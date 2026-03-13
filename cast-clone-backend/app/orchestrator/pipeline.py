"""Analysis pipeline orchestrator — runs 9 stages sequentially.

Each stage function delegates to the real implementation from app.stages.*.
Services (GraphStore) are injected via PipelineServices.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select

from app.models.context import AnalysisContext
from app.models.db import AnalysisRun, Project
from app.orchestrator.progress import WebSocketProgressReporter
from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)


@dataclass
class PipelineServices:
    """Injected dependencies for the pipeline stages."""

    graph_store: GraphStore
    source_path: Path


@dataclass
class PipelineStage:
    """Definition of a single pipeline stage."""

    name: str
    description: str
    critical: bool = False  # If True, failure aborts the pipeline


# ── Stage wrapper functions ──────────────────────────────────────────────
# Each function accepts (context, services) and delegates to the real stage.


async def _stage_discovery(
    context: AnalysisContext, services: PipelineServices
) -> None:
    """Stage 1: Discover project files, languages, frameworks."""
    from app.stages.discovery import discover_project

    context.manifest = discover_project(services.source_path)


async def _stage_dependencies(
    context: AnalysisContext, services: PipelineServices
) -> None:
    """Stage 2: Resolve build dependencies."""
    from app.stages.dependencies import resolve_dependencies

    assert context.manifest is not None, "Stage 1 (discovery) must run first"
    context.environment = await resolve_dependencies(context.manifest)


async def _stage_parsing(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 3: Parse source files with tree-sitter."""
    from app.stages.treesitter.parser import parse_with_treesitter

    assert context.manifest is not None, "Stage 1 (discovery) must run first"
    graph = await parse_with_treesitter(context.manifest)
    context.graph.merge(graph)


