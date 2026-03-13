"""Activity feed API endpoint -- admin only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import require_admin
from app.models.db import ActivityLog, User
from app.schemas.activity import ActivityLogResponse
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


@router.get("", response_model=list[ActivityLogResponse])
async def get_activity_feed(
    limit: int = Query(default=50, ge=1, le=200),
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> list[ActivityLogResponse]:
    """Get recent activity log entries. Admin only.

    Filters by user_id and/or action type. Returns most recent first.
    """
    query = (
        select(ActivityLog)
        .options(joinedload(ActivityLog.user))
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )

    if user_id:
        query = query.where(ActivityLog.user_id == user_id)
    if action:
        query = query.where(ActivityLog.action == action)

    result = await session.execute(query)
    entries = result.scalars().unique().all()
    return [
        ActivityLogResponse.model_validate(e, from_attributes=True) for e in entries
    ]
