# tests/unit/test_sql_parser_plugin.py
import pytest
from dataclasses import field as dataclass_field

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.stages.plugins.sql.parser import (
    SQLParserPlugin,
    SQLDependencies,
    extract_sql_dependencies,
)


# -- Helpers ----------------------------------------------------------


def _find_node(nodes: list[GraphNode], name: str) -> GraphNode | None:
    for n in nodes:
        if n.name == name:
            return n
    return None


def _find_nodes(nodes: list[GraphNode], kind: NodeKind) -> list[GraphNode]:
    return [n for n in nodes if n.kind == kind]


def _find_edge(
    edges: list[GraphEdge],
    source_fqn: str,
    target_fqn: str,
    kind: EdgeKind,
) -> GraphEdge | None:
    for e in edges:
        if e.source_fqn == source_fqn and e.target_fqn == target_fqn and e.kind == kind:
            return e
    return None


def _find_edges(edges: list[GraphEdge], kind: EdgeKind) -> list[GraphEdge]:
    return [e for e in edges if e.kind == kind]


# -- Unit Tests: extract_sql_dependencies() --------------------------


class TestExtractSqlDependencies:
    """Test the pure function that parses a SQL string and returns table dependencies."""

    def test_simple_select(self):
        result = extract_sql_dependencies("SELECT id, name FROM users WHERE active = 1")
        assert result is not None
        assert "users" in result.reads
        assert len(result.writes) == 0

    def test_select_with_join(self):
        sql = "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        result = extract_sql_dependencies(sql)
        assert result is not None
        assert "users" in result.reads
        assert "orders" in result.reads
        assert len(result.reads) == 2

    def test_select_with_subquery(self):
        sql = "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders WHERE total > 100)"
        result = extract_sql_dependencies(sql)
        assert result is not None
        assert "users" in result.reads
        assert "orders" in result.reads

    def test_insert(self):
        result = extract_sql_dependencies("INSERT INTO users (name, email) VALUES ('a', 'b')")
        assert result is not None
        assert "users" in result.writes
        assert len(result.reads) == 0

    def test_insert_select(self):
        sql = "INSERT INTO archive_users SELECT * FROM users WHERE active = 0"
        result = extract_sql_dependencies(sql)
        assert result is not None
        assert "archive_users" in result.writes
        assert "users" in result.reads

    def test_update(self):
        result = extract_sql_dependencies("UPDATE users SET name = 'test' WHERE id = 1")
        assert result is not None
        assert "users" in result.writes

    def test_delete(self):
        result = extract_sql_dependencies("DELETE FROM users WHERE id = 1")
        assert result is not None
        assert "users" in result.writes

    def test_invalid_sql_returns_none(self):
        result = extract_sql_dependencies("this is not sql at all")
        assert result is None

    def test_empty_string_returns_none(self):
        result = extract_sql_dependencies("")
        assert result is None

    def test_dialect_postgres(self):
        sql = "SELECT * FROM users WHERE name ILIKE '%test%'"
        result = extract_sql_dependencies(sql, dialect="postgres")
        assert result is not None
        assert "users" in result.reads

    def test_multi_table_join(self):
        sql = """
            SELECT u.name, o.total, p.name
            FROM users u
            JOIN orders o ON u.id = o.user_id
            JOIN products p ON o.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
        """
        result = extract_sql_dependencies(sql)
        assert result is not None
        assert result.reads == {"users", "orders", "products", "categories"}

    def test_schema_qualified_table(self):
        sql = "SELECT * FROM public.users"
        result = extract_sql_dependencies(sql)
        assert result is not None
        # sqlglot resolves Table.name as "users" for schema-qualified refs
        assert "users" in result.reads


# -- Unit Tests: SQLParserPlugin.extract() ----------------------------


