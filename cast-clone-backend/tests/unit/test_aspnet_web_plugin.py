"""Tests for ASP.NET Core Web plugin — HTTP endpoint extraction."""

from __future__ import annotations

import pytest

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.manifest import DetectedFramework, ProjectManifest


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_context() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test-dotnet")
    ctx.graph = SymbolGraph()
    ctx.manifest = ProjectManifest(root_path="/code")
    ctx.manifest.detected_frameworks = [
        DetectedFramework(
            name="aspnet",
            language="csharp",
            confidence=Confidence.HIGH,
            evidence=["csproj"],
        ),
    ]
    return ctx


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    *,
    base_class: str = "",
    implements: list[str] | None = None,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    is_interface: bool = False,
    type_args: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.INTERFACE if is_interface else NodeKind.CLASS,
        language="csharp",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "base_class": base_class,
            "implements": implements or [],
            "type_args": type_args or [],
        },
    )
    graph.add_node(node)
    return node


def _add_method(
    graph: SymbolGraph,
    class_fqn: str,
    method_name: str,
    *,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    parameters: list[dict[str, str]] | None = None,
    return_type: str = "void",
    is_constructor: bool = False,
) -> GraphNode:
    fqn = f"{class_fqn}.{method_name}"
    node = GraphNode(
        fqn=fqn,
        name=method_name,
        kind=NodeKind.FUNCTION,
        language="csharp",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "parameters": parameters or [],
            "return_type": return_type,
            "is_constructor": is_constructor,
        },
    )
    graph.add_node(node)
    graph.add_edge(
        GraphEdge(
            source_fqn=class_fqn,
            target_fqn=fqn,
            kind=EdgeKind.CONTAINS,
            confidence=Confidence.HIGH,
            evidence="treesitter",
        )
    )
    return node


# ---------------------------------------------------------------------------
# Tests: Controller Detection & Endpoint Extraction
# ---------------------------------------------------------------------------


class TestControllerDetection:
    """Test HTTP endpoint extraction from ASP.NET controllers."""

    @pytest.mark.asyncio
    async def test_controller_with_route_and_httpget(self) -> None:
        """[ApiController] + [Route("api/[controller]")] + [HttpGet("{id}")] -> GET /api/users/:id."""
        from app.stages.plugins.aspnet.web import ASPNetWebPlugin

        ctx = _make_context()
        graph = ctx.graph

        _add_class(
            graph,
            "MyApp.Controllers.UsersController",
            "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            graph,
            "MyApp.Controllers.UsersController",
            "GetById",
            annotations=["HttpGet"],
            annotation_args={"": "{id}"},
            return_type="User",
        )

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)

        assert result.node_count == 1
        ep = result.nodes[0]
        assert ep.kind == NodeKind.API_ENDPOINT
        assert ep.properties["method"] == "GET"
        assert ep.properties["path"] == "/api/users/:id"

    @pytest.mark.asyncio
    async def test_httppost_endpoint(self) -> None:
        """[HttpPost] with no path argument -> POST /api/users."""
        from app.stages.plugins.aspnet.web import ASPNetWebPlugin

        ctx = _make_context()
        graph = ctx.graph

        _add_class(
            graph,
            "MyApp.Controllers.UsersController",
            "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            graph,
            "MyApp.Controllers.UsersController",
            "Create",
            annotations=["HttpPost"],
            return_type="ActionResult",
        )

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)

        assert result.node_count == 1
        ep = result.nodes[0]
        assert ep.properties["method"] == "POST"
        assert ep.properties["path"] == "/api/users"

    @pytest.mark.asyncio
    async def test_controller_token_replacement(self) -> None:
        """[Route("api/v1/[controller]")] replaces [controller] with class name minus 'Controller'."""
        from app.stages.plugins.aspnet.web import ASPNetWebPlugin

        ctx = _make_context()
        graph = ctx.graph

        _add_class(
            graph,
            "MyApp.Controllers.ProductsController",
            "ProductsController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/v1/[controller]"},
        )
        _add_method(
            graph,
            "MyApp.Controllers.ProductsController",
            "GetAll",
            annotations=["HttpGet"],
            return_type="List<Product>",
        )

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)

        assert result.node_count == 1
        ep = result.nodes[0]
        assert ep.properties["path"] == "/api/v1/products"

    @pytest.mark.asyncio
    async def test_multiple_http_methods_on_controller(self) -> None:
        """A controller with GET, POST, PUT, DELETE methods produces 4 endpoints."""
        from app.stages.plugins.aspnet.web import ASPNetWebPlugin

        ctx = _make_context()
        graph = ctx.graph

        _add_class(
            graph,
            "MyApp.Controllers.OrdersController",
            "OrdersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            graph,
            "MyApp.Controllers.OrdersController",
            "GetAll",
            annotations=["HttpGet"],
        )
        _add_method(
            graph,
            "MyApp.Controllers.OrdersController",
            "Create",
            annotations=["HttpPost"],
        )
        _add_method(
            graph,
            "MyApp.Controllers.OrdersController",
            "Update",
            annotations=["HttpPut"],
            annotation_args={"": "{id}"},
        )
        _add_method(
            graph,
            "MyApp.Controllers.OrdersController",
            "Delete",
            annotations=["HttpDelete"],
            annotation_args={"": "{id}"},
        )

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)

        assert result.node_count == 4
        methods = {n.properties["method"] for n in result.nodes}
        assert methods == {"GET", "POST", "PUT", "DELETE"}


