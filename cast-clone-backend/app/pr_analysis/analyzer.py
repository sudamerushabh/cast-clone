"""PR analysis orchestrator -- coordinates the full analysis pipeline."""

from __future__ import annotations

import time

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.git import create_platform_client
from app.pr_analysis.ai import generate_pr_summary
from app.pr_analysis.diff_mapper import DiffMapper
from app.pr_analysis.drift_detector import DriftDetector
from app.pr_analysis.impact_aggregator import ImpactAggregator
from app.pr_analysis.models import (
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)
from app.pr_analysis.risk_scorer import classify_risk
from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)


async def log_activity(
    session: AsyncSession,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
    user_id: str | None = None,
) -> None:
    """Log an activity, delegating to the activity service if available."""
    try:
        from app.services.activity import log_activity as _log_activity

        await _log_activity(
            session=session,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            user_id=user_id,
        )
    except Exception:
        logger.warning("activity_log_failed", action=action, exc_info=True)


async def run_pr_analysis(
    pr_record,  # PrAnalysis ORM instance
    session: AsyncSession,
    store: GraphStore,
    api_token: str,
    repo_path: str,
    app_name: str,
) -> None:
    """Run the full PR analysis pipeline.

    Steps:
    1. Fetch diff via Git platform API
    2. Map diff to graph nodes
    3. Compute impact per changed node + aggregate
    4. Detect architecture drift
    5. Classify risk
    6. Generate AI summary
    7. Store results
    """
    start_time = time.monotonic()

    try:
        pr_record.status = "analyzing"
        await session.commit()

        # 1. Fetch diff
        diff = await _fetch_diff(
            platform=pr_record.platform,
            repo_url=_get_repo_url(pr_record),
            pr_number=pr_record.pr_number,
            token=api_token,
        )

        pr_record.files_changed = diff.total_files_changed
        pr_record.additions = diff.total_additions
        pr_record.deletions = diff.total_deletions

        # 2. Map diff to graph nodes
        mapper = _create_diff_mapper(store, app_name)
        map_result = await mapper.map_diff_to_nodes(diff)

        pr_record.changed_node_count = len(map_result.changed_nodes)

        # 3. Compute aggregated impact
        aggregator = _create_impact_aggregator(store, app_name)
        impact = await aggregator.compute_aggregated_impact(map_result.changed_nodes)

        pr_record.blast_radius_total = impact.total_blast_radius

        # 4. Detect drift
        detector = _create_drift_detector(store, app_name)
        drift = await detector.detect_drift(
            map_result.changed_nodes,
            new_files=map_result.new_files,
        )

        # 5. Classify risk
        risk_level = classify_risk(impact)
        pr_record.risk_level = risk_level

        # 6. Generate AI summary
        pr_event = PullRequestEvent(
            platform=GitPlatform(pr_record.platform),
            repo_url=_get_repo_url(pr_record),
            pr_number=pr_record.pr_number,
            pr_title=pr_record.pr_title,
            pr_description=pr_record.pr_description or "",
            author=pr_record.pr_author,
            source_branch=pr_record.source_branch,
            target_branch=pr_record.target_branch,
            action="opened",
            commit_sha=pr_record.commit_sha,
            created_at="",
        )

        summary_result = await generate_pr_summary(
            pr_event=pr_event,
            diff=diff,
            impact=impact,
            drift=drift,
            risk_level=risk_level,
            repo_path=repo_path,
            graph_store=store,
            app_name=app_name,
        )
        pr_record.ai_summary = summary_result.summary
        pr_record.ai_summary_tokens = summary_result.tokens_used

        # 7. Store structured results as JSON
        pr_record.impact_summary = {
            "total_blast_radius": impact.total_blast_radius,
            "by_type": impact.by_type,
            "by_depth": impact.by_depth,
            "by_layer": impact.by_layer,
            "changed_nodes": [
                {"fqn": n.fqn, "name": n.name, "type": n.type, "change_type": n.change_type}
                for n in impact.changed_nodes
            ],
            "downstream_affected": [
                {"fqn": a.fqn, "name": a.name, "type": a.type, "file": a.file, "depth": a.depth}
                for a in impact.downstream_affected[:200]
            ],
            "upstream_dependents": [
                {"fqn": a.fqn, "name": a.name, "type": a.type, "file": a.file, "depth": a.depth}
                for a in impact.upstream_dependents[:200]
            ],
            "downstream_count": len(impact.downstream_affected),
            "upstream_count": len(impact.upstream_dependents),
            "cross_tech": [
                {"kind": ct.kind, "name": ct.name, "detail": ct.detail}
                for ct in impact.cross_tech_impacts
            ],
            "transactions_affected": impact.transactions_affected,
            "new_files": map_result.new_files,
            "non_graph_files": map_result.non_graph_files,
        }

        pr_record.drift_report = {
            "has_drift": drift.has_drift,
            "potential_new_module_deps": [
                {"from_module": d.from_module, "to_module": d.to_module}
                for d in drift.potential_new_module_deps
            ],
            "circular_deps_affected": drift.circular_deps_affected,
            "new_files_outside_modules": drift.new_files_outside_modules,
        }

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        pr_record.analysis_duration_ms = elapsed_ms
        pr_record.status = "completed"
        await session.commit()

        logger.info(
            "pr_analysis_completed",
            analysis_id=pr_record.id,
            risk_level=risk_level,
            blast_radius=impact.total_blast_radius,
            duration_ms=elapsed_ms,
        )

        # Activity log
        await log_activity(
            session=session,
            action="pr_analysis.completed",
            resource_type="pr_analysis",
            resource_id=pr_record.id,
            details={
                "pr_number": pr_record.pr_number,
                "risk_level": risk_level,
                "blast_radius": impact.total_blast_radius,
                "duration_ms": elapsed_ms,
            },
        )

    except Exception as exc:
        logger.error(
            "pr_analysis_failed",
            analysis_id=pr_record.id,
            error=str(exc),
            exc_info=True,
        )
        pr_record.status = "failed"
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        pr_record.analysis_duration_ms = elapsed_ms
        await session.commit()

        await log_activity(
            session=session,
            action="pr_analysis.failed",
            resource_type="pr_analysis",
            resource_id=pr_record.id,
            details={"error": str(exc)},
        )


