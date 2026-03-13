# tests/unit/test_sqlalchemy_plugin.py
"""Tests for the SQLAlchemy plugin — declarative model mapping, FK resolution, relationship edges."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult, PluginResult
from app.stages.plugins.sqlalchemy_plugin.models import SQLAlchemyPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_sqlalchemy() -> AnalysisContext:
    """Create an AnalysisContext with sqlalchemy detected."""
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="sqlalchemy",
                language="python",
                confidence=Confidence.HIGH,
                evidence=["pyproject.toml contains sqlalchemy"],
            ),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    bases: list[str] | None = None,
    annotations: list[str] | None = None,
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
    for base in (bases or []):
        graph.add_edge(GraphEdge(
            source_fqn=fqn, target_fqn=base, kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW, evidence="tree-sitter",
        ))
    return node


def _add_field(
    graph: SymbolGraph,
    class_fqn: str,
    field_name: str,
    field_type: str | None = None,
    value: str | None = None,
    annotations: list[str] | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{field_name}"
    node = GraphNode(
        fqn=fqn,
        name=field_name,
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "type": field_type,
            "value": value or "",
            "annotations": annotations or [],
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

class TestSQLAlchemyDetection:
    def test_detect_high_when_sqlalchemy_in_frameworks(self):
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_sqlalchemy(self):
        plugin = SQLAlchemyPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp"),
            detected_frameworks=[],
        )
        result = plugin.detect(ctx)
        assert result.is_active is False

    def test_detect_medium_when_tablename_found(self):
        """If no sqlalchemy in frameworks but __tablename__ fields exist."""
        plugin = SQLAlchemyPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp"),
            detected_frameworks=[],
        )
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM


# ---------------------------------------------------------------------------
# Entity-to-table mapping tests
# ---------------------------------------------------------------------------

class TestSQLAlchemyEntityMapping:
    @pytest.mark.asyncio
    async def test_model_creates_table_node(self):
        """Class with __tablename__ -> Table node + MAPS_TO edge."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')
        _add_field(ctx.graph, "myapp.models.User", "name", value='Column(String(50))')
        _add_field(ctx.graph, "myapp.models.User", "email", value='Column(String, unique=True)')

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "users"
        assert table_nodes[0].fqn == "table:users"

        maps_to = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
        assert len(maps_to) == 1
        assert maps_to[0].source_fqn == "myapp.models.User"
        assert maps_to[0].target_fqn == "table:users"
        assert maps_to[0].properties.get("orm") == "sqlalchemy"

    @pytest.mark.asyncio
    async def test_columns_create_column_nodes(self):
        """Column() fields -> Column nodes + HAS_COLUMN edges."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')
        _add_field(ctx.graph, "myapp.models.User", "name", value='Column(String(50))')

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        column_names = {n.name for n in column_nodes}
        assert "id" in column_names
        assert "name" in column_names

        has_col_edges = [e for e in result.edges if e.kind == EdgeKind.HAS_COLUMN]
        assert len(has_col_edges) >= 2
        assert all(e.source_fqn == "table:users" for e in has_col_edges)

    @pytest.mark.asyncio
    async def test_primary_key_detected(self):
        """Column(primary_key=True) -> Column node with is_primary_key property."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        id_col = [n for n in column_nodes if n.name == "id"][0]
        assert id_col.properties.get("is_primary_key") is True

    @pytest.mark.asyncio
    async def test_mapped_column_style(self):
        """SQLAlchemy 2.0 mapped_column() style also detected."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='mapped_column(primary_key=True)')
        _add_field(ctx.graph, "myapp.models.User", "name", value='mapped_column(String(50))')

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        assert len(column_nodes) >= 2

    @pytest.mark.asyncio
    async def test_class_without_tablename_is_skipped(self):
        """Class inheriting Base but without __tablename__ (abstract) -> no Table."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.BaseModel", "BaseModel", bases=["myapp.db.Base"])

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 0


# ---------------------------------------------------------------------------
# Foreign key relationship tests
# ---------------------------------------------------------------------------

class TestSQLAlchemyRelationships:
    @pytest.mark.asyncio
    async def test_foreign_key_creates_references_edge(self):
        """Column(ForeignKey("users.id")) -> REFERENCES edge."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()

        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')

        _add_class(ctx.graph, "myapp.models.Post", "Post", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.Post", "__tablename__", value='"posts"')
        _add_field(ctx.graph, "myapp.models.Post", "id", value='Column(Integer, primary_key=True)')
        _add_field(
            ctx.graph, "myapp.models.Post", "author_id",
            value='Column(Integer, ForeignKey("users.id"))',
        )

        result = await plugin.extract(ctx)
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1
        assert "author_id" in ref_edges[0].source_fqn
        assert "id" in ref_edges[0].target_fqn

    @pytest.mark.asyncio
    async def test_relationship_field_is_ignored_for_columns(self):
        """relationship("User") field should NOT create a Column node."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()

        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')

        _add_class(ctx.graph, "myapp.models.Post", "Post", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.Post", "__tablename__", value='"posts"')
        _add_field(ctx.graph, "myapp.models.Post", "id", value='Column(Integer, primary_key=True)')
        _add_field(ctx.graph, "myapp.models.Post", "author_id", value='Column(Integer, ForeignKey("users.id"))')
        _add_field(ctx.graph, "myapp.models.Post", "author", value='relationship("User", back_populates="posts")')

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        column_names = {n.name for n in column_nodes}
        assert "author" not in column_names

    @pytest.mark.asyncio
    async def test_multiple_models_with_fks(self):
        """Multiple models with cross-references produce correct REFERENCES edges."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()

        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')

        _add_class(ctx.graph, "myapp.models.Post", "Post", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.Post", "__tablename__", value='"posts"')
        _add_field(ctx.graph, "myapp.models.Post", "id", value='Column(Integer, primary_key=True)')
        _add_field(ctx.graph, "myapp.models.Post", "author_id", value='Column(Integer, ForeignKey("users.id"))')

        _add_class(ctx.graph, "myapp.models.Comment", "Comment", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.Comment", "__tablename__", value='"comments"')
        _add_field(ctx.graph, "myapp.models.Comment", "id", value='Column(Integer, primary_key=True)')
        _add_field(ctx.graph, "myapp.models.Comment", "post_id", value='Column(Integer, ForeignKey("posts.id"))')
        _add_field(ctx.graph, "myapp.models.Comment", "user_id", value='Column(Integer, ForeignKey("users.id"))')

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 3
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 3


# ---------------------------------------------------------------------------
# Layer classification tests
# ---------------------------------------------------------------------------

class TestSQLAlchemyLayerClassification:
    @pytest.mark.asyncio
    async def test_model_is_data_access(self):
        """SQLAlchemy model classes -> Data Access layer."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("myapp.models.User") == "Data Access"


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestSQLAlchemyPluginMetadata:
    def test_plugin_name(self):
        assert SQLAlchemyPlugin().name == "sqlalchemy"

    def test_supported_languages(self):
        assert SQLAlchemyPlugin().supported_languages == {"python"}

    def test_depends_on_empty(self):
        assert SQLAlchemyPlugin().depends_on == []
