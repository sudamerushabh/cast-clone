"""Flask-RESTful Resource + MethodView helpers (M4 Tasks 8-10)."""

from __future__ import annotations

from app.models.enums import EdgeKind, NodeKind
from app.models.graph import SymbolGraph

_HTTP_METHOD_NAMES: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options"}
)


def _class_inherits_from(
    graph: SymbolGraph, class_fqn: str, bases: frozenset[str]
) -> bool:
    """Return True if the class has an INHERITS edge whose target matches any base.

    Matches the raw base name or any FQN ending in `.<base>` (accommodates
    'flask_restful.Resource' etc.).
    """
    for edge in graph.edges:
        if edge.kind != EdgeKind.INHERITS or edge.source_fqn != class_fqn:
            continue
        target = edge.target_fqn
        if target in bases:
            return True
        for base in bases:
            if target.endswith(f".{base}"):
                return True
    return False


def enumerate_resource_methods(
    graph: SymbolGraph, base_classes: frozenset[str]
) -> dict[str, list[tuple[str, str]]]:
    """Return `{class_fqn: [(HTTP_METHOD, method_fqn), ...]}` for every class that
    inherits (directly) from any of the given base class names and defines at least
    one HTTP-named method.
    """
    contained: dict[str, list[tuple[str, str]]] = {}
    for edge in graph.edges:
        if edge.kind != EdgeKind.CONTAINS:
            continue
        child = graph.get_node(edge.target_fqn)
        if child is None or child.kind != NodeKind.FUNCTION:
            continue
        contained.setdefault(edge.source_fqn, []).append((child.name, child.fqn))

    result: dict[str, list[tuple[str, str]]] = {}
    for node in graph.nodes.values():
        if node.kind != NodeKind.CLASS or node.language != "python":
            continue
        if not _class_inherits_from(graph, node.fqn, base_classes):
            continue
        methods: list[tuple[str, str]] = []
        for child_name, child_fqn in contained.get(node.fqn, []):
            if child_name.lower() in _HTTP_METHOD_NAMES:
                methods.append((child_name.upper(), child_fqn))
        if methods:
            result[node.fqn] = methods
    return result
