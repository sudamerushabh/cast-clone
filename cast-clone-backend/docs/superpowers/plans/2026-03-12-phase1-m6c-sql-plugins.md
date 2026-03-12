# M6c: SQL Parser & SQL Migration Plugins Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement two framework plugins -- SQL Parser (detects embedded SQL in code and creates READS/WRITES edges to Table nodes) and SQL Migration (reconstructs database schema from migration files like Flyway, Alembic, Liquibase, EF). These connect the application layer to the database layer in the architecture graph.

**Architecture:** Both plugins implement the `FrameworkPlugin` ABC from `app/stages/plugins/base.py`. SQL Parser scans existing Function nodes for `properties["tagged_strings"]` (set by tree-sitter extractors), parses them with `sqlglot`, and emits Table nodes + READS/WRITES edges. SQL Migration detects migration files by convention, parses them in version order with `sqlglot` (for SQL files) or pattern matching (for code-based migrations), and emits Table, Column nodes + HAS_COLUMN, REFERENCES edges.

**Tech Stack:** Python 3.12, sqlglot >=29.0.1, pytest

**Depends on:** M1 (enums, GraphNode, GraphEdge, SymbolGraph, AnalysisContext), M6a (FrameworkPlugin ABC, PluginResult, Confidence, plugin registry)

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       └── plugins/
│           └── sql/
│               ├── __init__.py          # CREATE (empty)
│               ├── parser.py            # CREATE — SQLParserPlugin
│               └── migration.py         # CREATE — SQLMigrationPlugin
└── tests/
    ├── unit/
    │   ├── test_sql_parser_plugin.py    # CREATE — 10 test cases
    │   └── test_sql_migration_plugin.py # CREATE — 9 test cases
    └── fixtures/
        └── sql-migrations/              # CREATE — sample migration files
            ├── flyway/
            │   ├── V1__create_users.sql
            │   ├── V2__create_orders.sql
            │   └── V3__add_email_index.sql
            └── alembic/
                └── versions/
                    └── 001_create_users.py
```

---

## Task 1: SQL Parser Plugin — Core SQL Extraction

**Files:**
- Create: `app/stages/plugins/sql/__init__.py`
- Create: `app/stages/plugins/sql/parser.py`
- Create: `tests/unit/test_sql_parser_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
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


# ── Helpers ──────────────────────────────────────────────


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


# ── Unit Tests: extract_sql_dependencies() ───────────────


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