class TestSQLParserPluginExtract:
    """Test the full plugin extract cycle against an AnalysisContext with graph nodes."""

    @pytest.fixture
    def plugin(self):
        return SQLParserPlugin()

    @pytest.fixture
    def graph_with_tagged_sql(self):
        """Build a SymbolGraph where a Function node has tagged_strings containing SQL."""
        g = SymbolGraph()
        fn = GraphNode(
            fqn="com.example.UserDao.findAll",
            name="findAll",
            kind=NodeKind.FUNCTION,
            language="java",
            path="UserDao.java",
            line=10,
            properties={
                "tagged_strings": [
                    "SELECT id, name, email FROM users WHERE active = 1",
                ]
            },
        )
        g.add_node(fn)
        return g

    @pytest.fixture
    def graph_with_write_sql(self):
        g = SymbolGraph()
        fn = GraphNode(
            fqn="com.example.UserDao.insertUser",
            name="insertUser",
            kind=NodeKind.FUNCTION,
            language="java",
            path="UserDao.java",
            line=30,
            properties={
                "tagged_strings": [
                    "INSERT INTO users (name, email) VALUES (?, ?)",
                ]
            },
        )
        g.add_node(fn)
        return g

    @pytest.fixture
    def graph_with_multiple_sql(self):
        g = SymbolGraph()
        fn = GraphNode(
            fqn="com.example.ReportDao.generate",
            name="generate",
            kind=NodeKind.FUNCTION,
            language="java",
            path="ReportDao.java",
            line=10,
            properties={
                "tagged_strings": [
                    "SELECT u.name FROM users u JOIN orders o ON u.id = o.user_id",
                    "INSERT INTO reports (user_id, total) SELECT user_id, SUM(total) FROM orders GROUP BY user_id",
                ]
            },
        )
        g.add_node(fn)
        return g

    @pytest.fixture
    def graph_with_invalid_sql(self):
        g = SymbolGraph()
        fn = GraphNode(
            fqn="com.example.SomeService.doStuff",
            name="doStuff",
            kind=NodeKind.FUNCTION,
            language="java",
            path="SomeService.java",
            line=5,
            properties={
                "tagged_strings": [
                    "this is not valid SQL",
                    "SELECT id FROM users",
                ]
            },
        )
        g.add_node(fn)
        return g

    def test_detect_always_high(self, plugin):
        """SQL can appear in any codebase, so detect always returns HIGH."""
        assert plugin.detect_from_graph(SymbolGraph()) == Confidence.HIGH

    def test_extract_select_creates_reads_edge(self, plugin, graph_with_tagged_sql):
        result = plugin.extract_from_graph(graph_with_tagged_sql)

        # Should create a Table node for "users"
        table_nodes = _find_nodes(result.nodes, NodeKind.TABLE)
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "users"
        assert table_nodes[0].fqn == "table:users"

        # Should create a READS edge from function -> table
        reads_edges = _find_edges(result.edges, EdgeKind.READS)
        assert len(reads_edges) == 1
        edge = reads_edges[0]
        assert edge.source_fqn == "com.example.UserDao.findAll"
        assert edge.target_fqn == "table:users"
        assert edge.properties.get("query_type") == "SELECT"

    def test_extract_insert_creates_writes_edge(self, plugin, graph_with_write_sql):
        result = plugin.extract_from_graph(graph_with_write_sql)

        table_nodes = _find_nodes(result.nodes, NodeKind.TABLE)
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "users"

        writes_edges = _find_edges(result.edges, EdgeKind.WRITES)
        assert len(writes_edges) == 1
        assert writes_edges[0].source_fqn == "com.example.UserDao.insertUser"
        assert writes_edges[0].target_fqn == "table:users"
        assert writes_edges[0].properties.get("query_type") == "INSERT"

    def test_extract_multiple_sql_strings(self, plugin, graph_with_multiple_sql):
        result = plugin.extract_from_graph(graph_with_multiple_sql)

        table_nodes = _find_nodes(result.nodes, NodeKind.TABLE)
        table_names = {n.name for n in table_nodes}
        assert "users" in table_names
        assert "orders" in table_names
        assert "reports" in table_names

        reads_edges = _find_edges(result.edges, EdgeKind.READS)
        writes_edges = _find_edges(result.edges, EdgeKind.WRITES)
        assert len(reads_edges) >= 2  # users, orders read by first SQL; orders by second
        assert len(writes_edges) == 1  # reports written by INSERT

    def test_invalid_sql_skipped_gracefully(self, plugin, graph_with_invalid_sql):
        result = plugin.extract_from_graph(graph_with_invalid_sql)

        # "this is not valid SQL" should be skipped; "SELECT id FROM users" should work
        table_nodes = _find_nodes(result.nodes, NodeKind.TABLE)
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "users"

        # Should have a warning about the invalid SQL
        assert len(result.warnings) >= 1

    def test_no_tagged_strings_no_results(self, plugin):
        g = SymbolGraph()
        fn = GraphNode(
            fqn="com.example.Plain.method",
            name="method",
            kind=NodeKind.FUNCTION,
            language="java",
            properties={},
        )
        g.add_node(fn)
        result = plugin.extract_from_graph(g)
        assert len(result.nodes) == 0
        assert len(result.edges) == 0

    def test_duplicate_table_not_duplicated(self, plugin):
        """Two functions reading same table should produce only one Table node."""
        g = SymbolGraph()
        fn1 = GraphNode(
            fqn="a.findAll", name="findAll", kind=NodeKind.FUNCTION,
            properties={"tagged_strings": ["SELECT * FROM users"]},
        )
        fn2 = GraphNode(
            fqn="a.findOne", name="findOne", kind=NodeKind.FUNCTION,
            properties={"tagged_strings": ["SELECT * FROM users WHERE id = ?"]},
        )
        g.add_node(fn1)
        g.add_node(fn2)
        result = plugin.extract_from_graph(g)

        table_nodes = _find_nodes(result.nodes, NodeKind.TABLE)
        assert len(table_nodes) == 1
        reads_edges = _find_edges(result.edges, EdgeKind.READS)
        assert len(reads_edges) == 2

    def test_plugin_metadata(self, plugin):
        assert plugin.name == "sql-parser"
        assert plugin.supported_languages == {"java", "python", "typescript", "csharp"}
        assert plugin.depends_on == []
