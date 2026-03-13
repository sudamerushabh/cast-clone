"""Activity logging service -- fire-and-forget action recording."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import ActivityLog

logger = structlog.get_logger()


async def log_activity(
    session: AsyncSession,
    action: str,
    user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Record an activity log entry.

    This function never raises -- logging failures are swallowed and logged.
    It should be called after the primary operation has committed.
    """
    try:
        entry = ActivityLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        session.add(entry)
        await session.commit()
        logger.debug(
            "activity_logged",
            action=action,
            user_id=user_id,
            resource_type=resource_type,
        )
    except Exception:
        logger.warning(
            "activity_log_failed",
            action=action,
            exc_info=True,
        )
