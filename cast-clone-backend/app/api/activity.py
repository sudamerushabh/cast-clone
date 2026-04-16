"""Activity feed API endpoint -- admin only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import require_admin
from app.models.db import ActivityLog, User
from app.schemas.activity import ActivityLogResponse
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ActionCount(BaseModel):
    action: str
    count: int


class DailyCount(BaseModel):
    date: str  # ISO date YYYY-MM-DD
    count: int


class ActivityStatsResponse(BaseModel):
    total: int
    by_action: list[ActionCount]
    by_day: list[DailyCount]
    unique_users: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ActivityLogResponse])
async def get_activity_feed(
    limit: int = Query(default=50, ge=1, le=200),
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    category: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> list[ActivityLogResponse]:
    """Get recent activity log entries. Admin only.

    Filters by user_id, action type, category prefix, and date range.
    Returns most recent first.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    query = (
        select(ActivityLog)
        .options(joinedload(ActivityLog.user))
        .where(ActivityLog.created_at >= since)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )

    if user_id:
        query = query.where(ActivityLog.user_id == user_id)
    if action:
        query = query.where(ActivityLog.action == action)
    if category:
        # Filter by action prefix, e.g. "project" matches "project.created", "project.deleted"
        query = query.where(ActivityLog.action.startswith(category + "."))

    result = await session.execute(query)
    entries = result.scalars().unique().all()
    return [
        ActivityLogResponse.model_validate(e, from_attributes=True) for e in entries
    ]


@router.get("/stats", response_model=ActivityStatsResponse)
async def get_activity_stats(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> ActivityStatsResponse:
    """Get activity statistics for the dashboard. Admin only."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Total count
    total_q = await session.execute(
        select(func.count(ActivityLog.id)).where(ActivityLog.created_at >= since)
    )
    total = total_q.scalar_one()

    # By action
    action_q = await session.execute(
        select(ActivityLog.action, func.count(ActivityLog.id))
        .where(ActivityLog.created_at >= since)
        .group_by(ActivityLog.action)
        .order_by(func.count(ActivityLog.id).desc())
    )
    by_action = [
        ActionCount(action=row[0], count=row[1]) for row in action_q.all()
    ]

    # By day (last N days)
    day_q = await session.execute(
        select(
            func.date(ActivityLog.created_at).label("day"),
            func.count(ActivityLog.id),
        )
        .where(ActivityLog.created_at >= since)
        .group_by(func.date(ActivityLog.created_at))
        .order_by(func.date(ActivityLog.created_at))
    )
    by_day = [
        DailyCount(date=str(row[0]), count=row[1]) for row in day_q.all()
    ]

    # Unique users
    users_q = await session.execute(
        select(func.count(func.distinct(ActivityLog.user_id)))
        .where(ActivityLog.created_at >= since)
        .where(ActivityLog.user_id.isnot(None))
    )
    unique_users = users_q.scalar_one()

    return ActivityStatsResponse(
        total=total,
        by_action=by_action,
        by_day=by_day,
        unique_users=unique_users,
    )
