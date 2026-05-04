"""M4 integration tests — Flask plugin end-to-end chains against flask-inventory.

Drives Stages 1-5 against the M4 fixtures and asserts on the in-memory
SymbolGraph. Mirrors the harness style of `test_python_m3_pipeline.py`:
- discover_project (sync)
- resolve_dependencies (async)
- parse_with_treesitter(manifest) -> SymbolGraph
- run_scip_indexers(ctx)
- run_framework_plugins(ctx)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# Importing the plugins package registers all built-in plugins (FlaskPlugin etc.)
import app.stages.plugins  # noqa: F401
from app.models.context import AnalysisContext
from app.models.enums import EdgeKind, NodeKind

FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures"


pytestmark = [
    pytest.mark.integration,
    pytest.mark.scip_python,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH"),
    pytest.mark.skipif(
        shutil.which("scip-python") is None, reason="scip-python not on PATH"
    ),
]


async def _run_pipeline_stages_1_to_5(
    fixture_root: Path, project_id: str
) -> AnalysisContext:
    """Run discovery -> dependencies -> treesitter -> SCIP -> plugins.

    Mirrors the M3 harness shape exactly.
    """
    from app.stages.dependencies import resolve_dependencies
    from app.stages.discovery import discover_project
    from app.stages.plugins.registry import run_framework_plugins
    from app.stages.scip.indexer import run_scip_indexers
    from app.stages.treesitter.parser import parse_with_treesitter

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
    return ctx


class TestFlaskInventoryBlueprints:
    """Acceptance: blueprint routes produce endpoints with the correct prefix."""

    @pytest.fixture(scope="class")
    async def ctx(self) -> AnalysisContext:
        return await _run_pipeline_stages_1_to_5(
            FIXTURES_ROOT / "flask-inventory", "flask-inventory-m4"
        )

    async def test_items_list_endpoint_exists(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/items"
            and n.properties.get("method") == "GET"
        ]
        assert len(eps) >= 1, "expected GET /items endpoint from items_bp"

    async def test_items_adjust_endpoint_includes_path_converter(
        self, ctx: AnalysisContext
    ) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/items/<int:item_id>/adjust"
            and n.properties.get("method") == "POST"
        ]
        assert len(eps) == 1

    async def test_warehouses_list_endpoint_exists(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/warehouses"
            and n.properties.get("method") == "GET"
        ]
        assert len(eps) >= 1

    async def test_warehouses_items_nested_endpoint_exists(
        self, ctx: AnalysisContext
    ) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/warehouses/<int:wh_id>/items"
            and n.properties.get("method") == "GET"
        ]
        assert len(eps) == 1

    async def test_blueprint_endpoint_has_handles_edge(
        self, ctx: AnalysisContext
    ) -> None:
        handles = [e for e in ctx.graph.edges if e.kind == EdgeKind.HANDLES]
        assert any(
            e.target_fqn == "GET:/items" and e.source_fqn.endswith("list_items")
            for e in handles
        ), "expected HANDLES edge from list_items -> GET:/items"


class TestFlaskInventoryRestful:
    """Acceptance: Flask-RESTful resources produce endpoints with Api prefix applied."""

    @pytest.fixture(scope="class")
    async def ctx(self) -> AnalysisContext:
        return await _run_pipeline_stages_1_to_5(
            FIXTURES_ROOT / "flask-inventory", "flask-inventory-m4-restful"
        )

    async def test_api_items_list_get(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/api/items"
            and n.properties.get("method") == "GET"
        ]
        assert len(eps) == 1

    async def test_api_items_list_post(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/api/items"
            and n.properties.get("method") == "POST"
        ]
        assert len(eps) == 1

    async def test_api_items_detail_get(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/api/items/<int:item_id>"
            and n.properties.get("method") == "GET"
        ]
        assert len(eps) == 1

    async def test_api_items_detail_delete(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/api/items/<int:item_id>"
            and n.properties.get("method") == "DELETE"
        ]
        assert len(eps) == 1

    async def test_resource_method_has_handles_edge(self, ctx: AnalysisContext) -> None:
        handles = [e for e in ctx.graph.edges if e.kind == EdgeKind.HANDLES]
        assert any(
            e.target_fqn == "DELETE:/api/items/<int:item_id>"
            and e.source_fqn.endswith("ItemResource.delete")
            for e in handles
        )
