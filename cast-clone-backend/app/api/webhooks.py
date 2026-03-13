"""Webhook receiver endpoints for Git platform events."""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.git import create_platform_client
from app.models.db import PrAnalysis, Repository, RepositoryGitConfig
from app.schemas.webhooks import WebhookResponse
from app.services.crypto import decrypt_token
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post(
    "/{platform}/{repo_id}",
    status_code=202,
    response_model=WebhookResponse,
)
async def receive_webhook(
    platform: Literal["github", "gitlab", "bitbucket", "gitea"],
    repo_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> WebhookResponse | JSONResponse:
    """Receive a webhook event from a Git platform.

    This endpoint is unauthenticated (no JWT) and is instead protected
    by signature verification using the shared webhook secret.
    """
    log = logger.bind(platform=platform, repo_id=repo_id)

    # 1. Look up git config
    result = await session.execute(
        select(RepositoryGitConfig).where(
            RepositoryGitConfig.repository_id == repo_id,
            RepositoryGitConfig.platform == platform,
            RepositoryGitConfig.is_active.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        await log.awarn("webhook_config_not_found")
        raise HTTPException(status_code=404, detail="Git config not found for repository")

    # 2. Read raw body and headers
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    # 3. Verify signature
    client = create_platform_client(platform)
    if not client.verify_webhook_signature(headers, body, config.webhook_secret):
        await log.awarn("webhook_signature_invalid")
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    # 4. Parse webhook event
    event = client.parse_webhook(headers, body)
    if event is None:
        await log.ainfo("webhook_event_ignored", reason="not a PR event")
        return JSONResponse(
            status_code=200,
            content=WebhookResponse(
                status="ignored", message="Not a relevant PR event"
            ).model_dump(),
        )

    # 5. Check if target branch is monitored
    if event.target_branch not in config.monitored_branches:
        await log.ainfo(
            "webhook_branch_ignored",
            target_branch=event.target_branch,
            monitored=config.monitored_branches,
        )
        return JSONResponse(
            status_code=200,
            content=WebhookResponse(
                status="ignored",
                message=f"Branch '{event.target_branch}' is not monitored",
            ).model_dump(),
        )

    # 6. Create PrAnalysis record
    pr_analysis = PrAnalysis(
        repository_id=repo_id,
        platform=platform,
        pr_number=event.pr_number,
        pr_title=event.pr_title,
        pr_description=event.pr_description,
        pr_author=event.author,
        source_branch=event.source_branch,
        target_branch=event.target_branch,
        commit_sha=event.commit_sha,
        pr_url=event.raw_payload.get("html_url") or event.raw_payload.get("url"),
        status="pending",
    )
    session.add(pr_analysis)
    await session.commit()
    await session.refresh(pr_analysis)

    await log.ainfo(
        "webhook_accepted",
        pr_number=event.pr_number,
        pr_analysis_id=pr_analysis.id,
    )

    # 7. Queue background analysis
    settings = get_settings()
    background_tasks.add_task(
        _run_analysis_background,
        pr_analysis_id=pr_analysis.id,
        repo_id=repo_id,
        api_token_encrypted=config.api_token_encrypted,
        platform=platform,
        secret_key=settings.secret_key,
    )

    return WebhookResponse(
        status="accepted",
        message=f"PR #{event.pr_number} queued for analysis",
        pr_analysis_id=pr_analysis.id,
    )


async def _run_analysis_background(
    pr_analysis_id: str,
    repo_id: str,
    api_token_encrypted: str,
    platform: str,
    secret_key: str,
) -> None:
    """Background task wrapper for PR analysis.

    Flow:
    1. Load repo and PR record
    2. Ensure projects exist for both source and target branches
    3. Pull latest code for both branches
    4. Run full code analysis on both branches (if needed)
    5. Run PR-specific impact analysis against target branch graph
    """
    from app.orchestrator.pipeline import run_analysis_pipeline
    from app.pr_analysis.analyzer import run_pr_analysis
    from app.services.branch_manager import BranchManager
    from app.services.clone import get_current_commit
    from app.services.postgres import get_background_session

    async with get_background_session() as session:
        # Load PR record
        result = await session.execute(
            select(PrAnalysis).where(PrAnalysis.id == pr_analysis_id)
        )
        pr_record = result.scalar_one_or_none()
        if not pr_record:
            logger.error("pr_analysis_not_found", id=pr_analysis_id)
            return

        # Load repository
        repo_result = await session.execute(
            select(Repository).where(Repository.id == repo_id)
        )
        repo = repo_result.scalar_one_or_none()
        if not repo or not repo.local_path:
            logger.error("repository_not_found_or_not_cloned", id=repo_id)
            pr_record.status = "failed"
            await session.commit()
            return

        # Fetch all remote refs so local branch clones can find any branch
        try:
            from app.services.clone import fetch_all_refs
            await fetch_all_refs(repo.local_path)
        except Exception as exc:
            logger.warning("main_repo_fetch_failed", error=str(exc))

        mgr = BranchManager(session)

        # Ensure both branch projects exist and are cloned
        target_branch = pr_record.target_branch
        source_branch = pr_record.source_branch

        try:
            target_project = await mgr.ensure_branch_project(repo, target_branch)
            source_project = await mgr.ensure_branch_project(repo, source_branch)
            await session.commit()
        except Exception as exc:
            logger.error("branch_setup_failed", error=str(exc), exc_info=True)
            pr_record.status = "failed"
            await session.commit()
            return

        # Analyze target branch first (PR impact analysis needs this graph)
        if await mgr.needs_analysis(target_project):
            try:
                await run_analysis_pipeline(target_project.id)
                commit = await get_current_commit(target_project.source_path)
                if commit:
                    target_project.last_analyzed_commit = commit
                await session.commit()
            except Exception as exc:
                logger.error(
                    "target_branch_analysis_failed",
                    branch=target_branch, error=str(exc), exc_info=True,
                )
                # Continue anyway — PR analysis can still try with existing graph

        # Analyze source branch
        if await mgr.needs_analysis(source_project):
            try:
                await run_analysis_pipeline(source_project.id)
                commit = await get_current_commit(source_project.source_path)
                if commit:
                    source_project.last_analyzed_commit = commit
                await session.commit()
            except Exception as exc:
                logger.warning(
                    "source_branch_analysis_failed",
                    branch=source_branch, error=str(exc), exc_info=True,
                )

        # Now run the PR-specific analysis (diff, impact, drift, AI)
        # Uses target branch graph for impact analysis
        app_name = f"{repo_id}:{target_branch}"

        store = Neo4jGraphStore(get_driver())
        api_token = decrypt_token(api_token_encrypted, secret_key)

        await run_pr_analysis(
            pr_record=pr_record,
            session=session,
            store=store,
            api_token=api_token,
            repo_path=target_project.source_path,
            app_name=app_name,
        )