def _get_repo_url(pr_record) -> str:
    """Extract repo URL from the PR record's pr_url or fall back."""
    if pr_record.pr_url:
        # PR URL like https://github.com/org/repo/pull/42 -> https://github.com/org/repo
        parts = pr_record.pr_url.split("/")
        for i, p in enumerate(parts):
            if p in ("pull", "pulls", "merge_requests", "pull-requests"):
                return "/".join(parts[:i])
    return ""


async def _fetch_diff(
    platform: str, repo_url: str, pr_number: int, token: str
) -> PRDiff:
    client = create_platform_client(platform)
    return await client.fetch_diff(repo_url, pr_number, token)


def _create_diff_mapper(store: GraphStore, app_name: str) -> DiffMapper:
    return DiffMapper(store, app_name)


def _create_impact_aggregator(store: GraphStore, app_name: str) -> ImpactAggregator:
    return ImpactAggregator(store, app_name)


def _create_drift_detector(store: GraphStore, app_name: str) -> DriftDetector:
    return DriftDetector(store, app_name)


async def mark_analyses_stale(
    session: AsyncSession, repository_id: str
) -> None:
    """Mark all completed PR analyses for a repository as stale.

    Called after a full re-analysis to indicate the graph has changed.
    """
    from app.models.db import PrAnalysis

    await session.execute(
        update(PrAnalysis)
        .where(
            PrAnalysis.repository_id == repository_id,
            PrAnalysis.status == "completed",
        )
        .values(status="stale")
    )
    await session.commit()
    logger.info("pr_analyses_marked_stale", repository_id=repository_id)
