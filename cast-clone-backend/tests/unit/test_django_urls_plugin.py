"""Tests for the Django URLs plugin -- path(), re_path(), include() resolution."""

from pathlib import Path

import pytest

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.manifest import DetectedFramework, ProjectManifest
from app.stages.plugins.django.urls import DjangoURLsPlugin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context_with_django() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="django",
                language="python",
                confidence=Confidence.HIGH,
                evidence=["requirements.txt contains Django"],
            ),
        ],
    )
    return ctx


def _add_module(graph: SymbolGraph, fqn: str, name: str) -> GraphNode:
    node = GraphNode(fqn=fqn, name=name, kind=NodeKind.MODULE, language="python")
    graph.add_node(node)
    return node


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    bases: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.CLASS,
        language="python",
        properties={"annotations": []},
    )
    graph.add_node(node)
    for base in bases or []:
        graph.add_edge(
            GraphEdge(
                source_fqn=fqn,
                target_fqn=base,
                kind=EdgeKind.INHERITS,
                confidence=Confidence.LOW,
                evidence="tree-sitter",
            )
        )
    return node


def _add_function(
    graph: SymbolGraph,
    parent_fqn: str,
    name: str,
    annotations: list[str] | None = None,
) -> GraphNode:
    fqn = f"{parent_fqn}.{name}"
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": annotations or []},
    )
    graph.add_node(node)
    graph.add_edge(
        GraphEdge(
            source_fqn=parent_fqn,
            target_fqn=fqn,
            kind=EdgeKind.CONTAINS,
        )
    )
    return node


def _add_field(
    graph: SymbolGraph,
    parent_fqn: str,
    name: str,
    value: str = "",
) -> GraphNode:
    fqn = f"{parent_fqn}.{name}"
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.FIELD,
        language="python",
        properties={"value": value},
    )
    graph.add_node(node)
    graph.add_edge(
        GraphEdge(
            source_fqn=parent_fqn,
            target_fqn=fqn,
            kind=EdgeKind.CONTAINS,
        )
    )
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


class TestDjangoURLsDetection:
    def test_detect_high_when_django_present(self):
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_django(self):
        plugin = DjangoURLsPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# URL extraction tests
# ---------------------------------------------------------------------------


class TestDjangoURLExtraction:
    @pytest.mark.asyncio
    async def test_simple_path_creates_endpoint(self):
        """path("users/", views.user_list) -> APIEndpoint node."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph,
            "myapp.urls",
            "urlpatterns",
            value='[path("users/", views.user_list, name="user-list")]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_list")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["path"] == "/users/"

    @pytest.mark.asyncio
    async def test_path_with_parameter(self):
        """path("users/<int:pk>/", ...) -> endpoint with parameter in path."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph,
            "myapp.urls",
            "urlpatterns",
            value='[path("users/<int:pk>/", views.user_detail)]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_detail")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert "<int:pk>" in endpoint_nodes[0].properties["path"]

    @pytest.mark.asyncio
    async def test_handles_edge_to_view(self):
        """View function referenced in path() -> HANDLES edge."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph,
            "myapp.urls",
            "urlpatterns",
            value='[path("users/", views.user_list)]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_list")

        result = await plugin.extract(ctx)
        handles_edges = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        assert len(handles_edges) == 1

    @pytest.mark.asyncio
    async def test_class_based_view(self):
        """path("users/", UserListView.as_view()) -> endpoint + HANDLES to class."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph,
            "myapp.urls",
            "urlpatterns",
            value='[path("users/", UserListView.as_view())]',
        )
        _add_class(ctx.graph, "myapp.views.UserListView", "UserListView")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1

    @pytest.mark.asyncio
    async def test_include_resolves_prefix(self):
        """path("api/", include("myapp.urls")) -> prefixed endpoints."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()

        # Root urls with include
        _add_module(ctx.graph, "myproject.urls", "urls")
        _add_field(
            ctx.graph,
            "myproject.urls",
            "urlpatterns",
            value='[path("api/", include("myapp.urls"))]',
        )

        # App urls
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph,
            "myapp.urls",
            "urlpatterns",
            value='[path("users/", views.user_list)]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_list")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) >= 1
        # The full path should combine the prefix
        paths = [n.properties["path"] for n in endpoint_nodes]
        assert any("/api/users/" in p for p in paths)

    @pytest.mark.asyncio
    async def test_entry_points_created(self):
        """Each URL endpoint should produce an entry point."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph,
            "myapp.urls",
            "urlpatterns",
            value='[path("users/", views.user_list)]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_list")

        result = await plugin.extract(ctx)
        assert len(result.entry_points) >= 1
        assert result.entry_points[0].kind == "http_endpoint"

    @pytest.mark.asyncio
    async def test_view_layer_assignment(self):
        """View functions/classes -> Presentation layer."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph,
            "myapp.urls",
            "urlpatterns",
            value='[path("users/", views.user_list)]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_list")

        result = await plugin.extract(ctx)
        # The view function should be classified as Presentation
        assert "Presentation" in result.layer_assignments.values()


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------


class TestDjangoURLsMetadata:
    def test_plugin_name(self):
        assert DjangoURLsPlugin().name == "django-urls"

    def test_depends_on(self):
        assert DjangoURLsPlugin().depends_on == ["django-settings"]

    def test_supported_languages(self):
        assert DjangoURLsPlugin().supported_languages == {"python"}