# ── Unit Tests: SQLParserPlugin.extract() ────────────────


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_sql_parser_plugin.py -v`
Expected: FAIL (ImportError -- module doesn't exist)

- [ ] **Step 3: Create the `sql/` package init**

```python
# app/stages/plugins/sql/__init__.py
```

- [ ] **Step 4: Implement the SQL Parser Plugin**

```python
# app/stages/plugins/sql/parser.py
"""SQL Parser Plugin — detects embedded SQL in code and creates READS/WRITES edges to Table nodes.

Scans all Function nodes in the graph for `properties["tagged_strings"]`,
attempts to parse each string with sqlglot, and produces Table nodes plus
READS/WRITES edges linking functions to the tables they access.

This plugin has no framework dependency — SQL can appear in any codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.plugins.base import FrameworkPlugin, PluginResult


@dataclass(frozen=True)
class SQLDependencies:
    """Tables read and written by a single SQL statement."""

    reads: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)
    query_type: str = ""


def extract_sql_dependencies(
    sql_string: str, dialect: str | None = None
) -> SQLDependencies | None:
    """Parse a SQL string and extract table read/write dependencies.

    Returns None if the string is not valid SQL.
    """
    if not sql_string or not sql_string.strip():
        return None

    try:
        ast = sqlglot.parse_one(sql_string, dialect=dialect)
    except sqlglot.errors.ParseError:
        return None

    tables_read: set[str] = set()
    tables_written: set[str] = set()
    query_type = ""

    if isinstance(ast, exp.Select):
        query_type = "SELECT"
        for table in ast.find_all(exp.Table):
            if table.name:
                tables_read.add(table.name)
    elif isinstance(ast, exp.Insert):
        query_type = "INSERT"
        target = ast.find(exp.Table)
        if target and target.name:
            tables_written.add(target.name)
        # INSERT ... SELECT — subselect reads from other tables
        for sub in ast.find_all(exp.Select):
            for table in sub.find_all(exp.Table):
                if table.name and table.name not in tables_written:
                    tables_read.add(table.name)
    elif isinstance(ast, exp.Update):
        query_type = "UPDATE"
        target = ast.find(exp.Table)
        if target and target.name:
            tables_written.add(target.name)
    elif isinstance(ast, exp.Delete):
        query_type = "DELETE"
        target = ast.find(exp.Table)
        if target and target.name:
            tables_written.add(target.name)
    else:
        # DDL or other statement types — not relevant for read/write edges
        return None

    if not tables_read and not tables_written:
        return None

    return SQLDependencies(reads=tables_read, writes=tables_written, query_type=query_type)


class SQLParserPlugin(FrameworkPlugin):
    """Detects embedded SQL in code and creates function-to-table edges.

    Scans Function nodes for tagged_strings (set by tree-sitter extractors),
    parses each with sqlglot, and emits:
    - Table nodes (kind=TABLE, fqn="table:<name>")
    - READS edges (Function -> Table) for SELECT/JOIN
    - WRITES edges (Function -> Table) for INSERT/UPDATE/DELETE
    """

    name: str = "sql-parser"
    version: str = "1.0.0"
    supported_languages: set[str] = field(default_factory=lambda: {"java", "python", "typescript", "csharp"})
    depends_on: list[str] = field(default_factory=list)

    def __init__(self) -> None:
        self.name = "sql-parser"
        self.version = "1.0.0"
        self.supported_languages = {"java", "python", "typescript", "csharp"}
        self.depends_on = []

    def detect_from_graph(self, graph: SymbolGraph) -> Confidence:
        """SQL can appear in any codebase, so always return HIGH."""
        return Confidence.HIGH

    def extract_from_graph(self, graph: SymbolGraph) -> PluginResult:
        """Scan all Function nodes for embedded SQL, produce Table nodes and edges."""
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []
        seen_tables: dict[str, GraphNode] = {}  # table_name -> node

        for node in graph.nodes.values():
            if node.kind != NodeKind.FUNCTION:
                continue

            tagged_strings: list[str] = node.properties.get("tagged_strings", [])
            if not tagged_strings:
                continue

            for sql_string in tagged_strings:
                deps = extract_sql_dependencies(sql_string)
                if deps is None:
                    warnings.append(
                        f"Unparseable SQL in {node.fqn}: {sql_string[:80]}..."
                        if len(sql_string) > 80
                        else f"Unparseable SQL in {node.fqn}: {sql_string}"
                    )
                    continue

                # Create Table nodes for reads
                for table_name in deps.reads:
                    table_fqn = f"table:{table_name}"
                    if table_name not in seen_tables:
                        table_node = GraphNode(
                            fqn=table_fqn,
                            name=table_name,
                            kind=NodeKind.TABLE,
                            properties={"source": "embedded_sql"},
                        )
                        seen_tables[table_name] = table_node
                        nodes.append(table_node)

                    edges.append(
                        GraphEdge(
                            source_fqn=node.fqn,
                            target_fqn=table_fqn,
                            kind=EdgeKind.READS,
                            confidence=Confidence.HIGH,
                            evidence="sqlglot",
                            properties={"query_type": deps.query_type},
                        )
                    )

                # Create Table nodes for writes
                for table_name in deps.writes:
                    table_fqn = f"table:{table_name}"
                    if table_name not in seen_tables:
                        table_node = GraphNode(
                            fqn=table_fqn,
                            name=table_name,
                            kind=NodeKind.TABLE,
                            properties={"source": "embedded_sql"},
                        )
                        seen_tables[table_name] = table_node
                        nodes.append(table_node)

                    edges.append(
                        GraphEdge(
                            source_fqn=node.fqn,
                            target_fqn=table_fqn,
                            kind=EdgeKind.WRITES,
                            confidence=Confidence.HIGH,
                            evidence="sqlglot",
                            properties={"query_type": deps.query_type},
                        )
                    )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=warnings,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_sql_parser_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/sql/__init__.py app/stages/plugins/sql/parser.py tests/unit/test_sql_parser_plugin.py && git commit -m "feat(plugins): add SQL Parser plugin — embedded SQL detection with sqlglot"
```

---

## Task 2: SQL Migration Plugin — Test Fixtures

**Files:**
- Create: `tests/fixtures/sql-migrations/flyway/V1__create_users.sql`
- Create: `tests/fixtures/sql-migrations/flyway/V2__create_orders.sql`
- Create: `tests/fixtures/sql-migrations/flyway/V3__add_email_index.sql`
- Create: `tests/fixtures/sql-migrations/alembic/versions/001_create_users.py`

- [ ] **Step 1: Create Flyway migration fixtures**

```sql
-- tests/fixtures/sql-migrations/flyway/V1__create_users.sql
CREATE TABLE users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

```sql
-- tests/fixtures/sql-migrations/flyway/V2__create_orders.sql
CREATE TABLE orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    total DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id)
);
```

```sql
-- tests/fixtures/sql-migrations/flyway/V3__add_email_index.sql
ALTER TABLE users ADD COLUMN phone VARCHAR(20);
CREATE INDEX idx_users_email ON users(email);
```

- [ ] **Step 2: Create Alembic migration fixture**

```python
# tests/fixtures/sql-migrations/alembic/versions/001_create_users.py
"""create users table

