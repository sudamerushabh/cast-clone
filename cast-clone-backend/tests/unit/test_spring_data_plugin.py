"""Tests for the Spring Data plugin — repository detection, derived queries, @Query parsing."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult
from app.stages.plugins.spring.data import SpringDataPlugin


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
    is_interface: bool = False,
    implements: list[str] | None = None,
    type_args: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.INTERFACE if is_interface else NodeKind.CLASS,
        language="java",
        properties={
            "annotations": annotations or [],
            "implements": implements or [],
            "is_interface": is_interface,
            "type_args": type_args or [],
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
            "is_constructor": False,
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


def _add_table(graph: SymbolGraph, table_name: str) -> GraphNode:
    """Add a table node (as Hibernate plugin would have produced)."""
    fqn = f"table:{table_name}"
    node = GraphNode(fqn=fqn, name=table_name, kind=NodeKind.TABLE)
    graph.add_node(node)
    return node


def _add_entity_with_table(
    graph: SymbolGraph, entity_fqn: str, entity_name: str, table_name: str
) -> None:
    """Add entity class + table + MAPS_TO edge (simulating Hibernate plugin output)."""
    _add_class(graph, entity_fqn, entity_name, annotations=["Entity"])
    _add_table(graph, table_name)
    graph.add_edge(GraphEdge(
        source_fqn=entity_fqn,
        target_fqn=f"table:{table_name}",
        kind=EdgeKind.MAPS_TO,
        confidence=Confidence.HIGH,
        evidence="hibernate",
        properties={"orm": "hibernate"},
    ))


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestSpringDataDetection:
    def test_detect_high_when_spring_present(self):
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_spring(self):
        plugin = SpringDataPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# Repository detection tests
# ---------------------------------------------------------------------------

class TestSpringDataRepositoryDetection:
    @pytest.mark.asyncio
    async def test_jpa_repository_detected(self):
        """Interface extending JpaRepository<User, Long> -> MANAGES edge to entity."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )

        result = await plugin.extract(ctx)
        manages_edges = [e for e in result.edges if e.kind == EdgeKind.MANAGES]
        assert len(manages_edges) == 1
        assert manages_edges[0].source_fqn == "com.example.UserRepository"
        assert manages_edges[0].target_fqn == "com.example.User"

    @pytest.mark.asyncio
    async def test_crud_repository_detected(self):
        """Interface extending CrudRepository -> MANAGES edge."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.Order", "Order", "orders")
        _add_class(
            ctx.graph, "com.example.OrderRepository", "OrderRepository",
            is_interface=True,
            implements=["CrudRepository"],
            type_args=["Order", "Long"],
        )

        result = await plugin.extract(ctx)
        manages_edges = [e for e in result.edges if e.kind == EdgeKind.MANAGES]
        assert len(manages_edges) == 1


# ---------------------------------------------------------------------------
# Derived query method tests
# ---------------------------------------------------------------------------

class TestSpringDataDerivedQueries:
    @pytest.mark.asyncio
    async def test_find_by_single_field(self):
        """findByEmail -> READS edge to users table with column 'email'."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(ctx.graph, "com.example.UserRepository", "findByEmail",
                    return_type="User")

        result = await plugin.extract(ctx)
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        assert len(reads_edges) >= 1
        reads_to_users = [e for e in reads_edges if "users" in e.target_fqn]
        assert len(reads_to_users) == 1
        assert "email" in reads_to_users[0].properties.get("columns", [])

    @pytest.mark.asyncio
    async def test_find_by_multiple_fields(self):
        """findByEmailAndStatus -> READS with columns ['email', 'status']."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(ctx.graph, "com.example.UserRepository", "findByEmailAndStatus",
                    return_type="List<User>")

        result = await plugin.extract(ctx)
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        reads_to_users = [e for e in reads_edges if "users" in e.target_fqn]
        assert len(reads_to_users) == 1
        cols = set(reads_to_users[0].properties.get("columns", []))
        assert cols == {"email", "status"}

    @pytest.mark.asyncio
    async def test_count_by_method(self):
        """countByStatus -> READS edge."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(ctx.graph, "com.example.UserRepository", "countByStatus",
                    return_type="Long")

        result = await plugin.extract(ctx)
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        assert len(reads_edges) >= 1

    @pytest.mark.asyncio
    async def test_delete_by_method(self):
        """deleteByEmail -> WRITES edge."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(ctx.graph, "com.example.UserRepository", "deleteByEmail",
                    return_type="void")

        result = await plugin.extract(ctx)
        writes_edges = [e for e in result.edges if e.kind == EdgeKind.WRITES]
        assert len(writes_edges) >= 1


# ---------------------------------------------------------------------------
# @Query annotation tests
# ---------------------------------------------------------------------------

class TestSpringDataQueryAnnotation:
    @pytest.mark.asyncio
    async def test_query_annotation_select(self):
        """@Query("SELECT u FROM User u WHERE u.email = ?1") -> READS users table."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(
            ctx.graph, "com.example.UserRepository", "findActiveUsers",
            annotations=["Query"],
            annotation_args={"Query": "SELECT u FROM User u WHERE u.active = true"},
            return_type="List<User>",
        )

        result = await plugin.extract(ctx)
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        assert len(reads_edges) >= 1

    @pytest.mark.asyncio
    async def test_query_annotation_native_sql(self):
        """@Query with native SQL referencing actual table name."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(
            ctx.graph, "com.example.UserRepository", "findByNativeQuery",
            annotations=["Query"],
            annotation_args={"Query": "SELECT * FROM users WHERE email = ?1"},
            return_type="List<User>",
        )

        result = await plugin.extract(ctx)
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        assert len(reads_edges) >= 1


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestSpringDataMetadata:
    def test_name(self):
        assert SpringDataPlugin().name == "spring-data"

    def test_depends_on(self):
        assert SpringDataPlugin().depends_on == ["spring-di", "hibernate"]

    def test_supported_languages(self):
        assert SpringDataPlugin().supported_languages == {"java"}
