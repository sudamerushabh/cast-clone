"""Analysis trigger and status API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_accessible_project,
    get_current_user,
    require_license_writable,
)
from app.models.db import AnalysisRun, Project, User
from app.orchestrator.pipeline import PipelineServices, run_analysis_pipeline
from app.orchestrator.progress import active_contexts
from app.schemas.analysis import (
    AnalysisStageStatus,
    AnalysisStatusResponse,
    AnalysisTriggerResponse,
)
from app.services.activity import log_activity
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

logger = structlog.get_logger(__name__)

_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}

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
    dependencies=[Depends(require_license_writable)],
)
async def trigger_analysis(
    project_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    project: Project = Depends(get_accessible_project),
    user: User = Depends(get_current_user),
) -> AnalysisTriggerResponse:
    """Trigger analysis for a project. Runs as a background task.

    Access control: ``get_accessible_project`` transitively requires
    ``get_current_user`` and enforces ownership (admin or repo creator).
    """
    # Prevent duplicate analysis
    if project.status == "analyzing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project {project_id} is already being analyzed",
        )

    # Create analysis run
    run = AnalysisRun(project_id=project_id, status="pending")
    session.add(run)
    project.status = "analyzing"
    await session.commit()
    await session.refresh(run)

    # Build services and launch pipeline as background task
    services = PipelineServices(
        graph_store=Neo4jGraphStore(get_driver()),
        source_path=Path(project.source_path),
    )
    background_tasks.add_task(run_analysis_pipeline, project_id, run.id, services)

    # Log activity using independent connection (fire-and-forget, never fails)
    await log_activity(
        session,
        "analysis.started",
        user_id=user.id,
        resource_type="project",
        resource_id=project_id,
        details={"run_id": run.id, "project_name": project.name},
    )

    return AnalysisTriggerResponse(
        project_id=project_id,
        run_id=run.id,
        status="analyzing",
        message="Analysis started",
    )


@router.delete(
    "/{project_id}/analyze",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_license_writable)],
)
async def cancel_analysis(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    project: Project = Depends(get_accessible_project),
    user: User = Depends(get_current_user),
) -> Response:
    """Cancel a running analysis for a project (CHAN-73).

    Finds the live ``AnalysisContext`` for this project in the
    in-memory ``active_contexts`` registry, flips
    ``context.cancelled=True``, and sets the latest ``AnalysisRun``
    row's status to ``"cancelled"``. The pipeline observes the flag
    between stages and exits cleanly; subprocesses receive SIGTERM
    (then SIGKILL after a grace window) via
    ``subprocess_utils.run_subprocess``.

    Status codes:
    - 204: cancellation flag set; pipeline will exit shortly.
    - 404: no active analysis run found for this project.
    - 409: the most recent run is already in a terminal state
      (``completed`` / ``failed`` / ``cancelled``).

    Access control mirrors ``POST /analyze``:
    ``get_accessible_project`` transitively requires
    ``get_current_user`` and enforces ownership.
    """
    # Look up the most recent run so we can validate state + persist cancelled.
    run_result = await session.execute(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == project_id)
        .order_by(AnalysisRun.started_at.desc().nullslast())
        .limit(1)
    )
    latest_run = run_result.scalar_one_or_none()

    if latest_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No analysis run found for project {project_id}",
        )

    if latest_run.status in _TERMINAL_RUN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Analysis run {latest_run.id} is already in terminal "
                f"status '{latest_run.status}'"
            ),
        )

    # Flip the in-memory flag if the pipeline is currently running.
    # Missing context just means the pipeline already exited between
    # the status check and here — we still persist the DB status so
    # the UI reflects the user's intent.
    context = active_contexts.get(project_id)
    if context is not None:
        context.cancelled = True

    latest_run.status = "cancelled"
    latest_run.completed_at = datetime.now(UTC)
    latest_run.error_message = "Cancelled by user"
    # Keep the project row out of the "analyzing" state so the UI
    # stops polling; the pipeline's own finally block would flip
    # this too, but doing it here avoids a window where the user
    # sees "analyzing" after they just cancelled.
    project.status = "created"
    await session.commit()

    await log_activity(
        session,
        "analysis.cancelled",
        user_id=user.id,
        resource_type="project",
        resource_id=project_id,
        details={"run_id": latest_run.id, "project_name": project.name},
    )

    logger.info(
        "analysis.cancel_requested",
        project_id=project_id,
        run_id=latest_run.id,
        user_id=user.id,
        had_live_context=context is not None,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{project_id}/status",
    response_model=AnalysisStatusResponse,
)
async def get_analysis_status(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    project: Project = Depends(get_accessible_project),
) -> AnalysisStatusResponse:
    """Get the current analysis status for a project.

    Access control: ``get_accessible_project`` transitively requires
    ``get_current_user`` and enforces ownership (admin or repo creator).
    """
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
