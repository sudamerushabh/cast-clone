"""Cumulative LOC usage query with a short in-process cache.

Billable LOC = SUM(repository_loc_tracking.billable_loc)
             + SUM(latest completed run LOC for standalone projects)

A 60-second cache prevents hammering the DB during hot loops (status polling,
dashboard renders); the cache is explicitly invalidated when a tracking row
is recalculated.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AnalysisRun, Project, RepositoryLocTracking
from app.services.postgres import get_background_session

logger = structlog.get_logger(__name__)

_CACHE_TTL_SECONDS = 60.0
_cache_value: int | None = None
_cache_set_at: float = 0.0
_lock = asyncio.Lock()


async def cumulative_loc(session: AsyncSession | None = None) -> int:
    """Return total billable LOC across all repositories + standalone projects.

    Cached for 60 seconds.  Call :func:`invalidate_cumulative_loc_cache` when
    a tracking row is recalculated to force a fresh read.
    """
    global _cache_value, _cache_set_at

    now = time.monotonic()
    if _cache_value is not None and (now - _cache_set_at) < _CACHE_TTL_SECONDS:
        return _cache_value

    async with _lock:
        now = time.monotonic()
        if (
            _cache_value is not None
            and (now - _cache_set_at) < _CACHE_TTL_SECONDS
        ):
            return _cache_value

        async def _query(s: AsyncSession) -> int:
            # Part 1: Sum of per-repo max-branch LOC from tracking table
            repo_result = await s.execute(
                select(
                    func.coalesce(func.sum(RepositoryLocTracking.billable_loc), 0)
                )
            )
            repo_total = int(repo_result.scalar_one())

            # Part 2: Standalone projects (no repository_id) — latest run each
            standalone_latest = (
                select(
                    AnalysisRun.project_id,
                    AnalysisRun.total_loc,
                )
                .join(Project, Project.id == AnalysisRun.project_id)
                .where(
                    Project.repository_id.is_(None),
                    AnalysisRun.status == "completed",
                    AnalysisRun.total_loc.isnot(None),
                )
                .order_by(AnalysisRun.project_id, AnalysisRun.completed_at.desc())
                .distinct(AnalysisRun.project_id)
                .subquery()
            )
            standalone_result = await s.execute(
                select(func.coalesce(func.sum(standalone_latest.c.total_loc), 0))
            )
            standalone_total = int(standalone_result.scalar_one())

            return repo_total + standalone_total

        if session is not None:
            value = await _query(session)
        else:
            async with get_background_session() as s:
                value = await _query(s)

        _cache_value = value
        _cache_set_at = time.monotonic()
        logger.debug("cumulative_loc.cache_refreshed", total_loc=value)
        return value


def invalidate_cumulative_loc_cache() -> None:
    """Clear the cumulative LOC cache; next call will re-query."""
    global _cache_value, _cache_set_at
    _cache_value = None
    _cache_set_at = 0.0
    logger.debug("cumulative_loc.cache_invalidated")
