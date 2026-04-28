"""M3 integration tests — Pydantic + Celery plugin end-to-end chains.

Drives Stages 1-5 against the M1 fixtures and asserts on the in-memory
SymbolGraph. Mirrors the harness style of `test_python_m1_scip.py`:
- discover_project (sync)
- resolve_dependencies (async)
- parse_with_treesitter(manifest) -> SymbolGraph
- run_scip_indexers(ctx)
- run_framework_plugins(ctx)

Gated by `scip_python` because SCIP upgrades cross-module call confidence
which the Celery producer linker depends on for HIGH-confidence edges.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# Importing the plugins package registers all built-in plugins (Pydantic,
# Celery, etc.) with the global_registry at import time.
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

    Skips Stage 6 (cross-tech linker), Stage 7 (enricher), Stage 8 (writer).
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


class TestFastAPITodoPydanticChain:
    """Acceptance: endpoint -> Pydantic model -> SQLAlchemy column via MAPS_TO."""

    @pytest.fixture(scope="class")
    async def ctx(self) -> AnalysisContext:
        fixture = FIXTURES_ROOT / "fastapi-todo"
        return await _run_pipeline_stages_1_to_5(fixture, "fastapi-todo-m3")

    async def test_api_endpoint_nodes_exist(self, ctx: AnalysisContext) -> None:
        endpoints = [
            n for n in ctx.graph.nodes.values() if n.kind == NodeKind.API_ENDPOINT
        ]
        assert len(endpoints) >= 1, f"expected >=1 APIEndpoint; got {len(endpoints)}"

    async def test_accepts_edge_points_to_pydantic_model(
        self, ctx: AnalysisContext
    ) -> None:
        accepts = [e for e in ctx.graph.edges if e.kind == EdgeKind.ACCEPTS]
        assert len(accepts) >= 1, (
            "expected >=1 ACCEPTS edge from endpoint to body model"
        )
        for edge in accepts:
            target = ctx.graph.get_node(edge.target_fqn)
            assert target is not None, f"ACCEPTS target missing: {edge.target_fqn}"
            assert target.kind == NodeKind.CLASS
            assert target.properties.get("is_pydantic_model") is True

    async def test_returns_edge_points_to_pydantic_model(
        self, ctx: AnalysisContext
    ) -> None:
        returns = [e for e in ctx.graph.edges if e.kind == EdgeKind.RETURNS]
        assert len(returns) >= 1
        for edge in returns:
            target = ctx.graph.get_node(edge.target_fqn)
            assert target is not None
            assert target.properties.get("is_pydantic_model") is True

    async def test_pydantic_field_maps_to_column(self, ctx: AnalysisContext) -> None:
        maps = [e for e in ctx.graph.edges if e.kind == EdgeKind.MAPS_TO]
        pydantic_maps = [
            e
            for e in maps
            if (src := ctx.graph.get_node(e.source_fqn)) is not None
            and src.kind == NodeKind.FIELD
            and (tgt := ctx.graph.get_node(e.target_fqn)) is not None
            and tgt.kind == NodeKind.COLUMN
        ]
        assert len(pydantic_maps) >= 1, (
            "expected >=1 Pydantic field -> SQLAlchemy column MAPS_TO edge"
        )


class TestDjangoBlogCeleryChain:
    """Acceptance: endpoint -> producer function -> Celery task -> queue topic."""

    @pytest.fixture(scope="class")
    async def ctx(self) -> AnalysisContext:
        fixture = FIXTURES_ROOT / "django-blog"
        return await _run_pipeline_stages_1_to_5(fixture, "django-blog-m3")

    async def test_task_nodes_tagged_with_celery_framework(
        self, ctx: AnalysisContext
    ) -> None:
        tasks = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.FUNCTION and n.properties.get("framework") == "celery"
        ]
        assert len(tasks) >= 2, (
            f"expected >=2 Celery tasks in django-blog; got {len(tasks)}"
        )

    async def test_message_topic_exists_for_notifications(
        self, ctx: AnalysisContext
    ) -> None:
        topics = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.MESSAGE_TOPIC and n.name == "notifications"
        ]
        assert len(topics) == 1, (
            f"expected exactly one 'notifications' MESSAGE_TOPIC; got {len(topics)}"
        )

    async def test_consumes_edge_from_task_to_topic(self, ctx: AnalysisContext) -> None:
        consumes = [e for e in ctx.graph.edges if e.kind == EdgeKind.CONSUMES]
        assert any(e.target_fqn == "queue::notifications" for e in consumes), (
            "expected CONSUMES edge pointing to queue::notifications"
        )

    async def test_produces_edge_from_view_caller_to_topic(
        self, ctx: AnalysisContext
    ) -> None:
        produces = [e for e in ctx.graph.edges if e.kind == EdgeKind.PRODUCES]
        assert any(
            e.target_fqn == "queue::notifications"
            and e.source_fqn.endswith("perform_create")
            for e in produces
        ), (
            "expected PRODUCES edge from PostViewSet.perform_create to "
            "queue::notifications"
        )
