"""Flask-SQLAlchemy db.Model adapter (M4 Tasks 11-12)."""

from __future__ import annotations

import re

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph

_DB_MODEL_BASES: frozenset[str] = frozenset({"db.Model", "Model"})
_SNAKECASE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _to_snake_case(name: str) -> str:
    return _SNAKECASE_RE.sub("_", name).lower()


def _class_is_flask_model(graph: SymbolGraph, class_fqn: str) -> bool:
    for edge in graph.edges:
        if edge.kind != EdgeKind.INHERITS or edge.source_fqn != class_fqn:
            continue
        target = edge.target_fqn
        if target in _DB_MODEL_BASES:
            return True
        for base in _DB_MODEL_BASES:
            if target.endswith(f".{base}"):
                return True
    return False


def _find_tablename(graph: SymbolGraph, class_fqn: str) -> str | None:
    for edge in graph.edges:
        if edge.kind != EdgeKind.CONTAINS or edge.source_fqn != class_fqn:
            continue
        child = graph.get_node(edge.target_fqn)
        if (
            child is not None
            and child.kind == NodeKind.FIELD
            and child.name == "__tablename__"
        ):
            raw = child.properties.get("value", "").strip()
            if (raw.startswith('"') and raw.endswith('"')) or (
                raw.startswith("'") and raw.endswith("'")
            ):
                return raw[1:-1]
    return None


def extract_flask_sqlalchemy_tables(
    graph: SymbolGraph,
) -> list[tuple[GraphNode, str]]:
    """Return [(TableNode, source_class_fqn), ...] for each Flask-SQLAlchemy model."""
    results: list[tuple[GraphNode, str]] = []
    for node in graph.nodes.values():
        if node.kind != NodeKind.CLASS or node.language != "python":
            continue
        if not _class_is_flask_model(graph, node.fqn):
            continue
        table_name = _find_tablename(graph, node.fqn) or _to_snake_case(node.name)
        table = GraphNode(
            fqn=f"table::{table_name}",
            name=table_name,
            kind=NodeKind.TABLE,
            language="python",
            properties={"framework": "flask-sqlalchemy"},
        )
        results.append((table, node.fqn))
    return results


_DB_COLUMN_CALL_RE = re.compile(r"^db\.Column\(")
_DB_TYPE_SIMPLE_RE = re.compile(
    r"db\.(Integer|BigInteger|SmallInteger|Boolean|Float|Numeric|Date|DateTime|Text)"
)
_DB_TYPE_STRING_RE = re.compile(r"db\.String\(\s*(\d+)\s*\)")
_FOREIGN_KEY_RE = re.compile(r"db\.ForeignKey\(\s*[\"']([^\"']+)[\"']")
_TRUE_KWARG_RE = re.compile(r"(primary_key|unique|nullable)\s*=\s*(True|False)")

_DB_TYPE_TO_SQL: dict[str, str] = {
    "Integer": "INTEGER",
    "BigInteger": "BIGINT",
    "SmallInteger": "SMALLINT",
    "Boolean": "BOOLEAN",
    "Float": "FLOAT",
    "Numeric": "NUMERIC",
    "Date": "DATE",
    "DateTime": "TIMESTAMP",
    "Text": "TEXT",
}


def _parse_column_type(raw: str) -> str:
    str_match = _DB_TYPE_STRING_RE.search(raw)
    if str_match:
        return f"VARCHAR({str_match.group(1)})"
    simple_match = _DB_TYPE_SIMPLE_RE.search(raw)
    if simple_match:
        return _DB_TYPE_TO_SQL[simple_match.group(1)]
    return "UNKNOWN"


def _parse_column_flags(raw: str) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for match in _TRUE_KWARG_RE.finditer(raw):
        flags[match.group(1)] = match.group(2) == "True"
    return flags


def extract_flask_sqlalchemy_columns(
    graph: SymbolGraph,
) -> tuple[list[GraphNode], list[GraphEdge], list[GraphEdge]]:
    """Return ``(column_nodes, has_column_edges, reference_edges)`` for every
    Flask-SQLAlchemy model class.
    """
    columns: list[GraphNode] = []
    has_column: list[GraphEdge] = []
    references: list[GraphEdge] = []

    for cls_node in graph.nodes.values():
        if cls_node.kind != NodeKind.CLASS or cls_node.language != "python":
            continue
        if not _class_is_flask_model(graph, cls_node.fqn):
            continue
        table_name = _find_tablename(graph, cls_node.fqn) or _to_snake_case(
            cls_node.name
        )
        table_fqn = f"table::{table_name}"

        for edge in graph.edges:
            if edge.kind != EdgeKind.CONTAINS or edge.source_fqn != cls_node.fqn:
                continue
            child = graph.get_node(edge.target_fqn)
            if child is None or child.kind != NodeKind.FIELD:
                continue
            if child.name == "__tablename__":
                continue
            raw = child.properties.get("value", "").strip()
            if not _DB_COLUMN_CALL_RE.match(raw):
                continue

            col_fqn = f"column::{table_name}.{child.name}"
            flags = _parse_column_flags(raw)
            column = GraphNode(
                fqn=col_fqn,
                name=child.name,
                kind=NodeKind.COLUMN,
                language="python",
                properties={
                    "type": _parse_column_type(raw),
                    "primary_key": flags.get("primary_key", False),
                    "nullable": flags.get("nullable", True),
                    "unique": flags.get("unique", False),
                    "framework": "flask-sqlalchemy",
                },
            )
            columns.append(column)
            has_column.append(
                GraphEdge(
                    source_fqn=table_fqn,
                    target_fqn=col_fqn,
                    kind=EdgeKind.HAS_COLUMN,
                    confidence=Confidence.HIGH,
                    evidence="flask-sqlalchemy",
                )
            )
            fk_match = _FOREIGN_KEY_RE.search(raw)
            if fk_match:
                target_spec = fk_match.group(1)
                references.append(
                    GraphEdge(
                        source_fqn=col_fqn,
                        target_fqn=f"column::{target_spec}",
                        kind=EdgeKind.REFERENCES,
                        confidence=Confidence.HIGH,
                        evidence="flask-sqlalchemy-foreignkey",
                    )
                )
    return columns, has_column, references