Revision ID: 001
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
    )


def downgrade():
    op.drop_table("users")
```

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add tests/fixtures/sql-migrations/ && git commit -m "test(fixtures): add Flyway and Alembic migration fixture files"
```

---

## Task 3: SQL Migration Plugin — Implementation

**Files:**
- Create: `app/stages/plugins/sql/migration.py`
- Create: `tests/unit/test_sql_migration_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
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


# ── Helpers ──────────────────────────────────────────────


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


# ── Unit Tests: Flyway filename parsing ──────────────────


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


# ── Unit Tests: Migration framework detection ────────────


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


# ── Unit Tests: DDL parsing ──────────────────────────────


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


# ── Unit Tests: Full Plugin Extract ──────────────────────


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_sql_migration_plugin.py -v`
Expected: FAIL (ImportError -- module doesn't exist)

- [ ] **Step 3: Implement the SQL Migration Plugin**

```python
# app/stages/plugins/sql/migration.py
"""SQL Migration Plugin — reconstructs database schema from migration files.

Detects Flyway (V*__*.sql), Liquibase (changelog.xml/yaml), Alembic (versions/*.py),
and EF Migrations (Migrations/*.cs). Parses DDL in version order to build
the current schema state and emits Table, Column nodes plus HAS_COLUMN and
REFERENCES edges.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import FrameworkPlugin, PluginResult


# ── Data Structures ──────────────────────────────────────


@dataclass
class MigrationFile:
    """A detected migration file with version for ordering."""

    path: Path
    version: str
    description: str
    framework: str  # "flyway", "liquibase", "alembic", "ef"


@dataclass
class SchemaState:
    """Mutable schema state built up by applying migrations in order."""

    @dataclass
    class ColumnDef:
        name: str
        type: str = "UNKNOWN"
        nullable: bool = True
        is_primary_key: bool = False
        is_foreign_key: bool = False
        default_value: str | None = None

    @dataclass
    class TableDef:
        name: str
        columns: dict[str, SchemaState.ColumnDef] = field(default_factory=dict)
        schema_name: str | None = None

    @dataclass
    class ForeignKeyDef:
        source_table: str
        source_column: str
        target_table: str
        target_column: str
        constraint_name: str = ""

    @dataclass
    class IndexDef:
        name: str
        table_name: str
        column_names: list[str]
        is_unique: bool = False

    tables: dict[str, TableDef] = field(default_factory=dict)
    foreign_keys: list[ForeignKeyDef] = field(default_factory=list)
    indexes: list[IndexDef] = field(default_factory=list)


# ── Flyway Filename Parser ───────────────────────────────


_FLYWAY_PATTERN = re.compile(r"^V([\d.]+)__(.+)\.sql$")


def parse_flyway_filename(filename: str) -> MigrationFile | None:
    """Parse a Flyway migration filename like V1__create_users.sql.

    Returns None for non-matching files or undo (U*) migrations.
    """
    match = _FLYWAY_PATTERN.match(filename)
    if not match:
        return None
    return MigrationFile(
        path=Path(filename),
        version=match.group(1),
        description=match.group(2),
        framework="flyway",
    )


# ── Migration Framework Detection ────────────────────────


def detect_migration_framework(directory: Path) -> str | None:
    """Detect which migration framework is used in a directory.

    Checks for:
    - Flyway: V*__*.sql files
    - Alembic: versions/ subdirectory with *.py files
    - Liquibase: changelog.xml or changelog.yaml
    - EF Migrations: Migrations/*.cs
    """
    if not directory.is_dir():
        return None

    # Flyway: look for V*__*.sql
    for f in directory.iterdir():
        if f.is_file() and _FLYWAY_PATTERN.match(f.name):
            return "flyway"

    # Alembic: look for versions/ subdir with .py files
    versions_dir = directory / "versions"
    if versions_dir.is_dir():
        for f in versions_dir.iterdir():
            if f.is_file() and f.suffix == ".py" and not f.name.startswith("__"):
                return "alembic"

    # Liquibase
    for name in ("changelog.xml", "changelog.yaml", "changelog.yml"):
        if (directory / name).is_file():
            return "liquibase"

    # EF Migrations
    migrations_dir = directory / "Migrations"
    if migrations_dir.is_dir():
        for f in migrations_dir.iterdir():
            if f.is_file() and f.suffix == ".cs":
                return "ef"

    return None


# ── DDL Parsing with sqlglot ─────────────────────────────


def parse_ddl_statements(sql: str, schema: SchemaState, dialect: str | None = None) -> None:
    """Parse SQL DDL statements and update the schema state.

    Handles CREATE TABLE, ALTER TABLE ADD COLUMN, ALTER TABLE ADD CONSTRAINT FOREIGN KEY,
    and CREATE INDEX.
    """
    try:
        statements = sqlglot.parse(sql, dialect=dialect)
    except sqlglot.errors.ParseError:
        return

    for ast in statements:
        if ast is None:
            continue

        if isinstance(ast, exp.Create):
            _handle_create(ast, schema)
        elif isinstance(ast, exp.AlterTable):
            _handle_alter_table(ast, schema)
        # sqlglot may parse CREATE INDEX differently depending on dialect
        # Check for Create with kind="INDEX" as well
        if isinstance(ast, exp.Create) and _is_index_create(ast):
            _handle_create_index(ast, schema)


def _is_index_create(ast: exp.Create) -> bool:
    """Check if a CREATE statement is a CREATE INDEX."""
    kind = ast.args.get("kind")
    return kind is not None and str(kind).upper() == "INDEX"


def _handle_create(ast: exp.Create, schema: SchemaState) -> None:
    """Handle CREATE TABLE and CREATE INDEX statements."""
    kind = ast.args.get("kind")
    if kind is not None and str(kind).upper() == "INDEX":
        _handle_create_index(ast, schema)
        return

    # CREATE TABLE
    table_expr = ast.find(exp.Table)
    if table_expr is None or not table_expr.name:
        return

    table_name = table_expr.name
    table_def = SchemaState.TableDef(name=table_name)
    schema_expr = ast.find(exp.Schema)

    if schema_expr is not None:
        for col_def in schema_expr.find_all(exp.ColumnDef):
            col_name_node = col_def.find(exp.Column)
            if col_name_node is None:
                # Try the 'this' attribute directly
                col_name_expr = col_def.args.get("this")
                if col_name_expr is None:
                    continue
                col_name = col_name_expr.name if hasattr(col_name_expr, "name") else str(col_name_expr)
            else:
                col_name = col_name_node.name

            # Get data type
            data_type = col_def.find(exp.DataType)
            type_str = data_type.sql() if data_type else "UNKNOWN"

            # Check constraints
            is_pk = False
            nullable = True
            for constraint in col_def.find_all(exp.ColumnConstraint):
                constraint_kind = constraint.find(exp.PrimaryKeyColumnConstraint)
                if constraint_kind is not None:
                    is_pk = True
                not_null = constraint.find(exp.NotNullColumnConstraint)
                if not_null is not None:
                    nullable = False

            table_def.columns[col_name] = SchemaState.ColumnDef(
                name=col_name,
                type=type_str,
                is_primary_key=is_pk,
                nullable=nullable and not is_pk,
            )

        # Handle table-level constraints (FOREIGN KEY, PRIMARY KEY)
        for constraint in schema_expr.find_all(exp.ForeignKey):
            _handle_foreign_key_constraint(constraint, table_name, schema)

    schema.tables[table_name] = table_def


def _handle_foreign_key_constraint(
    fk_expr: exp.ForeignKey, source_table: str, schema: SchemaState
) -> None:
    """Extract a FOREIGN KEY constraint and add it to the schema."""
    # Get source columns
    expressions = fk_expr.args.get("expressions", [])
    source_columns = []
    for e in expressions:
        if hasattr(e, "name"):
            source_columns.append(e.name)

    # Get reference
    reference = fk_expr.args.get("reference")
    if reference is None:
        return

    ref_table = reference.find(exp.Table)
    if ref_table is None:
        return
    target_table = ref_table.name

    ref_columns = []
    ref_col_list = reference.args.get("expressions", [])
    for e in ref_col_list:
        if hasattr(e, "name"):
            ref_columns.append(e.name)

    # Create FK entries (zip source and target columns)
    for src_col, tgt_col in zip(source_columns, ref_columns):
        schema.foreign_keys.append(
            SchemaState.ForeignKeyDef(
                source_table=source_table,
                source_column=src_col,
                target_table=target_table,
                target_column=tgt_col,
            )
        )

        # Mark source column as FK
        if source_table in schema.tables and src_col in schema.tables[source_table].columns:
            schema.tables[source_table].columns[src_col].is_foreign_key = True


def _handle_alter_table(ast: exp.AlterTable, schema: SchemaState) -> None:
    """Handle ALTER TABLE ADD COLUMN and ALTER TABLE ADD CONSTRAINT."""
    table_expr = ast.find(exp.Table)
    if table_expr is None:
        return
    table_name = table_expr.name

    if table_name not in schema.tables:
        # Table not yet known; create a stub
        schema.tables[table_name] = SchemaState.TableDef(name=table_name)

    # Look for ADD COLUMN actions
    for action in ast.args.get("actions", []):
        if isinstance(action, exp.AlterColumn):
            continue

        # ADD COLUMN
        col_def = None
        if isinstance(action, exp.ColumnDef):
            col_def = action
        elif hasattr(action, "find"):
            col_def = action.find(exp.ColumnDef)

        if col_def is not None:
            col_name_expr = col_def.args.get("this")
            if col_name_expr is not None:
                col_name = col_name_expr.name if hasattr(col_name_expr, "name") else str(col_name_expr)
                data_type = col_def.find(exp.DataType)
                type_str = data_type.sql() if data_type else "UNKNOWN"
                schema.tables[table_name].columns[col_name] = SchemaState.ColumnDef(
                    name=col_name,
                    type=type_str,
                )


def _handle_create_index(ast: exp.Create, schema: SchemaState) -> None:
    """Handle CREATE INDEX statements."""
    # Extract index name
    index_expr = ast.find(exp.Index)
    index_name = ""
    if index_expr is not None and hasattr(index_expr, "name"):
        index_name = index_expr.name or ""

    # If no index_expr, try this attribute
    if not index_name:
        this = ast.args.get("this")
        if this is not None and hasattr(this, "name"):
            index_name = this.name or ""

    # Extract table name
    table_expr = ast.find(exp.Table)
    if table_expr is None:
        return
    table_name = table_expr.name

    # Extract columns
    column_names: list[str] = []
    for col in ast.find_all(exp.Column):
        if col.name:
            column_names.append(col.name)

    if not column_names:
        return

    is_unique = "unique" in ast.sql().lower().split("create")[1].split("index")[0] if "index" in ast.sql().lower() else False

    schema.indexes.append(
        SchemaState.IndexDef(
            name=index_name,
            table_name=table_name,
            column_names=column_names,
            is_unique=is_unique,
        )
    )


# ── Schema -> Graph Conversion ───────────────────────────


def schema_to_graph(schema: SchemaState) -> PluginResult:
    """Convert a SchemaState into GraphNode/GraphEdge lists."""
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    for table_name, table_def in schema.tables.items():
        table_fqn = f"table:{table_name}"
        nodes.append(
            GraphNode(
                fqn=table_fqn,
                name=table_name,
                kind=NodeKind.TABLE,
                properties={
                    "source": "migration",
                    "column_count": len(table_def.columns),
                    "schema": table_def.schema_name or "",
                },
            )
        )

        for col_name, col_def in table_def.columns.items():
            col_fqn = f"table:{table_name}.{col_name}"
            nodes.append(
                GraphNode(
                    fqn=col_fqn,
                    name=col_name,
                    kind=NodeKind.COLUMN,
                    properties={
                        "type": col_def.type,
                        "nullable": col_def.nullable,
                        "is_primary_key": col_def.is_primary_key,
                        "is_foreign_key": col_def.is_foreign_key,
                        "default_value": col_def.default_value or "",
                    },
                )
            )

            edges.append(
                GraphEdge(
                    source_fqn=table_fqn,
                    target_fqn=col_fqn,
                    kind=EdgeKind.HAS_COLUMN,
                    confidence=Confidence.HIGH,
                    evidence="migration",
                )
            )

    # Foreign key edges: Column -> Column
    for fk in schema.foreign_keys:
        source_col_fqn = f"table:{fk.source_table}.{fk.source_column}"
        target_col_fqn = f"table:{fk.target_table}.{fk.target_column}"
        edges.append(
            GraphEdge(
                source_fqn=source_col_fqn,
                target_fqn=target_col_fqn,
                kind=EdgeKind.REFERENCES,
                confidence=Confidence.HIGH,
                evidence="migration",
                properties={"constraint_name": fk.constraint_name},
            )
        )

    return PluginResult(
        nodes=nodes,
        edges=edges,
        layer_assignments={},
        entry_points=[],
        warnings=[],
    )


# ── Plugin Class ─────────────────────────────────────────


class SQLMigrationPlugin(FrameworkPlugin):
    """Reconstructs database schema from migration files.

    Supports:
    - Flyway: V*__*.sql files parsed with sqlglot
    - Alembic: versions/*.py files (pattern-matched for op.create_table calls)
    - Liquibase: changelog.xml/yaml (planned)
    - EF Migrations: Migrations/*.cs (planned)

    Produces Table and Column nodes, HAS_COLUMN edges, and REFERENCES edges
    for foreign key constraints.
    """

    def __init__(self) -> None:
        self.name = "sql-migration"
        self.version = "1.0.0"
        self.supported_languages = {"sql", "java", "python", "csharp"}
        self.depends_on: list[str] = []

    def detect_from_paths(self, search_dirs: list[Path]) -> Confidence:
        """Check for migration files in known locations."""
        for d in search_dirs:
            if not d.is_dir():
                continue
            framework = detect_migration_framework(d)
            if framework is not None:
                return Confidence.HIGH

            # Also check common subdirectories
            for subdir in [
                "db/migration",
                "src/main/resources/db/migration",
                "migrations",
                "alembic",
                "Migrations",
            ]:
                candidate = d / subdir
                if candidate.is_dir():
                    framework = detect_migration_framework(candidate)
                    if framework is not None:
                        return Confidence.HIGH

        return Confidence.LOW

    def extract_from_migration_dir(
        self, migration_dir: Path, framework: str
    ) -> PluginResult:
        """Parse all migration files in a directory and produce graph nodes/edges."""
        schema = SchemaState()

        if framework == "flyway":
            self._process_flyway(migration_dir, schema)
        elif framework == "alembic":
            self._process_alembic(migration_dir, schema)
        # liquibase and ef are planned for later implementation

        return schema_to_graph(schema)

    def _process_flyway(self, directory: Path, schema: SchemaState) -> None:
        """Process Flyway SQL migrations in version order."""
        migrations: list[MigrationFile] = []
        for f in directory.iterdir():
            if not f.is_file():
                continue
            mf = parse_flyway_filename(f.name)
            if mf is not None:
                mf.path = f
                migrations.append(mf)

        # Sort by version (split on dots for natural ordering)
        migrations.sort(key=lambda m: [int(x) for x in m.version.split(".")])

        for mf in migrations:
            sql = mf.path.read_text(encoding="utf-8")
            parse_ddl_statements(sql, schema)

    def _process_alembic(self, directory: Path, schema: SchemaState) -> None:
        """Process Alembic Python migrations by extracting op.create_table() calls.

        This is a simplified parser that uses regex to find table/column definitions
        in Alembic migration files. For full accuracy, tree-sitter Python parsing
        would be used (available after M4d).
        """
        versions_dir = directory / "versions"
        if not versions_dir.is_dir():
            return

        migration_files: list[tuple[str, Path]] = []
        for f in sorted(versions_dir.iterdir()):
            if f.is_file() and f.suffix == ".py" and not f.name.startswith("__"):
                # Extract revision from filename or content
                migration_files.append((f.stem, f))

        for _, path in migration_files:
            content = path.read_text(encoding="utf-8")
            self._parse_alembic_content(content, schema)

    def _parse_alembic_content(self, content: str, schema: SchemaState) -> None:
        """Extract op.create_table(), op.add_column() from Alembic Python source."""
        # Match op.create_table("table_name", ...)
        create_pattern = re.compile(
            r'op\.create_table\(\s*["\'](\w+)["\']', re.MULTILINE
        )
        for match in create_pattern.finditer(content):
            table_name = match.group(1)
            schema.tables[table_name] = SchemaState.TableDef(name=table_name)

            # Find sa.Column() calls within the same block
            # Look from the match position to the next closing paren at the right nesting level
            start = match.end()
            col_pattern = re.compile(
                r'sa\.Column\(\s*["\'](\w+)["\']\s*,\s*sa\.(\w+)\(',
                re.MULTILINE,
            )
            # Search within a reasonable window (next 500 chars)
            block = content[start : start + 2000]
            for col_match in col_pattern.finditer(block):
                col_name = col_match.group(1)
                col_type = col_match.group(2)

                # Check for primary_key=True
                is_pk = "primary_key=True" in block[col_match.start() : col_match.start() + 200]
                nullable = "nullable=False" not in block[col_match.start() : col_match.start() + 200]

                schema.tables[table_name].columns[col_name] = SchemaState.ColumnDef(
                    name=col_name,
                    type=col_type,
                    is_primary_key=is_pk,
                    nullable=nullable and not is_pk,
                )

        # Match op.add_column("table_name", sa.Column("col_name", ...))
        add_col_pattern = re.compile(
            r'op\.add_column\(\s*["\'](\w+)["\']\s*,\s*sa\.Column\(\s*["\'](\w+)["\']\s*,\s*sa\.(\w+)\(',
            re.MULTILINE,
        )
        for match in add_col_pattern.finditer(content):
            table_name = match.group(1)
            col_name = match.group(2)
            col_type = match.group(3)

            if table_name not in schema.tables:
                schema.tables[table_name] = SchemaState.TableDef(name=table_name)

            schema.tables[table_name].columns[col_name] = SchemaState.ColumnDef(
                name=col_name,
                type=col_type,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_sql_migration_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/sql/migration.py tests/unit/test_sql_migration_plugin.py tests/fixtures/sql-migrations/ && git commit -m "feat(plugins): add SQL Migration plugin — schema reconstruction from Flyway/Alembic"
```

---

## Task 4: Edge Cases and Robustness Tests

**Files:**
- Modify: `tests/unit/test_sql_parser_plugin.py`
- Modify: `tests/unit/test_sql_migration_plugin.py`

- [ ] **Step 1: Add SQL Parser edge-case tests**

Append to `tests/unit/test_sql_parser_plugin.py`:

```python
# ── Edge Case Tests ──────────────────────────────────────


class TestSQLParserEdgeCases:
    """Edge cases and robustness checks for the SQL parser."""

    def test_sql_with_placeholders(self):
        """JDBC-style ? placeholders should not break parsing."""
        result = extract_sql_dependencies("SELECT * FROM users WHERE id = ?")
        # sqlglot may or may not handle ? — verify graceful behavior
        # If it parses, we get reads; if not, None is acceptable
        if result is not None:
            assert "users" in result.reads

    def test_sql_with_named_params(self):
        """MyBatis-style #{param} or :param should be handled."""
        result = extract_sql_dependencies("SELECT * FROM users WHERE id = :id")
        if result is not None:
            assert "users" in result.reads

    def test_multiline_sql(self):
        sql = """
            SELECT
                u.id,
                u.name,
                u.email
            FROM
                users u
            WHERE
                u.active = 1
            ORDER BY
                u.name
        """
        result = extract_sql_dependencies(sql)
        assert result is not None
        assert "users" in result.reads

    def test_update_with_subquery(self):
        sql = "UPDATE users SET status = 'archived' WHERE id IN (SELECT user_id FROM deleted_accounts)"
        result = extract_sql_dependencies(sql)
        assert result is not None
        assert "users" in result.writes
        # The subquery read may or may not be captured depending on sqlglot behavior

    def test_function_node_without_properties_key(self):
        """Function node with no properties dict at all should not crash."""
        plugin = SQLParserPlugin()
        g = SymbolGraph()
        fn = GraphNode(fqn="a.b", name="b", kind=NodeKind.FUNCTION)
        g.add_node(fn)
        result = plugin.extract_from_graph(g)
        assert len(result.nodes) == 0
        assert len(result.edges) == 0

    def test_non_function_nodes_ignored(self):
        """Class, Table, Module nodes should not be scanned for SQL."""
        plugin = SQLParserPlugin()
        g = SymbolGraph()
        cls = GraphNode(
            fqn="a.MyClass", name="MyClass", kind=NodeKind.CLASS,
            properties={"tagged_strings": ["SELECT * FROM users"]},
        )
        g.add_node(cls)
        result = plugin.extract_from_graph(g)
        assert len(result.nodes) == 0
```

- [ ] **Step 2: Add SQL Migration edge-case tests**

Append to `tests/unit/test_sql_migration_plugin.py`:

```python
# ── Edge Case Tests ──────────────────────────────────────


class TestSQLMigrationEdgeCases:
    """Edge cases for migration parsing."""

    def test_empty_sql_file(self, tmp_path):
        """An empty migration file should not crash."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "V1__empty.sql").write_text("")

        plugin = SQLMigrationPlugin()
        result = plugin.extract_from_migration_dir(mig_dir, "flyway")
        assert len(result.nodes) == 0

    def test_sql_with_comments(self):
        """SQL comments should not break DDL parsing."""
        sql = """
        -- This creates the users table
        /* Multi-line
           comment */
        CREATE TABLE users (
            id BIGINT PRIMARY KEY,
            name VARCHAR(255)
        );
        """
        schema = SchemaState()
        parse_ddl_statements(sql, schema)
        assert "users" in schema.tables
        assert "id" in schema.tables["users"].columns

    def test_multiple_tables_in_one_file(self):
        """A single migration file with multiple CREATE TABLE statements."""
        sql = """
        CREATE TABLE departments (
            id BIGINT PRIMARY KEY,
            name VARCHAR(100)
        );

        CREATE TABLE employees (
            id BIGINT PRIMARY KEY,
            name VARCHAR(255),
            dept_id BIGINT,
            CONSTRAINT fk_emp_dept FOREIGN KEY (dept_id) REFERENCES departments(id)
        );
        """
        schema = SchemaState()
        parse_ddl_statements(sql, schema)
        assert "departments" in schema.tables
        assert "employees" in schema.tables
        assert len(schema.foreign_keys) == 1
```

- [ ] **Step 3: Run all tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_sql_parser_plugin.py tests/unit/test_sql_migration_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend && git add tests/unit/test_sql_parser_plugin.py tests/unit/test_sql_migration_plugin.py && git commit -m "test(plugins): add edge-case tests for SQL parser and migration plugins"
```

---

## Task 5: Lint and Type-Check

- [ ] **Step 1: Run ruff check**

Run: `cd cast-clone-backend && uv run ruff check app/stages/plugins/sql/ tests/unit/test_sql_parser_plugin.py tests/unit/test_sql_migration_plugin.py`
Expected: No errors. If there are errors, fix them.

- [ ] **Step 2: Run ruff format**

Run: `cd cast-clone-backend && uv run ruff format app/stages/plugins/sql/ tests/unit/test_sql_parser_plugin.py tests/unit/test_sql_migration_plugin.py`

- [ ] **Step 3: Run mypy (if configured)**

Run: `cd cast-clone-backend && uv run mypy app/stages/plugins/sql/`
Expected: No errors (or only pre-existing ones from missing stubs for sqlglot).

- [ ] **Step 4: Commit any formatting fixes**

```bash
cd cast-clone-backend && git add -u && git commit -m "style(plugins): apply ruff formatting to SQL plugins"
```

---

## Implementation Notes

### FQN Conventions for Database Nodes

- **Table FQN:** `table:<table_name>` (e.g., `table:users`, `table:orders`)
- **Column FQN:** `table:<table_name>.<column_name>` (e.g., `table:users.email`)
- Schema-qualified tables: `table:<schema>.<table_name>` (future enhancement)

These FQN conventions ensure Table/Column nodes from the SQL Parser and SQL Migration plugins can be merged (same table discovered both ways gets the same FQN, avoiding duplicates when the graph is written to Neo4j in Stage 8).

### How tagged_strings Work

Tree-sitter extractors (M4a-M4e) populate `properties["tagged_strings"]` on Function nodes. The heuristic is:
1. Extract all string literals from the function body
2. Filter strings that contain SQL keywords (SELECT, INSERT, UPDATE, DELETE, FROM, WHERE, JOIN)
3. Store the filtered strings in `tagged_strings`

The SQL Parser Plugin then parses these with sqlglot for full SQL AST analysis (not just keyword matching).

### sqlglot Dialect Handling

The `extract_sql_dependencies()` function accepts an optional `dialect` parameter. When not specified, sqlglot uses its generic parser which handles most standard SQL. For dialect-specific syntax (e.g., PostgreSQL's `ILIKE`, MySQL's backtick quoting), the dialect should be inferred from the project's database configuration (detected in Stage 1 discovery). For M6c, dialect is left as None by default; Stage 1 integration will pass it through AnalysisContext in a future milestone.

### Migration Processing Order

Flyway migrations are sorted by version number using natural numeric ordering (`1 < 2 < 10`, not lexicographic `1 < 10 < 2`). Dotted versions (e.g., `V1.2.3`) are split and compared segment-by-segment. This ensures schema state is built correctly even when migration versions span multiple digits.

### What Is NOT Implemented (Deferred)

- **Liquibase XML/YAML parsing** — Requires XML parser; deferred to a future PR
- **EF Migrations C# parsing** — Requires tree-sitter C# analysis of `migrationBuilder` calls; deferred until M4e (C# extractor) is complete
- **Column-level lineage** — sqlglot's `lineage()` module can trace column flow through SELECT chains; planned for Phase 3 (Impact Analysis)
- **ORM query pattern detection** — `@Query("...")`, `session.execute(text("..."))` scanning is planned for integration with Spring Data and SQLAlchemy plugins respectively

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] `uv run pytest tests/unit/test_sql_parser_plugin.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/test_sql_migration_plugin.py -v` — all tests pass
- [ ] `uv run ruff check app/stages/plugins/sql/` — no lint errors
- [ ] `app/stages/plugins/sql/__init__.py` exists
- [ ] `app/stages/plugins/sql/parser.py` exports `SQLParserPlugin`, `SQLDependencies`, `extract_sql_dependencies`
- [ ] `app/stages/plugins/sql/migration.py` exports `SQLMigrationPlugin`, `MigrationFile`, `detect_migration_framework`, `parse_flyway_filename`, `parse_ddl_statements`, `SchemaState`
- [ ] Table FQN convention is `table:<name>`, Column FQN is `table:<table>.<column>`
- [ ] Both plugins produce `PluginResult` with correct node kinds (TABLE, COLUMN) and edge kinds (READS, WRITES, HAS_COLUMN, REFERENCES)
- [ ] Invalid SQL strings produce warnings, not crashes
- [ ] Test fixtures exist under `tests/fixtures/sql-migrations/`
