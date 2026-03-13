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
from app.models.db import PrAnalysis, Project, Repository, ProjectGitConfig
from app.schemas.webhooks import WebhookResponse
from app.services.crypto import decrypt_token
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post(
    "/{platform}/{project_id}",
    status_code=202,
    response_model=WebhookResponse,
)
async def receive_webhook(
    platform: Literal["github", "gitlab", "bitbucket", "gitea"],
    project_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> WebhookResponse | JSONResponse:
    """Receive a webhook event from a Git platform.

    This endpoint is unauthenticated (no JWT) and is instead protected
    by signature verification using the shared webhook secret.
    """
    log = logger.bind(platform=platform, project_id=project_id)

    # 1. Look up git config
    result = await session.execute(
        select(ProjectGitConfig).where(
            ProjectGitConfig.project_id == project_id,
            ProjectGitConfig.platform == platform,
            ProjectGitConfig.is_active.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        await log.awarn("webhook_config_not_found")
        raise HTTPException(status_code=404, detail="Git config not found for project")

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
        project_id=project_id,
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
        project_id=project_id,
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
    project_id: str,
    api_token_encrypted: str,
    platform: str,
    secret_key: str,
) -> None:
    """Background task wrapper for PR analysis."""
    from app.pr_analysis.analyzer import run_pr_analysis
    from app.services.postgres import get_background_session

    async with get_background_session() as session:
        result = await session.execute(
            select(PrAnalysis).where(PrAnalysis.id == pr_analysis_id)
        )
        pr_record = result.scalar_one_or_none()
        if not pr_record:
            logger.error("pr_analysis_not_found", id=pr_analysis_id)
            return

        # Resolve repo_path from Project -> Repository -> local_path
        repo_path = ""
        proj_result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = proj_result.scalar_one_or_none()
        if project and project.repository_id:
            repo_result = await session.execute(
                select(Repository).where(Repository.id == project.repository_id)
            )
            repo = repo_result.scalar_one_or_none()
            if repo and repo.local_path:
                repo_path = repo.local_path

        store = Neo4jGraphStore(get_driver())
        api_token = decrypt_token(api_token_encrypted, secret_key)

        await run_pr_analysis(
            pr_record=pr_record,
            session=session,
            store=store,
            api_token=api_token,
            repo_path=repo_path,
            app_name=project_id,
        )
