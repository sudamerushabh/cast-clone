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
from app.stages.plugins.base import FrameworkPlugin, PluginDetectionResult, PluginResult


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

    def __init__(self) -> None:
        self.name = "sql-parser"
        self.version = "1.0.0"
        self.supported_languages = {"java", "python", "typescript", "csharp"}
        self.depends_on: list[str] = []

    def detect(self, context: Any) -> PluginDetectionResult:
        """SQL can appear in any codebase, so always return HIGH."""
        return PluginDetectionResult(confidence=Confidence.HIGH, reason="SQL can appear in any codebase")

    async def extract(self, context: Any) -> PluginResult:
        """Extract embedded SQL from the analysis context's graph."""
        graph: SymbolGraph = context.graph
        return self.extract_from_graph(graph)

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
