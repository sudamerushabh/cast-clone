"""Admin endpoints for AI usage statistics and cost tracking."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.models.db import AiUsageLog, Project, User
from app.schemas.ai_usage import (
    UsageByProjectItem,
    UsageBySourceItem,
    UsageLogResponse,
    UsageSummaryResponse,
)
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/admin/ai-usage", tags=["ai-usage"])


@router.get("", response_model=UsageSummaryResponse)
async def get_usage_summary(
    days: int = Query(default=30, ge=1, le=365),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UsageSummaryResponse:
    """Get aggregated AI usage summary (admin only).

    Returns total tokens, estimated cost, and breakdowns by source and project
    for the specified time window (default: last 30 days).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Totals
    totals_q = await session.execute(
        select(
            func.coalesce(func.sum(AiUsageLog.input_tokens), 0).label("total_input"),
            func.coalesce(func.sum(AiUsageLog.output_tokens), 0).label("total_output"),
            func.coalesce(func.sum(AiUsageLog.estimated_cost_usd), 0).label(
                "total_cost"
            ),
        ).where(AiUsageLog.created_at >= cutoff)
    )
    totals = totals_q.one()

    # By source
    source_q = await session.execute(
        select(
            AiUsageLog.source,
            func.sum(AiUsageLog.input_tokens).label("input_tokens"),
            func.sum(AiUsageLog.output_tokens).label("output_tokens"),
            func.coalesce(func.sum(AiUsageLog.estimated_cost_usd), 0).label("cost"),
            func.count().label("count"),
        )
        .where(AiUsageLog.created_at >= cutoff)
        .group_by(AiUsageLog.source)
        .order_by(func.sum(AiUsageLog.estimated_cost_usd).desc())
    )
    by_source = [
        UsageBySourceItem(
            source=row.source,
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            estimated_cost_usd=float(row.cost or 0),
            count=int(row.count),
        )
        for row in source_q.all()
    ]

    # By project
    project_q = await session.execute(
        select(
            AiUsageLog.project_id,
            Project.name.label("project_name"),
            func.sum(AiUsageLog.input_tokens).label("input_tokens"),
            func.sum(AiUsageLog.output_tokens).label("output_tokens"),
            func.coalesce(func.sum(AiUsageLog.estimated_cost_usd), 0).label("cost"),
            func.count().label("count"),
        )
        .join(Project, AiUsageLog.project_id == Project.id)
        .where(AiUsageLog.created_at >= cutoff)
        .group_by(AiUsageLog.project_id, Project.name)
        .order_by(func.sum(AiUsageLog.estimated_cost_usd).desc())
    )
    by_project = [
        UsageByProjectItem(
            project_id=row.project_id,
            project_name=row.project_name or "Unknown",
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            estimated_cost_usd=float(row.cost or 0),
            count=int(row.count),
        )
        for row in project_q.all()
    ]

    return UsageSummaryResponse(
        total_input_tokens=int(totals.total_input),
        total_output_tokens=int(totals.total_output),
        total_estimated_cost_usd=float(totals.total_cost),
        by_source=by_source,
        by_project=by_project,
    )


@router.get("/project/{project_id}", response_model=list[UsageLogResponse])
async def get_project_usage(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[UsageLogResponse]:
    """Get recent AI usage log entries for a specific project (admin only)."""
    result = await session.execute(
        select(AiUsageLog)
        .where(AiUsageLog.project_id == project_id)
        .order_by(AiUsageLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [UsageLogResponse.model_validate(log) for log in logs]
