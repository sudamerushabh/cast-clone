"""Tests for the Django ORM plugin — Model-to-table, ForeignKey, ManyToManyField."""

from pathlib import Path

import pytest

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.manifest import DetectedFramework, ProjectManifest
from app.stages.plugins.django.orm import DjangoORMPlugin

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
                evidence=["Django detected"],
            ),
        ],
    )
    return ctx


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


def _add_field(
    graph: SymbolGraph,
    class_fqn: str,
    name: str,
    value: str = "",
) -> GraphNode:
    fqn = f"{class_fqn}.{name}"
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
            source_fqn=class_fqn,
            target_fqn=fqn,
            kind=EdgeKind.CONTAINS,
        )
    )
    return node


def _add_django_model(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    fields: dict[str, str],
    db_table: str | None = None,
) -> GraphNode:
    """Convenience: add a Django model class with fields."""
    node = _add_class(graph, fqn, name, bases=["django.db.models.Model"])
    for field_name, field_value in fields.items():
        _add_field(graph, fqn, field_name, value=field_value)
    if db_table:
        # Simulate class Meta: db_table = "custom"
        _add_field(graph, fqn, "_meta_db_table", value=f'"{db_table}"')
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


class TestDjangoORMDetection:
    def test_detect_high_when_django_present(self):
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_medium_when_models_found(self):
        plugin = DjangoORMPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        _add_class(
            ctx.graph, "myapp.models.User", "User", bases=["django.db.models.Model"]
        )
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM

    def test_detect_none_without_django(self):
        plugin = DjangoORMPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# Model-to-table mapping tests
# ---------------------------------------------------------------------------


class TestDjangoORMEntityMapping:
    @pytest.mark.asyncio
    async def test_model_creates_table_node(self):
        """Django model -> Table node with conventional name (app_model)."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(
            ctx.graph,
            "myapp.models.User",
            "User",
            {
                "id": "models.AutoField(primary_key=True)",
                "name": "models.CharField(max_length=100)",
                "email": "models.EmailField(unique=True)",
            },
        )

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "myapp_user"

        maps_to = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
        assert len(maps_to) == 1
        assert maps_to[0].properties.get("orm") == "django"

    @pytest.mark.asyncio
    async def test_custom_db_table_override(self):
        """Model with Meta.db_table override uses custom table name."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(
            ctx.graph,
            "myapp.models.User",
            "User",
            {"id": "models.AutoField(primary_key=True)"},
            db_table="custom_users",
        )

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "custom_users"

    @pytest.mark.asyncio
    async def test_columns_from_model_fields(self):
        """Model fields -> Column nodes + HAS_COLUMN edges."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(
            ctx.graph,
            "myapp.models.User",
            "User",
            {
                "id": "models.AutoField(primary_key=True)",
                "name": "models.CharField(max_length=100)",
            },
        )

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        names = {n.name for n in column_nodes}
        assert "id" in names
        assert "name" in names

    @pytest.mark.asyncio
    async def test_primary_key_detected(self):
        """primary_key=True -> Column with is_primary_key property."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(
            ctx.graph,
            "myapp.models.User",
            "User",
            {
                "id": "models.AutoField(primary_key=True)",
            },
        )

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        pk_cols = [n for n in column_nodes if n.properties.get("is_primary_key")]
        assert len(pk_cols) == 1
        assert pk_cols[0].name == "id"


# ---------------------------------------------------------------------------
# Relationship tests
# ---------------------------------------------------------------------------


class TestDjangoORMRelationships:
    @pytest.mark.asyncio
    async def test_foreign_key_creates_references_edge(self):
        """ForeignKey(User) -> REFERENCES edge + implicit _id column."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(
            ctx.graph,
            "myapp.models.User",
            "User",
            {
                "id": "models.AutoField(primary_key=True)",
            },
        )
        _add_django_model(
            ctx.graph,
            "myapp.models.Post",
            "Post",
            {
                "id": "models.AutoField(primary_key=True)",
                "author": "models.ForeignKey(User, on_delete=models.CASCADE)",
            },
        )

        result = await plugin.extract(ctx)
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1
        # Django adds _id suffix: author -> author_id column
        assert "author_id" in ref_edges[0].source_fqn

    @pytest.mark.asyncio
    async def test_many_to_many_creates_junction_table(self):
        """ManyToManyField -> junction table with FK edges."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(
            ctx.graph,
            "myapp.models.Tag",
            "Tag",
            {
                "id": "models.AutoField(primary_key=True)",
                "name": "models.CharField(max_length=50)",
            },
        )
        _add_django_model(
            ctx.graph,
            "myapp.models.Post",
            "Post",
            {
                "id": "models.AutoField(primary_key=True)",
                "tags": "models.ManyToManyField(Tag)",
            },
        )

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        table_names = {n.name for n in table_nodes}
        # Should have the junction table
        assert any("post" in t and "tag" in t for t in table_names)

    @pytest.mark.asyncio
    async def test_one_to_one_creates_references_edge(self):
        """OneToOneField(User) -> REFERENCES edge (like FK but unique)."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(
            ctx.graph,
            "myapp.models.User",
            "User",
            {
                "id": "models.AutoField(primary_key=True)",
            },
        )
        _add_django_model(
            ctx.graph,
            "myapp.models.Profile",
            "Profile",
            {
                "id": "models.AutoField(primary_key=True)",
                "user": "models.OneToOneField(User, on_delete=models.CASCADE)",
            },
        )

        result = await plugin.extract(ctx)
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1


# ---------------------------------------------------------------------------
# Layer classification tests
# ---------------------------------------------------------------------------


class TestDjangoORMLayerClassification:
    @pytest.mark.asyncio
    async def test_model_is_data_access(self):
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(
            ctx.graph,
            "myapp.models.User",
            "User",
            {
                "id": "models.AutoField(primary_key=True)",
            },
        )

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("myapp.models.User") == "Data Access"


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------


class TestDjangoORMMetadata:
    def test_plugin_name(self):
        assert DjangoORMPlugin().name == "django-orm"

    def test_depends_on(self):
        assert DjangoORMPlugin().depends_on == ["django-settings"]

    def test_supported_languages(self):
        assert DjangoORMPlugin().supported_languages == {"python"}
