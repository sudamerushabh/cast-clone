"""Analysis trigger and status API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AnalysisRun, Project
from app.orchestrator.pipeline import PipelineServices, run_analysis_pipeline
from app.schemas.analysis import (
    AnalysisStageStatus,
    AnalysisStatusResponse,
    AnalysisTriggerResponse,
)
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

# Pipeline stages in execution order — must match pipeline.PIPELINE_STAGES
_PIPELINE_STAGE_DEFS: list[tuple[str, str, str]] = [
    ("discovery", "Discovery", "Scanning filesystem for source files and frameworks"),
    ("dependencies", "Dependencies", "Resolving build tool dependencies"),
    ("parsing", "Parsing", "Parsing source files with tree-sitter"),
    ("scip", "Type Resolution", "Running SCIP indexers for cross-file resolution"),
    ("lsp_fallback", "LSP Fallback", "Fallback resolution for unsupported languages"),
    ("plugins", "Framework Plugins", "Detecting Spring, ASP.NET, EF Core patterns"),
    ("linking", "Cross-Tech Linking", "Matching HTTP endpoints and shared tables"),
    ("enrichment", "Enrichment", "Computing metrics, dependencies, and layers"),
    ("transactions", "Transactions", "Discovering API transaction flows"),
    ("writing", "Writing to Neo4j", "Persisting graph to database"),
    ("gds_enrichment", "Graph Algorithms", "Running community detection (Louvain)"),
]


def _build_stage_list(
    current_stage: str | None, project_status: str, stage_progress: int | None = None
) -> list[AnalysisStageStatus]:
    """Compute per-stage statuses from the current stage name.

    Stages are sequential so everything before current = completed,
    current = running, everything after = pending.
    If the project is already analyzed/failed, all stages are completed/skipped.
    """
    stage_names = [s[0] for s in _PIPELINE_STAGE_DEFS]

    # Not analyzing — return empty or all-completed
    if project_status != "analyzing":
        status_val = "completed" if project_status == "analyzed" else "pending"
        return [
            AnalysisStageStatus(
                name=name, label=label, status=status_val, description=desc
            )
            for name, label, desc in _PIPELINE_STAGE_DEFS
        ]

    # Find the index of the current stage
    try:
        current_idx = stage_names.index(current_stage) if current_stage else -1
    except ValueError:
        current_idx = -1

    result: list[AnalysisStageStatus] = []
    for i, (name, label, desc) in enumerate(_PIPELINE_STAGE_DEFS):
        if i < current_idx:
            status_val = "completed"
        elif i == current_idx:
            status_val = "running"
        else:
            status_val = "pending"
        result.append(
            AnalysisStageStatus(
                name=name,
                label=label,
                status=status_val,
                description=desc,
                progress=stage_progress if status_val == "running" else None,
            )
        )
    return result


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

    current_stage = latest_run.stage if latest_run else None
    stage_progress = latest_run.stage_progress if latest_run else None
    stages = _build_stage_list(current_stage, project.status, stage_progress)

    return AnalysisStatusResponse(
        project_id=project_id,
        status=project.status,
        current_stage=current_stage,
        stages=stages,
        started_at=latest_run.started_at if latest_run else None,
        completed_at=latest_run.completed_at if latest_run else None,
    )
