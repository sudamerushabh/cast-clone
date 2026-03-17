"""Tests for the ASP.NET Core middleware pipeline plugin."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.dotnet.middleware import ASPNetMiddlewarePlugin
from tests.unit.helpers import make_dotnet_context, add_class, add_method

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


# ---------------------------------------------------------------------------
# Custom middleware class resolution
# ---------------------------------------------------------------------------

class TestCustomMiddlewareResolution:
    @pytest.mark.asyncio
    async def test_use_middleware_resolves_to_class(self):
        """UseMiddleware<RequestLoggingMiddleware> creates HANDLES edge to the middleware class."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(ctx.graph, "MyApp.Program", "Program",
                           middleware_calls=["UseRouting", "UseMiddleware<RequestLoggingMiddleware>", "UseAuthorization"])

        # The custom middleware class with InvokeAsync method
        add_class(ctx.graph, "MyApp.RequestLoggingMiddleware", "RequestLoggingMiddleware")
        add_method(ctx.graph, "MyApp.RequestLoggingMiddleware", "InvokeAsync", return_type="Task")

        result = await plugin.extract(ctx)

        handles_edges = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        assert len(handles_edges) >= 1
        assert any(e.source_fqn == "MyApp.RequestLoggingMiddleware" for e in handles_edges)

    @pytest.mark.asyncio
    async def test_custom_middleware_classified_as_cross_cutting(self):
        """Custom middleware classes resolved via UseMiddleware<T> get Cross-Cutting layer."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(ctx.graph, "MyApp.Program", "Program",
                           middleware_calls=["UseMiddleware<TenantMiddleware>"])
        add_class(ctx.graph, "MyApp.TenantMiddleware", "TenantMiddleware")
        add_method(ctx.graph, "MyApp.TenantMiddleware", "Invoke", return_type="Task")

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.TenantMiddleware") == "Cross-Cutting"


# ---------------------------------------------------------------------------
# Technology nodes
# ---------------------------------------------------------------------------

class TestTechnologyNodes:
    @pytest.mark.asyncio
    async def test_known_middleware_creates_technology_node(self):
        """UseAuthentication creates a technology COMPONENT node."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(ctx.graph, "MyApp.Program", "Program",
                           middleware_calls=["UseAuthentication", "UseAuthorization", "UseCors"])

        result = await plugin.extract(ctx)

        tech_nodes = [n for n in result.nodes if n.properties.get("technology")]
        assert len(tech_nodes) == 3
        tech_names = {n.properties["name"] for n in tech_nodes}
        assert "Authentication" in tech_names
        assert "Authorization" in tech_names
        assert "CORS" in tech_names


# ---------------------------------------------------------------------------
# Terminal middleware
# ---------------------------------------------------------------------------

class TestTerminalMiddleware:
    @pytest.mark.asyncio
    async def test_map_controllers_is_terminal(self):
        """MapControllers() is stored as a terminal middleware component."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(ctx.graph, "MyApp.Program", "Program",
                           middleware_calls=["UseRouting", "MapControllers"])

        result = await plugin.extract(ctx)

        map_ctrl = [n for n in result.nodes if n.name == "MapControllers"]
        assert len(map_ctrl) == 1
        assert map_ctrl[0].properties.get("terminal") is True
