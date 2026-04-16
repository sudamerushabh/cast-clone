"""Activity logging service -- fire-and-forget action recording.

Uses a dedicated session to avoid double-commit issues when called
after the caller's primary transaction has already committed.
"""

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
    """Record an activity log entry using a fresh independent session.

    This function never raises -- logging failures are swallowed and logged.
    Safe to call before or after the caller's commit.
    """
    try:
        from app.services.postgres import get_engine

        engine = get_engine()
        async with engine.begin() as conn:
            from sqlalchemy import text
            import json
            from uuid import uuid4

            await conn.execute(
                text(
                    "INSERT INTO activity_log (id, user_id, action, resource_type, resource_id, details) "
                    "VALUES (:id, :user_id, :action, :resource_type, :resource_id, :details)"
                ),
                {
                    "id": str(uuid4()),
                    "user_id": user_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "details": json.dumps(details) if details else None,
                },
            )
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
