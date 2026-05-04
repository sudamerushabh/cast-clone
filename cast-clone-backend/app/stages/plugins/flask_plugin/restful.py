"""Flask-RESTful Resource + MethodView helpers (M4 Tasks 8-10)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from app.models.enums import EdgeKind, NodeKind
from app.models.graph import SymbolGraph

_HTTP_METHOD_NAMES: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options"}
)

_API_CTOR_RE = re.compile(r"Api\([^)]*?prefix\s*=\s*[\"']([^\"']+)[\"']")
_ADD_RESOURCE_RE = re.compile(r"add_resource\(\s*(\w+)\s*,\s*[\"']([^\"']+)[\"']")


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


def _join_prefix(prefix: str, path: str) -> str:
    if not prefix:
        return path
    if not path:
        return prefix
    if prefix.endswith("/") and path.startswith("/"):
        return prefix + path[1:]
    if not prefix.endswith("/") and not path.startswith("/"):
        return f"{prefix}/{path}"
    return prefix + path


def resolve_restful_bindings(project_root: str) -> dict[str, str]:
    """Return `{resource_class_name: effective_path}` by scanning .py files.

    Resolves the Api(prefix=...) global prefix and joins it with every
    api.add_resource(cls, "/path") call. When no Api prefix is present,
    the path is used as-is.
    """
    bindings: dict[str, str] = {}
    root = Path(project_root)
    if not root.exists():
        return bindings

    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(dirpath) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            api_prefix_match = _API_CTOR_RE.search(text)
            api_prefix = api_prefix_match.group(1) if api_prefix_match else ""
            for match in _ADD_RESOURCE_RE.finditer(text):
                cls_name = match.group(1)
                path = match.group(2)
                bindings[cls_name] = _join_prefix(api_prefix, path)
    return bindings
