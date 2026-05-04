"""Python Phase 1 end-to-end smoke — runs all three fixtures in sequence.

Acceptance gates:
- Each fixture completes in <5 minutes (wall clock)
- Each fixture surfaces at most 5 warnings
- Each fixture produces a non-empty graph
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

# Importing the plugins package registers all built-in plugins.
import app.stages.plugins  # noqa: F401
from app.models.context import AnalysisContext

FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures"

FIXTURES: list[tuple[str, str]] = [
    ("fastapi-todo", "e2e-fastapi-todo"),
    ("django-blog", "e2e-django-blog"),
    ("flask-inventory", "e2e-flask-inventory"),
]

MAX_DURATION_SECONDS: float = 300.0
MAX_WARNINGS: int = 5


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.scip_python,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH"),
    pytest.mark.skipif(
        shutil.which("scip-python") is None, reason="scip-python not on PATH"
    ),
]


async def _run_full_pipeline(
    fixture_root: Path, project_id: str
) -> tuple[AnalysisContext, float]:
    """Run stages 1-7 (skip Stage 8 Neo4j writer + Stage 9 transactions)."""
    from app.stages.dependencies import resolve_dependencies
    from app.stages.discovery import discover_project
    from app.stages.enricher import enrich_graph
    from app.stages.linker import run_cross_tech_linker
    from app.stages.plugins.registry import run_framework_plugins
    from app.stages.scip.indexer import run_scip_indexers
    from app.stages.treesitter.parser import parse_with_treesitter

    start = time.monotonic()
    manifest = discover_project(fixture_root)
    environment = await resolve_dependencies(manifest)
    graph = await parse_with_treesitter(manifest)
    ctx = AnalysisContext(
        project_id=project_id,
        graph=graph,
        manifest=manifest,
        environment=environment,
    )
    await run_scip_indexers(ctx)
    await run_framework_plugins(ctx)
    await run_cross_tech_linker(ctx)
    await enrich_graph(ctx)
    return ctx, time.monotonic() - start


@pytest.mark.parametrize("fixture_name,project_id", FIXTURES)
async def test_fixture_meets_phase1_acceptance_gates(
    fixture_name: str, project_id: str
) -> None:
    fixture = FIXTURES_ROOT / fixture_name
    assert fixture.is_dir(), f"fixture dir missing: {fixture}"

    ctx, duration = await _run_full_pipeline(fixture, project_id)

    assert duration < MAX_DURATION_SECONDS, (
        f"{fixture_name} pipeline took {duration:.1f}s (budget {MAX_DURATION_SECONDS}s)"
    )
    assert len(ctx.warnings) <= MAX_WARNINGS, (
        f"{fixture_name} emitted {len(ctx.warnings)} warnings "
        f"(budget {MAX_WARNINGS}): {ctx.warnings}"
    )
    assert ctx.graph.node_count > 0, f"{fixture_name} produced an empty graph"
    assert ctx.graph.edge_count > 0, f"{fixture_name} produced no edges"
