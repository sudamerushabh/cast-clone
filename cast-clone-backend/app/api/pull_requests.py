"""PR analysis list, detail, impact, drift, and re-analyze endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.config import Settings, get_settings
from app.models.db import PrAnalysis, ProjectGitConfig, User
from app.schemas.pull_requests import (
    PrAnalysisListResponse,
    PrAnalysisResponse,
    PrDriftResponse,
    PrImpactResponse,
)
from app.services.postgres import get_session

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/pull-requests",
    tags=["pull-requests"],
)


async def _get_pr_or_404(
    project_id: str, pr_analysis_id: str, session: AsyncSession
) -> PrAnalysis:
    result = await session.execute(
        select(PrAnalysis).where(
            PrAnalysis.id == pr_analysis_id,
            PrAnalysis.project_id == project_id,
        )
    )
    pr = result.scalar_one_or_none()
    if not pr:
        raise HTTPException(status_code=404, detail="PR analysis not found")
    return pr


@router.get("", response_model=PrAnalysisListResponse)
async def list_pr_analyses(
    project_id: str,
    status: str | None = Query(None),
    risk: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> PrAnalysisListResponse:
    """List PR analyses for a project, with optional filters."""
    base_filter = [PrAnalysis.project_id == project_id]
    if status:
        base_filter.append(PrAnalysis.status == status)
    if risk:
        base_filter.append(PrAnalysis.risk_level == risk)

    # Count
    count_q = select(func.count(PrAnalysis.id)).where(*base_filter)
    count_result = await session.execute(count_q)
    total = count_result.scalar() or 0

    # Fetch
    q = (
        select(PrAnalysis)
        .where(*base_filter)
        .order_by(PrAnalysis.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(q)
    items = result.scalars().all()

    return PrAnalysisListResponse(
        items=[PrAnalysisResponse.model_validate(pr) for pr in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{pr_analysis_id}", response_model=PrAnalysisResponse)
async def get_pr_analysis(
    project_id: str,
    pr_analysis_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> PrAnalysisResponse:
    """Get full PR analysis detail."""
    pr = await _get_pr_or_404(project_id, pr_analysis_id, session)
    return PrAnalysisResponse.model_validate(pr)


@router.get("/{pr_analysis_id}/impact")
async def get_pr_impact(
    project_id: str,
    pr_analysis_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    """Get detailed impact data for a PR analysis."""
    pr = await _get_pr_or_404(project_id, pr_analysis_id, session)
    if not pr.impact_summary:
        raise HTTPException(status_code=404, detail="Impact data not available")
    return {"pr_analysis_id": pr.id, **pr.impact_summary}


@router.get("/{pr_analysis_id}/drift")
async def get_pr_drift(
    project_id: str,
    pr_analysis_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    """Get drift report for a PR analysis."""
    pr = await _get_pr_or_404(project_id, pr_analysis_id, session)
    if not pr.drift_report:
        raise HTTPException(status_code=404, detail="Drift data not available")
    return {"pr_analysis_id": pr.id, **pr.drift_report}


@router.post("/{pr_analysis_id}/reanalyze", status_code=202)
async def reanalyze_pr(
    project_id: str,
    pr_analysis_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _user: User = Depends(get_current_user),
) -> dict:
    """Re-run analysis for a PR (e.g., after graph update)."""
    pr = await _get_pr_or_404(project_id, pr_analysis_id, session)

    # Get git config for API token
    config_result = await session.execute(
        select(ProjectGitConfig).where(ProjectGitConfig.project_id == project_id)
    )
    config = config_result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=400, detail="No git config — cannot re-analyze")

    pr.status = "pending"
    await session.commit()

    # Queue re-analysis (same background task as webhook)
    from app.api.webhooks import _run_analysis_background

    background_tasks.add_task(
        _run_analysis_background,
        pr_analysis_id=pr.id,
        project_id=project_id,
        api_token_encrypted=config.api_token_encrypted,
        platform=config.platform,
        secret_key=settings.secret_key,
    )

    return {"status": "queued", "pr_analysis_id": pr.id}
