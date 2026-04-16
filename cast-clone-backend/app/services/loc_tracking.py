"""Per-repository LOC tracking -- recalculation logic.

Each repository's billable LOC = max(latest completed run LOC) across all
its branches (Projects).  This module provides the recalculation function
called after scan completion and branch deletion.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AnalysisRun, Project, RepositoryLocTracking
from app.services.loc_usage import invalidate_cumulative_loc_cache

logger = structlog.get_logger(__name__)


async def recalculate_repo_loc(
    repository_id: str,
    session: AsyncSession,
) -> RepositoryLocTracking:
    """Recompute billable LOC for a repository from its branches' latest runs.

    Idempotent: upserts the tracking row.  Safe to call concurrently -- the
    last writer wins with the same correct result.

    Returns the upserted ``RepositoryLocTracking`` row.
    """
    # 1. Subquery: for each project (branch), find the latest completed_at
    #    among completed runs.  This avoids PostgreSQL-only DISTINCT ON and
    #    works on SQLite for unit tests.
    latest_run_sq = (
        select(
            AnalysisRun.project_id,
            func.max(AnalysisRun.completed_at).label("max_completed_at"),
        )
        .where(
            AnalysisRun.status == "completed",
            AnalysisRun.total_loc.isnot(None),
        )
        .group_by(AnalysisRun.project_id)
        .subquery()
    )

    stmt = (
        select(Project.id, Project.branch, AnalysisRun.total_loc)
        .join(AnalysisRun, AnalysisRun.project_id == Project.id)
        .join(
            latest_run_sq,
            (latest_run_sq.c.project_id == AnalysisRun.project_id)
            & (latest_run_sq.c.max_completed_at == AnalysisRun.completed_at),
        )
        .where(
            Project.repository_id == repository_id,
            AnalysisRun.status == "completed",
            AnalysisRun.total_loc.isnot(None),
        )
    )
    rows = (await session.execute(stmt)).all()

    # 2. Build breakdown and find max.
    breakdown: dict[str, int] = {}
    max_loc = 0
    max_project_id: str | None = None
    max_branch_name: str | None = None

    for project_id, branch, total_loc in rows:
        branch_name = branch or "unknown"
        breakdown[branch_name] = total_loc
        if total_loc > max_loc:
            max_loc = total_loc
            max_project_id = project_id
            max_branch_name = branch_name

    # 3. Upsert tracking row.
    result = await session.execute(
        select(RepositoryLocTracking).where(
            RepositoryLocTracking.repository_id == repository_id
        )
    )
    tracking = result.scalar_one_or_none()

    if tracking is None:
        tracking = RepositoryLocTracking(
            repository_id=repository_id,
            billable_loc=max_loc,
            max_loc_project_id=max_project_id,
            max_loc_branch_name=max_branch_name,
            breakdown=breakdown,
            last_recalculated_at=datetime.now(UTC),
        )
        session.add(tracking)
    else:
        tracking.billable_loc = max_loc
        tracking.max_loc_project_id = max_project_id
        tracking.max_loc_branch_name = max_branch_name
        tracking.breakdown = breakdown
        tracking.last_recalculated_at = datetime.now(UTC)

    await session.flush()

    invalidate_cumulative_loc_cache()
    logger.info(
        "loc_tracking.recalculated",
        repository_id=repository_id,
        billable_loc=max_loc,
        max_branch=max_branch_name,
        branch_count=len(breakdown),
    )
    return tracking
