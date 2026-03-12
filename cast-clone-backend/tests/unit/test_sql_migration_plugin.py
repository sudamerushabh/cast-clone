# tests/unit/test_sql_migration_plugin.py
import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.stages.plugins.sql.migration import (
    SQLMigrationPlugin,
    MigrationFile,
    detect_migration_framework,
    parse_flyway_filename,
    parse_ddl_statements,
    SchemaState,
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


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "sql-migrations"


# -- Unit Tests: Flyway filename parsing ------------------------------


class TestFlywayFilenameParsing:
    def test_standard_flyway_name(self):
        mf = parse_flyway_filename("V1__create_users.sql")
        assert mf is not None
        assert mf.version == "1"
        assert mf.description == "create_users"

    def test_dotted_version(self):
        mf = parse_flyway_filename("V1.2.3__add_index.sql")
        assert mf is not None
        assert mf.version == "1.2.3"

    def test_non_flyway_file_returns_none(self):
        assert parse_flyway_filename("README.md") is None
        assert parse_flyway_filename("init.sql") is None

    def test_undo_migration_skipped(self):
        mf = parse_flyway_filename("U1__undo_create.sql")
        assert mf is None  # Only V (versioned) migrations are processed


# -- Unit Tests: Migration framework detection ------------------------


class TestMigrationFrameworkDetection:
    def test_detect_flyway(self):
        result = detect_migration_framework(FIXTURES_DIR / "flyway")
        assert result == "flyway"

    def test_detect_alembic(self):
        result = detect_migration_framework(FIXTURES_DIR / "alembic")
        assert result == "alembic"

    def test_detect_none_in_empty_dir(self, tmp_path):
        result = detect_migration_framework(tmp_path)
        assert result is None


# -- Unit Tests: DDL parsing ------------------------------------------


class TestParseDDLStatements:
    def test_create_table_produces_table_and_columns(self):
        sql = """
        CREATE TABLE users (
            id BIGINT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255)
        );
        """
        schema = SchemaState()
        parse_ddl_statements(sql, schema)

        assert "users" in schema.tables
        table = schema.tables["users"]
        assert len(table.columns) == 3
        assert "id" in table.columns
        assert "name" in table.columns
        assert "email" in table.columns
        assert table.columns["id"].is_primary_key is True

    def test_create_table_with_foreign_key(self):
        sql = """
        CREATE TABLE orders (
            id BIGINT PRIMARY KEY,
            user_id BIGINT NOT NULL,
            CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """
        schema = SchemaState()
        # Pretend users table already exists
        schema.tables["users"] = SchemaState.TableDef(
            name="users",
            columns={
                "id": SchemaState.ColumnDef(name="id", type="BIGINT", is_primary_key=True),
            },
        )
        parse_ddl_statements(sql, schema)

        assert "orders" in schema.tables
        assert len(schema.foreign_keys) == 1
        fk = schema.foreign_keys[0]
        assert fk.source_table == "orders"
        assert fk.source_column == "user_id"
        assert fk.target_table == "users"
        assert fk.target_column == "id"

    def test_alter_table_add_column(self):
        sql = "ALTER TABLE users ADD COLUMN phone VARCHAR(20);"
        schema = SchemaState()
        schema.tables["users"] = SchemaState.TableDef(
            name="users",
            columns={
                "id": SchemaState.ColumnDef(name="id", type="BIGINT"),
            },
        )
        parse_ddl_statements(sql, schema)
        assert "phone" in schema.tables["users"].columns

    def test_create_index_recorded(self):
        sql = "CREATE INDEX idx_users_email ON users(email);"
        schema = SchemaState()
        schema.tables["users"] = SchemaState.TableDef(
            name="users",
            columns={
                "email": SchemaState.ColumnDef(name="email", type="VARCHAR(255)"),
            },
        )
        parse_ddl_statements(sql, schema)
        assert len(schema.indexes) >= 1
        assert schema.indexes[0].table_name == "users"
        assert "email" in schema.indexes[0].column_names


# -- Unit Tests: Full Plugin Extract ----------------------------------


class TestSQLMigrationPluginExtract:
    @pytest.fixture
    def plugin(self):
        return SQLMigrationPlugin()

    def test_plugin_metadata(self, plugin):
        assert plugin.name == "sql-migration"
        assert "sql" in plugin.supported_languages
        assert "java" in plugin.supported_languages
        assert plugin.depends_on == []

    def test_detect_with_flyway_dir(self, plugin):
        confidence = plugin.detect_from_paths([FIXTURES_DIR / "flyway"])
        assert confidence == Confidence.HIGH

    def test_detect_no_migrations(self, plugin, tmp_path):
        confidence = plugin.detect_from_paths([tmp_path])
        assert confidence == Confidence.LOW

    def test_extract_flyway_migrations(self, plugin):
        """Full integration: parse 3 Flyway migration files and produce graph nodes."""
        result = plugin.extract_from_migration_dir(FIXTURES_DIR / "flyway", "flyway")

        table_nodes = _find_nodes(result.nodes, NodeKind.TABLE)
        table_names = {n.name for n in table_nodes}
        assert "users" in table_names
        assert "orders" in table_names

        column_nodes = _find_nodes(result.nodes, NodeKind.COLUMN)
        column_names = {n.name for n in column_nodes}
        assert "id" in column_names
        assert "name" in column_names
        assert "email" in column_names
        assert "user_id" in column_names
        assert "phone" in column_names  # from V3 ALTER TABLE

        # HAS_COLUMN edges
        has_col_edges = _find_edges(result.edges, EdgeKind.HAS_COLUMN)
        assert len(has_col_edges) >= 8  # users(4+phone) + orders(5)

        # REFERENCES edge for FK
        ref_edges = _find_edges(result.edges, EdgeKind.REFERENCES)
        assert len(ref_edges) >= 1
        fk_edge = ref_edges[0]
        assert "orders" in fk_edge.source_fqn
        assert "users" in fk_edge.target_fqn

    def test_migrations_applied_in_order(self, plugin):
        """V3 adds phone column to users — must be applied after V1."""
        result = plugin.extract_from_migration_dir(FIXTURES_DIR / "flyway", "flyway")

        # Find the users table node
        users_table = _find_node(result.nodes, "users")
        assert users_table is not None

        # phone column should exist (added by V3)
        column_nodes = _find_nodes(result.nodes, NodeKind.COLUMN)
        phone_cols = [c for c in column_nodes if c.name == "phone"]
        assert len(phone_cols) == 1
        assert "users" in phone_cols[0].fqn