# ---------------------------------------------------------------------------
# Tests: Edges & Entry Points
# ---------------------------------------------------------------------------


class TestEdgesAndEntryPoints:
    """Test that HANDLES/EXPOSES edges and entry points are created."""

    @pytest.mark.asyncio
    async def test_handles_and_exposes_edges(self) -> None:
        """Each endpoint gets a HANDLES edge (method->endpoint) and EXPOSES edge (class->endpoint)."""
        from app.stages.plugins.aspnet.web import ASPNetWebPlugin

        ctx = _make_context()
        graph = ctx.graph

        class_fqn = "MyApp.Controllers.UsersController"
        _add_class(
            graph,
            class_fqn,
            "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            graph,
            class_fqn,
            "GetById",
            annotations=["HttpGet"],
            annotation_args={"": "{id}"},
        )

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)

        handles_edges = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        exposes_edges = [e for e in result.edges if e.kind == EdgeKind.EXPOSES]

        assert len(handles_edges) == 1
        assert handles_edges[0].source_fqn == f"{class_fqn}.GetById"
        assert len(exposes_edges) == 1
        assert exposes_edges[0].source_fqn == class_fqn

    @pytest.mark.asyncio
    async def test_entry_points_created(self) -> None:
        """Each endpoint handler method is registered as an http_endpoint entry point."""
        from app.stages.plugins.aspnet.web import ASPNetWebPlugin

        ctx = _make_context()
        graph = ctx.graph

        class_fqn = "MyApp.Controllers.UsersController"
        _add_class(
            graph,
            class_fqn,
            "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            graph,
            class_fqn,
            "GetAll",
            annotations=["HttpGet"],
        )
        _add_method(
            graph,
            class_fqn,
            "Create",
            annotations=["HttpPost"],
        )

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)

        assert len(result.entry_points) == 2
        kinds = {ep.kind for ep in result.entry_points}
        assert kinds == {"http_endpoint"}
        fqns = {ep.fqn for ep in result.entry_points}
        assert f"{class_fqn}.GetAll" in fqns
        assert f"{class_fqn}.Create" in fqns


# ---------------------------------------------------------------------------
# Tests: Layer Classification
# ---------------------------------------------------------------------------


class TestLayerClassification:
    """Test that controllers are classified into the Presentation layer."""

    @pytest.mark.asyncio
    async def test_controllers_classified_as_presentation(self) -> None:
        """Controller classes should be assigned to the Presentation layer."""
        from app.stages.plugins.aspnet.web import ASPNetWebPlugin

        ctx = _make_context()
        graph = ctx.graph

        class_fqn = "MyApp.Controllers.UsersController"
        _add_class(
            graph,
            class_fqn,
            "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            graph,
            class_fqn,
            "GetAll",
            annotations=["HttpGet"],
        )

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)

        assert class_fqn in result.layer_assignments
        assert result.layer_assignments[class_fqn] == "Presentation"


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    @pytest.mark.asyncio
    async def test_route_constraint_normalization(self) -> None:
        """Route constraints like {id:int} and {id?} are normalized to :param."""
        from app.stages.plugins.aspnet.web import ASPNetWebPlugin

        ctx = _make_context()
        graph = ctx.graph

        class_fqn = "MyApp.Controllers.ItemsController"
        _add_class(
            graph,
            class_fqn,
            "ItemsController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            graph,
            class_fqn,
            "GetById",
            annotations=["HttpGet"],
            annotation_args={"": "{id:int}"},
        )
        _add_method(
            graph,
            class_fqn,
            "GetOptional",
            annotations=["HttpGet"],
            annotation_args={"": "optional/{key?}"},
        )

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)

        assert result.node_count == 2
        paths = {n.properties["path"] for n in result.nodes}
        assert "/api/items/:id" in paths
        assert "/api/items/optional/:key" in paths

    @pytest.mark.asyncio
    async def test_action_token_replacement(self) -> None:
        """[action] token in route is replaced with lowercased method name."""
        from app.stages.plugins.aspnet.web import ASPNetWebPlugin

        ctx = _make_context()
        graph = ctx.graph

        class_fqn = "MyApp.Controllers.ReportsController"
        _add_class(
            graph,
            class_fqn,
            "ReportsController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]/[action]"},
        )
        _add_method(
            graph,
            class_fqn,
            "Generate",
            annotations=["HttpPost"],
        )

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)

        assert result.node_count == 1
        assert result.nodes[0].properties["path"] == "/api/reports/generate"
