"""Analysis trigger and status API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AnalysisRun, Project
from app.orchestrator.pipeline import PipelineServices, run_analysis_pipeline
from app.schemas.analysis import (
    AnalysisStatusResponse,
    AnalysisTriggerResponse,
)
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/projects", tags=["analysis"])


@router.post(
    "/{project_id}/analyze",
    response_model=AnalysisTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_analysis(
    project_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> AnalysisTriggerResponse:
    """Trigger analysis for a project. Runs as a background task."""
    # Load project
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # Prevent duplicate analysis
    if project.status == "analyzing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project {project_id} is already being analyzed",
        )

    # Create analysis run
    run = AnalysisRun(project_id=project_id, status="pending")
    session.add(run)

    # Update project status
    project.status = "analyzing"
    await session.commit()
    await session.refresh(run)

    # Build services and launch pipeline as background task
    services = PipelineServices(
        graph_store=Neo4jGraphStore(get_driver()),
        source_path=Path(project.source_path),
    )
    background_tasks.add_task(run_analysis_pipeline, project_id, run.id, services)

    return AnalysisTriggerResponse(
        project_id=project_id,
        run_id=run.id,
        status="analyzing",
        message="Analysis started",
    )


@router.get(
    "/{project_id}/status",
    response_model=AnalysisStatusResponse,
)
async def get_analysis_status(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> AnalysisStatusResponse:
    """Get the current analysis status for a project."""
    # Load project
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # Get latest analysis run
    run_result = await session.execute(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == project_id)
        .order_by(AnalysisRun.started_at.desc().nullslast())
        .limit(1)
    )
    latest_run = run_result.scalar_one_or_none()

    return AnalysisStatusResponse(
        project_id=project_id,
        status=project.status,
        current_stage=latest_run.stage if latest_run else None,
        started_at=latest_run.started_at if latest_run else None,
        completed_at=latest_run.completed_at if latest_run else None,
    )
