"""Cumulative LOC usage query with a short in-process cache.

This is the heart of license enforcement: how many lines of code have been
successfully analyzed across all ``analysis_runs``.  A 60-second cache prevents
hammering the DB during hot loops (status polling, dashboard renders); the
cache is explicitly invalidated when an analysis run completes so the next
caller sees fresh data.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AnalysisRun
from app.services.postgres import get_background_session

logger = structlog.get_logger(__name__)

_CACHE_TTL_SECONDS = 60.0
_cache_value: int | None = None
_cache_set_at: float = 0.0
_lock = asyncio.Lock()


async def cumulative_loc(session: AsyncSession | None = None) -> int:
    """Return the sum of ``total_loc`` across completed analysis runs.

    Cached for 60 seconds.  Call :func:`invalidate_cumulative_loc_cache` when
    an analysis run completes to force a fresh read.

    Args:
        session: Optional injected session (used in tests or when inside an
            existing transaction).  When ``None``, a fresh background session
            is opened.
    """
    global _cache_value, _cache_set_at

    # Fast path: unlocked read.  Races are benign — worst case a second
    # caller wastes one DB query, but correctness is preserved.
    now = time.monotonic()
    if _cache_value is not None and (now - _cache_set_at) < _CACHE_TTL_SECONDS:
        return _cache_value

    async with _lock:
        # Re-check under the lock in case another coroutine just refreshed.
        now = time.monotonic()
        if (
            _cache_value is not None
            and (now - _cache_set_at) < _CACHE_TTL_SECONDS
        ):
            return _cache_value

        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.coalesce(func.sum(AnalysisRun.total_loc), 0)).where(
                    AnalysisRun.status == "completed"
                )
            )
            return int(result.scalar_one())

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
