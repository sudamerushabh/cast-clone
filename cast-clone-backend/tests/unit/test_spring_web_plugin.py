"""Tests for the Spring Web plugin — endpoint extraction, path combining, entry points."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult
from app.stages.plugins.spring.web import SpringWebPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_spring() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="spring-boot",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains spring-boot-starter-web"],
            ),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.CLASS,
        language="java",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
        },
    )
    graph.add_node(node)
    return node


def _add_method(
    graph: SymbolGraph,
    class_fqn: str,
    method_name: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    return_type: str | None = None,
    params: list[dict] | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{method_name}"
    node = GraphNode(
        fqn=fqn,
        name=method_name,
        kind=NodeKind.FUNCTION,
        language="java",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "return_type": return_type,
            "params": params or [],
            "is_constructor": False,
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestSpringWebDetection:
    def test_detect_high_when_spring_present(self):
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_spring(self):
        plugin = SpringWebPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# Endpoint extraction tests
# ---------------------------------------------------------------------------

class TestSpringWebEndpointExtraction:
    @pytest.mark.asyncio
    async def test_get_mapping_simple(self):
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController",
                   annotations=["RestController"])
        _add_method(ctx.graph, "com.example.UserController", "getUsers",
                    annotations=["GetMapping"],
                    annotation_args={"GetMapping": "/users"},
                    return_type="List<User>")

        result = await plugin.extract(ctx)
        # Should create an APIEndpoint node
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["method"] == "GET"
        assert endpoint_nodes[0].properties["path"] == "/users"

        # Should create HANDLES edge (method -> endpoint)
        handles_edges = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        assert len(handles_edges) == 1
        assert handles_edges[0].source_fqn == "com.example.UserController.getUsers"

        # Should create EXPOSES edge (class -> endpoint)
        exposes_edges = [e for e in result.edges if e.kind == EdgeKind.EXPOSES]
        assert len(exposes_edges) == 1
        assert exposes_edges[0].source_fqn == "com.example.UserController"

    @pytest.mark.asyncio
    async def test_class_level_request_mapping_prefix(self):
        """Class-level @RequestMapping prefix is combined with method-level path."""
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController",
                   annotations=["RestController", "RequestMapping"],
                   annotation_args={"RequestMapping": "/api/v1"})
        _add_method(ctx.graph, "com.example.UserController", "getUser",
                    annotations=["GetMapping"],
                    annotation_args={"GetMapping": "/users/{id}"},
                    return_type="User")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["path"] == "/api/v1/users/{id}"

    @pytest.mark.asyncio
    async def test_multiple_http_methods(self):
        """Different HTTP method annotations produce correct method values."""
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController",
                   annotations=["RestController"])
        _add_method(ctx.graph, "com.example.UserController", "createUser",
                    annotations=["PostMapping"],
                    annotation_args={"PostMapping": "/users"},
                    return_type="User")
        _add_method(ctx.graph, "com.example.UserController", "updateUser",
                    annotations=["PutMapping"],
                    annotation_args={"PutMapping": "/users/{id}"})
        _add_method(ctx.graph, "com.example.UserController", "deleteUser",
                    annotations=["DeleteMapping"],
                    annotation_args={"DeleteMapping": "/users/{id}"})
        _add_method(ctx.graph, "com.example.UserController", "patchUser",
                    annotations=["PatchMapping"],
                    annotation_args={"PatchMapping": "/users/{id}"})

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        methods = {n.properties["method"] for n in endpoint_nodes}
        assert methods == {"POST", "PUT", "DELETE", "PATCH"}

    @pytest.mark.asyncio
    async def test_request_mapping_with_method_attribute(self):
        """@RequestMapping(method=GET, path="/users") at method level."""
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController",
                   annotations=["Controller"])
        _add_method(ctx.graph, "com.example.UserController", "listUsers",
                    annotations=["RequestMapping"],
                    annotation_args={"RequestMapping": "/users", "method": "GET"})

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["method"] == "GET"
        assert endpoint_nodes[0].properties["path"] == "/users"

    @pytest.mark.asyncio
    async def test_no_endpoints_for_non_controller(self):
        """Classes without @Controller/@RestController produce no endpoints."""
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserService", "UserService",
                   annotations=["Service"])
        _add_method(ctx.graph, "com.example.UserService", "getUsers",
                    annotations=["GetMapping"],
                    annotation_args={"GetMapping": "/users"})

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 0


# ---------------------------------------------------------------------------
# Entry points tests
# ---------------------------------------------------------------------------

class TestSpringWebEntryPoints:
    @pytest.mark.asyncio
    async def test_endpoints_are_entry_points(self):
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController",
                   annotations=["RestController"])
        _add_method(ctx.graph, "com.example.UserController", "getUsers",
                    annotations=["GetMapping"],
                    annotation_args={"GetMapping": "/users"})
        _add_method(ctx.graph, "com.example.UserController", "createUser",
                    annotations=["PostMapping"],
                    annotation_args={"PostMapping": "/users"})

        result = await plugin.extract(ctx)
        assert len(result.entry_points) == 2
        entry_fqns = {ep.fqn for ep in result.entry_points}
        assert "com.example.UserController.getUsers" in entry_fqns
        assert "com.example.UserController.createUser" in entry_fqns
        assert all(ep.kind == "http_endpoint" for ep in result.entry_points)


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestSpringWebMetadata:
    def test_name(self):
        assert SpringWebPlugin().name == "spring-web"

    def test_depends_on(self):
        assert SpringWebPlugin().depends_on == ["spring-di"]

    def test_supported_languages(self):
        assert SpringWebPlugin().supported_languages == {"java"}
