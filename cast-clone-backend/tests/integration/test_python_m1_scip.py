"""M1 acceptance: SCIP Python merge produces HIGH-confidence CALLS edges.

Gated by the `scip_python` pytest marker because it requires:
- `uv` on PATH
- `scip-python` v0.6.6 on PATH (or via Docker)
- Network access to PyPI
- ~5 minutes on a laptop

Run explicitly:
    uv run pytest tests/integration/test_python_m1_scip.py -v -m scip_python
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind
from app.stages.treesitter.extractors import register_extractor
from app.stages.treesitter.extractors.python import PythonExtractor

FIXTURES = Path(__file__).parent.parent / "fixtures"
FASTAPI_TODO = FIXTURES / "fastapi-todo"


pytestmark = [
    pytest.mark.integration,
    pytest.mark.scip_python,
    pytest.mark.skipif(
        shutil.which("uv") is None, reason="uv not on PATH"
    ),
    pytest.mark.skipif(
        shutil.which("scip-python") is None, reason="scip-python not on PATH"
    ),
]


@pytest.fixture(autouse=True)
def _ensure_python_extractor():
    register_extractor("python", PythonExtractor())
    yield


@pytest.mark.asyncio
async def test_fastapi_todo_scip_upgrades_cross_framework_calls():
    """M1 gate: >=80% of route-handler -> service CALLS edges upgrade to HIGH.

    This asserts the core value prop of M1: with the venv built and scip-python
    given VIRTUAL_ENV, Pyright resolves the imports and CALLS edges get upgraded
    from tree-sitter's LOW to SCIP's HIGH.
    """
    from app.stages.dependencies import resolve_dependencies
    from app.stages.discovery import discover_project
    from app.stages.scip.indexer import run_scip_indexers
    from app.stages.treesitter.parser import parse_with_treesitter

    manifest = discover_project(FASTAPI_TODO)
    environment = await resolve_dependencies(manifest)

    # Venv must have been built for the test to be meaningful
    assert environment.python_venv_path is not None, (
        "build_python_venv returned None -- uv venv or pip install failed"
    )

    graph = await parse_with_treesitter(manifest)
    ctx = AnalysisContext(
        project_id="fastapi-todo",
        graph=graph,
        manifest=manifest,
        environment=environment,
    )

    scip_result = await run_scip_indexers(ctx)
    assert "python" in scip_result.languages_resolved, (
        f"Python SCIP did not resolve. Failed: {scip_result.languages_failed}. "
        f"Warnings: {ctx.warnings}"
    )

    # Count CALLS edges from route handlers into service functions
    route_to_service_calls = [
        e for e in graph.edges
        if e.kind == EdgeKind.CALLS
        and "routes." in e.source_fqn
        and "services." in e.target_fqn
    ]
    assert len(route_to_service_calls) > 0, (
        "no route->service CALLS edges found; fixture or extractor broken"
    )

    high_conf = [e for e in route_to_service_calls if e.confidence == Confidence.HIGH]
    ratio = len(high_conf) / len(route_to_service_calls)

    failures = [
        (e.source_fqn, e.target_fqn, e.confidence)
        for e in route_to_service_calls
        if e.confidence != Confidence.HIGH
    ][:5]
    assert ratio >= 0.80, (
        f"only {ratio:.0%} of route->service CALLS edges are HIGH confidence; "
        f"expected >=80%. Sample failures: {failures}"
    )


@pytest.mark.asyncio
async def test_fastapi_todo_scip_partial_index_does_not_fail_pipeline():
    """Even if scip-python crashes mid-run, pipeline completes with warnings."""
    from app.stages.dependencies import resolve_dependencies
    from app.stages.discovery import discover_project
    from app.stages.scip.indexer import run_scip_indexers
    from app.stages.treesitter.parser import parse_with_treesitter

    manifest = discover_project(FASTAPI_TODO)
    environment = await resolve_dependencies(manifest)
    graph = await parse_with_treesitter(manifest)
    ctx = AnalysisContext(
        project_id="fastapi-todo-partial",
        graph=graph,
        manifest=manifest,
        environment=environment,
    )

    # run_scip_indexers catches exceptions internally and adds them to context.warnings.
    result = await run_scip_indexers(ctx)
    # Even if Python failed, the pipeline should return a result object, not raise.
    assert result is not None
