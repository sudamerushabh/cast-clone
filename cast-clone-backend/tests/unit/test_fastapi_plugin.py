# tests/unit/test_fastapi_plugin.py
"""Tests for the FastAPI plugin — route endpoints, Depends() DI, Pydantic model linking."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult, PluginResult
from app.stages.plugins.fastapi_plugin.routes import FastAPIPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_fastapi() -> AnalysisContext:
    """Create an AnalysisContext with fastapi detected."""
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="fastapi",
                language="python",
                confidence=Confidence.HIGH,
                evidence=["pyproject.toml contains fastapi"],
            ),
        ],
    )
    return ctx


def _add_module(graph: SymbolGraph, fqn: str, name: str) -> GraphNode:
    """Add a module node."""
    node = GraphNode(fqn=fqn, name=name, kind=NodeKind.MODULE, language="python")
    graph.add_node(node)
    return node


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    annotations: list[str] | None = None,
    bases: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.CLASS,
        language="python",
        properties={
            "annotations": annotations or [],
        },
    )
    graph.add_node(node)
    # Add INHERITS edges for base classes
    for base in (bases or []):
        graph.add_edge(GraphEdge(
            source_fqn=fqn, target_fqn=base, kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW, evidence="tree-sitter",
        ))
    return node


def _add_function(
    graph: SymbolGraph,
    parent_fqn: str,
    func_name: str,
    annotations: list[str] | None = None,
    params: list[dict] | None = None,
    return_type: str | None = None,
    is_method: bool = False,
) -> GraphNode:
    fqn = f"{parent_fqn}.{func_name}"
    node = GraphNode(
        fqn=fqn,
        name=func_name,
        kind=NodeKind.FUNCTION,
        language="python",
        properties={
            "annotations": annotations or [],
            "params": params or [],
            "return_type": return_type,
            "is_method": is_method,
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=parent_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestFastAPIDetection:
    def test_detect_high_when_fastapi_in_frameworks(self):
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_fastapi(self):
        plugin = FastAPIPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp"),
            detected_frameworks=[],
        )
        result = plugin.detect(ctx)
        assert result.is_active is False

    def test_detect_medium_when_decorators_found(self):
        """If no fastapi in frameworks but route decorators exist in graph."""
        plugin = FastAPIPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp"),
            detected_frameworks=[],
        )
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "get_users",
            annotations=['app.get("/users")'],
        )
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM


# ---------------------------------------------------------------------------
# Route endpoint extraction tests
# ---------------------------------------------------------------------------

class TestFastAPIRouteExtraction:
    @pytest.mark.asyncio
    async def test_get_endpoint_simple(self):
        """@app.get("/users") -> APIEndpoint node + HANDLES edge."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "get_users",
            annotations=['app.get("/users")'],
            return_type="list[User]",
        )

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["method"] == "GET"
        assert endpoint_nodes[0].properties["path"] == "/users"

        handles_edges = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        assert len(handles_edges) == 1
        assert handles_edges[0].source_fqn == "myapp.main.get_users"

    @pytest.mark.asyncio
    async def test_post_endpoint(self):
        """@app.post("/users") -> POST endpoint."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "create_user",
            annotations=['app.post("/users")'],
        )

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["method"] == "POST"
        assert endpoint_nodes[0].properties["path"] == "/users"

    @pytest.mark.asyncio
    async def test_all_http_methods(self):
        """All HTTP method decorators produce correct method values."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        methods = ["get", "post", "put", "delete", "patch"]
        for m in methods:
            _add_function(
                ctx.graph, "myapp.main", f"handle_{m}",
                annotations=[f'app.{m}("/resource")'],
            )

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 5
        extracted_methods = {n.properties["method"] for n in endpoint_nodes}
        assert extracted_methods == {"GET", "POST", "PUT", "DELETE", "PATCH"}

    @pytest.mark.asyncio
    async def test_path_with_parameters(self):
        """@app.get("/users/{user_id}") -> path preserved with parameter."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "get_user",
            annotations=['app.get("/users/{user_id}")'],
            params=[{"name": "user_id", "type": "int"}],
        )

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["path"] == "/users/{user_id}"

    @pytest.mark.asyncio
    async def test_router_prefix_composition(self):
        """APIRouter prefix is combined with method-level path."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.routes", "routes")

        # Simulate router = APIRouter(prefix="/api/v1") as a module-level field
        router_node = GraphNode(
            fqn="myapp.routes.router",
            name="router",
            kind=NodeKind.FIELD,
            language="python",
            properties={
                "type": "APIRouter",
                "annotations": [],
                "value": 'APIRouter(prefix="/api/v1")',
            },
        )
        ctx.graph.add_node(router_node)
        ctx.graph.add_edge(GraphEdge(
            source_fqn="myapp.routes", target_fqn="myapp.routes.router",
            kind=EdgeKind.CONTAINS,
        ))

        _add_function(
            ctx.graph, "myapp.routes", "list_users",
            annotations=['router.get("/users")'],
        )

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["path"] == "/api/v1/users"

    @pytest.mark.asyncio
    async def test_endpoint_creates_entry_point(self):
        """Each endpoint should be registered as an entry point."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "get_users",
            annotations=['app.get("/users")'],
        )

        result = await plugin.extract(ctx)
        assert len(result.entry_points) == 1
        assert result.entry_points[0].kind == "http_endpoint"
        assert result.entry_points[0].metadata["method"] == "GET"
        assert result.entry_points[0].metadata["path"] == "/users"


# ---------------------------------------------------------------------------
# Depends() DI tests
# ---------------------------------------------------------------------------

class TestFastAPIDependsInjection:
    @pytest.mark.asyncio
    async def test_depends_creates_injects_edge(self):
        """Parameter with Depends(get_db) -> INJECTS edge."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")

        # The dependency provider function
        _add_function(ctx.graph, "myapp.main", "get_db", return_type="AsyncSession")

        # The consumer with Depends()
        _add_function(
            ctx.graph, "myapp.main", "list_users",
            annotations=['app.get("/users")'],
            params=[
                {"name": "db", "type": "AsyncSession", "default": "Depends(get_db)"},
            ],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].source_fqn == "myapp.main.get_db"
        assert inject_edges[0].target_fqn == "myapp.main.list_users"
        assert inject_edges[0].properties.get("framework") == "fastapi"

    @pytest.mark.asyncio
    async def test_depends_with_dotted_path(self):
        """Depends(deps.get_db) — dotted import reference."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_module(ctx.graph, "myapp.deps", "deps")
        _add_function(ctx.graph, "myapp.deps", "get_db", return_type="AsyncSession")

        _add_function(
            ctx.graph, "myapp.main", "list_users",
            annotations=['app.get("/users")'],
            params=[
                {"name": "db", "type": "AsyncSession", "default": "Depends(deps.get_db)"},
            ],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1

    @pytest.mark.asyncio
    async def test_multiple_depends_in_one_function(self):
        """Multiple Depends() params -> multiple INJECTS edges."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(ctx.graph, "myapp.main", "get_db")
        _add_function(ctx.graph, "myapp.main", "get_current_user")

        _add_function(
            ctx.graph, "myapp.main", "create_item",
            annotations=['app.post("/items")'],
            params=[
                {"name": "db", "type": "Session", "default": "Depends(get_db)"},
                {"name": "user", "type": "User", "default": "Depends(get_current_user)"},
            ],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 2
        sources = {e.source_fqn for e in inject_edges}
        assert "myapp.main.get_db" in sources
        assert "myapp.main.get_current_user" in sources

    @pytest.mark.asyncio
    async def test_no_depends_no_inject_edges(self):
        """Function without Depends() -> no INJECTS edges."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "health",
            annotations=['app.get("/health")'],
            params=[],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 0


# ---------------------------------------------------------------------------
# Layer classification tests
# ---------------------------------------------------------------------------

class TestFastAPILayerClassification:
    @pytest.mark.asyncio
    async def test_route_handler_is_presentation(self):
        """Functions with route decorators -> Presentation layer."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "get_users",
            annotations=['app.get("/users")'],
        )

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("myapp.main.get_users") == "Presentation"


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestFastAPIPluginMetadata:
    def test_plugin_name(self):
        assert FastAPIPlugin().name == "fastapi"

    def test_supported_languages(self):
        assert FastAPIPlugin().supported_languages == {"python"}

    def test_depends_on_empty(self):
        assert FastAPIPlugin().depends_on == []
