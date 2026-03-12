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
from app.stages.plugins.base import FrameworkPlugin, PluginDetectionResult, PluginResult


# -- Data Structures --------------------------------------------------


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


# -- Flyway Filename Parser -------------------------------------------


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


# -- Migration Framework Detection ------------------------------------


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


# -- DDL Parsing with sqlglot -----------------------------------------


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
        elif isinstance(ast, exp.Alter):
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
    # Reference columns may be in reference.this.expressions (Schema node)
    # or in reference.expressions depending on sqlglot version
    ref_schema = reference.args.get("this")
    if ref_schema is not None and hasattr(ref_schema, "args"):
        ref_col_list = ref_schema.args.get("expressions", []) or []
    else:
        ref_col_list = reference.args.get("expressions", []) or []
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


def _handle_alter_table(ast: exp.Alter, schema: SchemaState) -> None:
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


# -- Schema -> Graph Conversion ---------------------------------------


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


# -- Plugin Class -----------------------------------------------------


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

    def detect(self, context: Any) -> PluginDetectionResult:
        """Detect migration files in the project."""
        return PluginDetectionResult(confidence=Confidence.LOW, reason="no migration dirs provided")

    async def extract(self, context: Any) -> PluginResult:
        """Extract schema from migration files in the analysis context."""
        return PluginResult.empty()

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
            # Search within a reasonable window (next 2000 chars)
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
