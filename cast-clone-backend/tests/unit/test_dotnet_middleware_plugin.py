"""Tests for the ASP.NET Core middleware pipeline plugin."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.dotnet.middleware import ASPNetMiddlewarePlugin
from tests.unit.helpers import make_dotnet_context

# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


class TestDetection:
    def test_detects_via_middleware_calls_fallback(self):
        """Detects ASP.NET middleware via middleware_calls property."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.graph = SymbolGraph()
        ctx.manifest = ProjectManifest(root_path=Path("/code"))
        ctx.manifest.detected_frameworks = []
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"middleware_calls": ["UseRouting", "UseAuthorization"]},
        ))
        result = plugin.detect(ctx)
        assert result.is_active


def _add_program_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    middleware_calls: list[str],
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.CLASS,
        language="csharp",
        properties={
            "middleware_calls": middleware_calls,
        },
    )
    graph.add_node(node)
    return node


# ---------------------------------------------------------------------------
# Extraction tests
# ---------------------------------------------------------------------------

class TestMiddlewareExtraction:
    @pytest.mark.asyncio
    async def test_extracts_middleware_chain(self):
        """Given 4 middleware calls, should produce 3 MIDDLEWARE_CHAIN edges linking consecutive items."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(
            ctx.graph, "MyApp.Program", "Program",
            middleware_calls=["UseRouting", "UseCors", "UseAuthentication", "UseAuthorization"],
        )

        result = await plugin.extract(ctx)

        chain_edges = [e for e in result.edges if e.kind == EdgeKind.MIDDLEWARE_CHAIN]
        assert len(chain_edges) == 3

        # Verify ordering: each edge connects consecutive middleware
        assert chain_edges[0].properties.get("order") == 0
        assert chain_edges[1].properties.get("order") == 1
        assert chain_edges[2].properties.get("order") == 2

        # Verify source/target names in edge properties or FQNs
        assert "UseRouting" in chain_edges[0].source_fqn
        assert "UseCors" in chain_edges[0].target_fqn
        assert "UseCors" in chain_edges[1].source_fqn
        assert "UseAuthentication" in chain_edges[1].target_fqn
        assert "UseAuthentication" in chain_edges[2].source_fqn
        assert "UseAuthorization" in chain_edges[2].target_fqn

    @pytest.mark.asyncio
    async def test_warns_on_wrong_auth_order(self):
        """UseAuthorization before UseAuthentication should produce a warning."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(
            ctx.graph, "MyApp.Program", "Program",
            middleware_calls=["UseRouting", "UseAuthorization", "UseAuthentication"],
        )

        result = await plugin.extract(ctx)

        assert len(result.warnings) >= 1
        warning_text = " ".join(result.warnings)
        assert "UseAuthorization" in warning_text
        assert "UseAuthentication" in warning_text

    @pytest.mark.asyncio
    async def test_warns_cors_after_auth(self):
        """UseCors after UseAuthentication should produce a warning."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(
            ctx.graph, "MyApp.Program", "Program",
            middleware_calls=["UseRouting", "UseAuthentication", "UseCors", "UseAuthorization"],
        )

        result = await plugin.extract(ctx)

        assert len(result.warnings) >= 1
        warning_text = " ".join(result.warnings)
        assert "UseCors" in warning_text
