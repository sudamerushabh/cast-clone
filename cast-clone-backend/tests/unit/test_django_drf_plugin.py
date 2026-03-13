"""Tests for the Django REST Framework plugin — ViewSet->Serializer->Model chain."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult, PluginResult
from app.stages.plugins.django.drf import DjangoDRFPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_drf() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(name="django", language="python",
                              confidence=Confidence.HIGH, evidence=["Django detected"]),
            DetectedFramework(name="djangorestframework", language="python",
                              confidence=Confidence.HIGH, evidence=["DRF detected"]),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph, fqn: str, name: str,
    bases: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn, name=name, kind=NodeKind.CLASS, language="python",
        properties={"annotations": []},
    )
    graph.add_node(node)
    for base in (bases or []):
        graph.add_edge(GraphEdge(
            source_fqn=fqn, target_fqn=base, kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW, evidence="tree-sitter",
        ))
    return node


def _add_field(
    graph: SymbolGraph, class_fqn: str, name: str, value: str = "",
) -> GraphNode:
    fqn = f"{class_fqn}.{name}"
    node = GraphNode(
        fqn=fqn, name=name, kind=NodeKind.FIELD, language="python",
        properties={"value": value},
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestDjangoDRFDetection:
    def test_detect_high_when_drf_in_frameworks(self):
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_drf(self):
        plugin = DjangoDRFPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False

    def test_detect_medium_when_viewset_found(self):
        """If no DRF in frameworks but ModelViewSet subclass exists."""
        plugin = DjangoDRFPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM


# ---------------------------------------------------------------------------
# ViewSet chain resolution tests
# ---------------------------------------------------------------------------

class TestDRFViewSetChain:
    @pytest.mark.asyncio
    async def test_viewset_manages_model(self):
        """ViewSet with queryset = User.objects.all() -> MANAGES edge to User."""
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()

        # Model
        _add_class(ctx.graph, "myapp.models.User", "User",
                   bases=["django.db.models.Model"])

        # ViewSet
        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        _add_field(ctx.graph, "myapp.views.UserViewSet", "queryset",
                   value="User.objects.all()")
        _add_field(ctx.graph, "myapp.views.UserViewSet", "serializer_class",
                   value="UserSerializer")

        result = await plugin.extract(ctx)
        manages_edges = [e for e in result.edges if e.kind == EdgeKind.MANAGES]
        assert len(manages_edges) == 1
        assert manages_edges[0].source_fqn == "myapp.views.UserViewSet"

    @pytest.mark.asyncio
    async def test_viewset_reads_writes_table(self):
        """ViewSet -> READS/WRITES edges to associated table (if ORM plugin ran first)."""
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()

        # Simulate ORM plugin output: model + table
        _add_class(ctx.graph, "myapp.models.User", "User",
                   bases=["django.db.models.Model"])
        table_node = GraphNode(
            fqn="table:myapp_user", name="myapp_user", kind=NodeKind.TABLE,
        )
        ctx.graph.add_node(table_node)
        ctx.graph.add_edge(GraphEdge(
            source_fqn="myapp.models.User", target_fqn="table:myapp_user",
            kind=EdgeKind.MAPS_TO, confidence=Confidence.HIGH, evidence="django-orm",
        ))

        # ViewSet
        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        _add_field(ctx.graph, "myapp.views.UserViewSet", "queryset",
                   value="User.objects.all()")

        result = await plugin.extract(ctx)
        rw_edges = [e for e in result.edges
                    if e.kind in (EdgeKind.READS, EdgeKind.WRITES)]
        assert len(rw_edges) >= 1

    @pytest.mark.asyncio
    async def test_viewset_creates_crud_endpoints(self):
        """ModelViewSet generates standard CRUD endpoints."""
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()

        _add_class(ctx.graph, "myapp.models.User", "User",
                   bases=["django.db.models.Model"])
        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        _add_field(ctx.graph, "myapp.views.UserViewSet", "queryset",
                   value="User.objects.all()")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        # ModelViewSet generates list, create, retrieve, update, destroy
        assert len(endpoint_nodes) >= 2  # At minimum list + detail

    @pytest.mark.asyncio
    async def test_viewset_layer_assignment(self):
        """ViewSet -> Presentation layer."""
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()

        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        _add_field(ctx.graph, "myapp.views.UserViewSet", "queryset",
                   value="User.objects.all()")

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("myapp.views.UserViewSet") == "Presentation"


# ---------------------------------------------------------------------------
# Serializer chain tests
# ---------------------------------------------------------------------------

class TestDRFSerializerChain:
    @pytest.mark.asyncio
    async def test_serializer_with_meta_model(self):
        """ModelSerializer with Meta.model = User -> link to model."""
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()

        _add_class(ctx.graph, "myapp.models.User", "User",
                   bases=["django.db.models.Model"])
        _add_class(ctx.graph, "myapp.serializers.UserSerializer", "UserSerializer",
                   bases=["rest_framework.serializers.ModelSerializer"])
        _add_field(ctx.graph, "myapp.serializers.UserSerializer", "_meta_model",
                   value="User")

        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        _add_field(ctx.graph, "myapp.views.UserViewSet", "serializer_class",
                   value="UserSerializer")
        _add_field(ctx.graph, "myapp.views.UserViewSet", "queryset",
                   value="User.objects.all()")

        result = await plugin.extract(ctx)
        manages_edges = [e for e in result.edges if e.kind == EdgeKind.MANAGES]
        assert len(manages_edges) >= 1


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestDjangoDRFMetadata:
    def test_plugin_name(self):
        assert DjangoDRFPlugin().name == "django-drf"

    def test_depends_on(self):
        assert DjangoDRFPlugin().depends_on == ["django-orm", "django-urls"]

    def test_supported_languages(self):
        assert DjangoDRFPlugin().supported_languages == {"python"}
