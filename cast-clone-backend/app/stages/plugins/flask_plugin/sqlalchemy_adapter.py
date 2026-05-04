"""Flask-SQLAlchemy db.Model adapter (M4 Tasks 11-12)."""

from __future__ import annotations

import re

from app.models.enums import EdgeKind, NodeKind
from app.models.graph import GraphNode, SymbolGraph

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
