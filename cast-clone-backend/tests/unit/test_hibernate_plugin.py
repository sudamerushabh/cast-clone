"""Tests for the Hibernate/JPA plugin — entity mapping, table/column nodes, FK relationships."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult
from app.stages.plugins.hibernate.jpa import HibernateJPAPlugin


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
                evidence=["pom.xml contains spring-boot-starter-data-jpa"],
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


def _add_field(
    graph: SymbolGraph,
    class_fqn: str,
    field_name: str,
    field_type: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    type_args: list[str] | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{field_name}"
    node = GraphNode(
        fqn=fqn,
        name=field_name,
        kind=NodeKind.FIELD,
        language="java",
        properties={
            "type": field_type,
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "type_args": type_args or [],
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

class TestHibernateDetection:
    def test_detect_high_when_spring_data_jpa_present(self):
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_medium_when_entity_annotations_found(self):
        plugin = HibernateJPAPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM

    def test_detect_none_without_hibernate(self):
        plugin = HibernateJPAPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# Entity-to-table mapping tests
# ---------------------------------------------------------------------------

class TestHibernateEntityMapping:
    @pytest.mark.asyncio
    async def test_entity_creates_table_node(self):
        """@Entity class -> Table node with MAPS_TO edge."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "users"  # camelCase -> snake_case

        maps_to = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
        assert len(maps_to) == 1
        assert maps_to[0].source_fqn == "com.example.User"
        assert maps_to[0].properties.get("orm") == "hibernate"

    @pytest.mark.asyncio
    async def test_entity_with_table_annotation(self):
        """@Table(name="app_users") overrides derived table name."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.User", "User",
                   annotations=["Entity", "Table"],
                   annotation_args={"Table": "app_users"})

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "app_users"

    @pytest.mark.asyncio
    async def test_fields_create_column_nodes(self):
        """Entity fields -> Column nodes with HAS_COLUMN edges."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.User", "email", "String")
        _add_field(ctx.graph, "com.example.User", "firstName", "String")

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        assert len(column_nodes) == 3
        col_names = {n.name for n in column_nodes}
        assert col_names == {"id", "email", "first_name"}  # camelCase -> snake_case

        has_column = [e for e in result.edges if e.kind == EdgeKind.HAS_COLUMN]
        assert len(has_column) == 3

    @pytest.mark.asyncio
    async def test_column_annotation_overrides_name(self):
        """@Column(name="email_address") overrides derived column name."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "email", "String",
                   annotations=["Column"],
                   annotation_args={"Column": "email_address"})

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        assert any(n.name == "email_address" for n in column_nodes)

    @pytest.mark.asyncio
    async def test_id_field_marked_as_primary_key(self):
        """@Id annotation sets is_primary_key on column."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "id", "Long", annotations=["Id"])

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        id_col = [n for n in column_nodes if n.name == "id"][0]
        assert id_col.properties.get("is_primary_key") is True


# ---------------------------------------------------------------------------
# Relationship mapping tests
# ---------------------------------------------------------------------------

class TestHibernateRelationships:
    @pytest.mark.asyncio
    async def test_many_to_one_creates_fk(self):
        """@ManyToOne + @JoinColumn -> REFERENCES edge between columns."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()

        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "id", "Long", annotations=["Id"])

        _add_class(ctx.graph, "com.example.Order", "Order", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.Order", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.Order", "user", "User",
                   annotations=["ManyToOne", "JoinColumn"],
                   annotation_args={"JoinColumn": "user_id"})

        result = await plugin.extract(ctx)
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1
        # The FK column (user_id in orders table) references (id in users table)
        assert "user_id" in ref_edges[0].source_fqn
        assert "id" in ref_edges[0].target_fqn

    @pytest.mark.asyncio
    async def test_one_to_many_with_mapped_by(self):
        """@OneToMany(mappedBy="user") — inverse side, no new FK, but relationship edge."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()

        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.User", "orders", "List",
                   annotations=["OneToMany"],
                   annotation_args={"OneToMany": "user"},  # mappedBy value
                   type_args=["Order"])

        _add_class(ctx.graph, "com.example.Order", "Order", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.Order", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.Order", "user", "User",
                   annotations=["ManyToOne", "JoinColumn"],
                   annotation_args={"JoinColumn": "user_id"})

        result = await plugin.extract(ctx)
        # The FK REFERENCES edge should exist from the ManyToOne side
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) >= 1

    @pytest.mark.asyncio
    async def test_many_to_many_creates_junction_table(self):
        """@ManyToMany + @JoinTable -> junction table node + FK edges."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()

        _add_class(ctx.graph, "com.example.Student", "Student", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.Student", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.Student", "courses", "Set",
                   annotations=["ManyToMany", "JoinTable"],
                   annotation_args={"JoinTable": "student_courses"},
                   type_args=["Course"])

        _add_class(ctx.graph, "com.example.Course", "Course", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.Course", "id", "Long", annotations=["Id"])

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        table_names = {n.name for n in table_nodes}
        # Should have students, courses, and the junction table student_courses
        assert "student_courses" in table_names
        assert "students" in table_names
        assert "courses" in table_names

    @pytest.mark.asyncio
    async def test_one_to_one(self):
        """@OneToOne + @JoinColumn -> unique FK."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()

        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "id", "Long", annotations=["Id"])

        _add_class(ctx.graph, "com.example.Profile", "Profile", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.Profile", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.Profile", "user", "User",
                   annotations=["OneToOne", "JoinColumn"],
                   annotation_args={"JoinColumn": "user_id"})

        result = await plugin.extract(ctx)
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestHibernateMetadata:
    def test_name(self):
        assert HibernateJPAPlugin().name == "hibernate"

    def test_depends_on(self):
        assert HibernateJPAPlugin().depends_on == ["spring-di"]

    def test_supported_languages(self):
        assert HibernateJPAPlugin().supported_languages == {"java"}