async def _stage_scip(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 4: Run SCIP indexers for type resolution."""
    from app.stages.scip.indexer import run_scip_indexers

    await run_scip_indexers(context)


async def _stage_lsp_fallback(
    context: AnalysisContext, services: PipelineServices
) -> None:
    """Stage 4b: LSP fallback for languages where SCIP failed.

    Only runs if there are languages that SCIP didn't cover.
    Currently a no-op — LSP fallback is deferred to later phases.
    """
    if context.languages_needing_fallback:
        logger.info(
            "pipeline.lsp_fallback.skipped",
            languages=context.languages_needing_fallback,
            reason="LSP fallback not yet implemented",
        )


async def _stage_plugins(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 5: Run framework-specific plugins."""
    from app.stages.plugins.registry import run_framework_plugins

    await run_framework_plugins(context)


async def _stage_linking(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 6: Link cross-technology dependencies."""
    from app.stages.linker import run_cross_tech_linker

    await run_cross_tech_linker(context)


async def _stage_enrichment(
    context: AnalysisContext, services: PipelineServices
) -> None:
    """Stage 7: Compute metrics and run community detection."""
    from app.stages.enricher import enrich_graph

    await enrich_graph(context)


async def _stage_writing(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 8: Write graph to Neo4j."""
    from app.stages.writer import write_to_neo4j

    await write_to_neo4j(context, services.graph_store)


async def _stage_transactions(
    context: AnalysisContext, services: PipelineServices
) -> None:
    """Stage 9: Discover transaction flows."""
    from app.stages.transactions import discover_transactions

    await discover_transactions(context)


# ── Stage registry ────────────────────────────────────────────────────────

StageFunc = Callable[[AnalysisContext, PipelineServices], Coroutine[Any, Any, None]]


PIPELINE_STAGES: list[PipelineStage] = [
    PipelineStage("discovery", "Scanning filesystem...", critical=True),
    PipelineStage("dependencies", "Resolving dependencies..."),
    PipelineStage("parsing", "Parsing source files..."),
    PipelineStage("scip", "Running SCIP indexers..."),
    PipelineStage("lsp_fallback", "LSP fallback for unsupported languages..."),
    PipelineStage("plugins", "Running framework plugins..."),
    PipelineStage("linking", "Linking cross-technology dependencies..."),
    PipelineStage("enrichment", "Computing metrics and communities..."),
    PipelineStage("transactions", "Discovering transaction flows..."),
    PipelineStage("writing", "Writing to database...", critical=True),
]

_STAGE_FUNCS: dict[str, StageFunc] = {
    "discovery": _stage_discovery,
    "dependencies": _stage_dependencies,
    "parsing": _stage_parsing,
    "scip": _stage_scip,
    "lsp_fallback": _stage_lsp_fallback,
    "plugins": _stage_plugins,
    "linking": _stage_linking,
    "enrichment": _stage_enrichment,
    "writing": _stage_writing,
    "transactions": _stage_transactions,
}


def get_session_factory():
    """Get the async session factory. Separated for testability."""
    from app.services.postgres import _session_factory

    assert _session_factory is not None, "PostgreSQL not initialized"
    return _session_factory


# ── Main pipeline function ────────────────────────────────────────────────


async def run_analysis_pipeline(
    project_id: str,
    run_id: str | None = None,
    services: PipelineServices | None = None,
) -> None:
    """Run the full 9-stage analysis pipeline.

    Called as a FastAPI BackgroundTask. Loads the project from DB,
    runs each stage sequentially, updates status, and reports progress
    via WebSocket.

    Args:
        project_id: UUID of the project to analyze.
        run_id: UUID of the existing AnalysisRun record (created by trigger endpoint).
        services: Injected pipeline services. If None, loads from app state.

    Raises:
        ValueError: If the project is not found in the database.
    """
    session_factory = get_session_factory()
    ws = WebSocketProgressReporter(project_id)
    pipeline_start = time.monotonic()

    async with session_factory() as session:
        # Load project
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        # Build services if not injected
        if services is None:
            from app.services.neo4j import Neo4jGraphStore, get_driver

            services = PipelineServices(
                graph_store=Neo4jGraphStore(get_driver()),
                source_path=Path(project.source_path),
            )

        # Load or create analysis run record
        if run_id:
            run_result = await session.execute(
                select(AnalysisRun).where(AnalysisRun.id == run_id)
            )
            run = run_result.scalar_one_or_none()
            if run is None:
                run = AnalysisRun(project_id=project_id, status="running")
                session.add(run)
            else:
                run.status = "running"
        else:
            run = AnalysisRun(project_id=project_id, status="running")
            session.add(run)

        await session.commit()

        # Initialize context
        context = AnalysisContext(project_id=project_id)

        # Run each stage
        for stage_def in PIPELINE_STAGES:
            stage_func = _STAGE_FUNCS[stage_def.name]
            stage_start = time.monotonic()

            try:
                await ws.emit(stage_def.name, "running", stage_def.description)
                logger.info(
                    "pipeline.stage.start",
                    project_id=project_id,
                    stage=stage_def.name,
                )

                await stage_func(context, services)

                elapsed = time.monotonic() - stage_start
                await ws.emit(
                    stage_def.name,
                    "complete",
                    details={"duration_seconds": round(elapsed, 2)},
                )
                logger.info(
                    "pipeline.stage.complete",
                    project_id=project_id,
                    stage=stage_def.name,
                    duration=round(elapsed, 2),
                )

                # Track current stage in run record
                run.stage = stage_def.name

            except Exception as e:
                elapsed = time.monotonic() - stage_start
                logger.error(
                    "pipeline.stage.failed",
                    project_id=project_id,
                    stage=stage_def.name,
                    error=str(e),
                    duration=round(elapsed, 2),
                )
                await ws.emit(
                    stage_def.name,
                    "failed",
                    message=str(e),
                    details={"duration_seconds": round(elapsed, 2)},
                )

                if stage_def.critical:
                    # Critical stage failure — abort pipeline
                    project.status = "failed"
                    run.status = "failed"
                    run.error_message = f"Critical stage '{stage_def.name}' failed: {e}"
                    await session.commit()
                    await ws.emit_error(
                        f"Pipeline aborted: stage '{stage_def.name}' failed: {e}"
                    )
                    raise
                else:
                    # Non-critical — warn and continue
                    context.warnings.append(f"Stage '{stage_def.name}' failed: {e}")

        # Pipeline complete
        total_elapsed = time.monotonic() - pipeline_start
        project.status = "analyzed"
        run.status = "completed"
        run.node_count = context.graph.node_count
        run.edge_count = context.graph.edge_count
        await session.commit()

        report = {
            "total_nodes": context.graph.node_count,
            "total_edges": context.graph.edge_count,
            "warnings": context.warnings,
            "duration_seconds": round(total_elapsed, 2),
        }
        await ws.emit_complete(report)

        logger.info(
            "pipeline.complete",
            project_id=project_id,
            duration=round(total_elapsed, 2),
            nodes=context.graph.node_count,
            edges=context.graph.edge_count,
            warnings=len(context.warnings),
        )
