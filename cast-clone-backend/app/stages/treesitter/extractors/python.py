"""Python tree-sitter extractor.

Parses Python source files into GraphNode and GraphEdge lists using
tree-sitter-python. Extracts modules, classes, functions, fields, imports,
calls, inheritance, decorators, and SQL-like string literals.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Tree

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.treesitter.extractors import register_extractor

logger = structlog.get_logger(__name__)

PY_LANGUAGE = Language(tspython.language())

# ── SQL heuristic ────────────────────────────────────────────────
_SQL_KEYWORDS_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE"
    r"|FROM|WHERE|JOIN|GROUP\s+BY|ORDER\s+BY)\b",
    re.IGNORECASE,
)


def _looks_like_sql(text: str) -> bool:
    """Return True if the string looks like an embedded SQL statement."""
    # Must have at least 2 SQL keywords to reduce false positives
    matches = _SQL_KEYWORDS_RE.findall(text)
    return len(matches) >= 2


def _derive_module_fqn(file_path: str, root_path: str) -> str:
    """Derive a Python module FQN from a file path relative to the root.

    Examples:
        ("/code/pkg/mod.py", "/code") -> "pkg.mod"
        ("/code/pkg/__init__.py", "/code") -> "pkg"
        ("/code/main.py", "/code") -> "main"
    """
    # Normalize: strip trailing slashes
    root = root_path.rstrip("/")
    rel = file_path
    if rel.startswith(root):
        rel = rel[len(root) :]
    rel = rel.lstrip("/")

    # Strip .py extension
    if rel.endswith(".py"):
        rel = rel[:-3]

    # Replace path separators with dots
    fqn = rel.replace("/", ".")

    # __init__ -> package name (strip trailing .__init__)
    if fqn.endswith(".__init__"):
        fqn = fqn[: -len(".__init__")]
    elif fqn == "__init__":
        fqn = "__init__"

    return fqn


def _node_text(node: Node, source: bytes) -> str:
    """Extract the source text for a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _walk_tree(node: Node, node_type: str) -> list[Node]:
    """Recursively find all descendant nodes of the given type."""
    results: list[Node] = []
    if node.type == node_type:
        results.append(node)
    for child in node.children:
        results.extend(_walk_tree(child, node_type))
    return results


def _compute_loc(node: Node) -> int:
    """Compute lines of code for a tree-sitter node."""
    return node.end_point[0] - node.start_point[0] + 1


_COMPLEXITY_NODE_TYPES: set[str] = {
    "if_statement",
    "elif_clause",
    "for_statement",
    "while_statement",
    "except_clause",
    "with_statement",
    "conditional_expression",
}


def _compute_complexity(node: Node) -> int:
    """Compute cyclomatic complexity for a function body."""
    complexity = 1

    def _visit(n: Node) -> None:
        nonlocal complexity
        if n.type in _COMPLEXITY_NODE_TYPES:
            complexity += 1
        elif n.type == "boolean_operator":
            complexity += 1
        for child in n.children:
            _visit(child)

    body = node.child_by_field_name("body")
    if body is not None:
        _visit(body)
    return complexity


class PythonExtractor:
    """Extracts graph nodes and edges from Python source using tree-sitter."""

    def __init__(self) -> None:
        self._parser = Parser(PY_LANGUAGE)

    def extract(
        self,
        source: bytes,
        file_path: str,
        root_path: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Parse a Python source file and return nodes and edges.

        Args:
            source: Raw bytes of the Python source file.
            file_path: Absolute path to the file.
            root_path: Absolute path to the project root.

        Returns:
            Tuple of (nodes, edges).
        """
        logger.debug("python_extract_start", file_path=file_path)
        tree = self._parser.parse(source)
        module_fqn = _derive_module_fqn(file_path, root_path)
        module_name = module_fqn.rsplit(".", 1)[-1] if "." in module_fqn else module_fqn

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # Extract children first — MODULE is only created if the file has content
        self._extract_imports(tree, source, module_fqn, nodes, edges)
        self._extract_classes(tree, source, file_path, module_fqn, nodes, edges)
        self._extract_module_functions(
            tree, source, file_path, module_fqn, nodes, edges
        )
        self._extract_module_fields(tree, source, file_path, module_fqn, nodes, edges)
        self._extract_call_edges(tree, source, module_fqn, nodes, edges)
        self._extract_sql_strings(tree, source, module_fqn, nodes, edges)

        # Only create MODULE node if the file produced at least one child
        # (class, function, module-level field, etc.).  Empty __init__.py files
        # without any declarations don't need MODULE nodes.
        has_children = any(
            n.kind
            in (NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.FUNCTION, NodeKind.FIELD)
            for n in nodes
        )
        if has_children:
            module_node = GraphNode(
                fqn=module_fqn,
                name=module_name,
                kind=NodeKind.MODULE,
                language="python",
                path=file_path,
                line=1,
            )
            nodes.append(module_node)

        logger.debug(
            "python_extract_done",
            file_path=file_path,
            nodes=len(nodes),
            edges=len(edges),
        )
        return nodes, edges

    # ── Imports ──────────────────────────────────────────────────

    def _extract_imports(
        self,
        tree: Tree,
        source: bytes,
        module_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract import statements and create IMPORTS edges."""
        root = tree.root_node

        for child in root.children:
            if child.type == "import_statement":
                # import X, import X.Y, import X as Z
                for name_node in child.children:
                    if name_node.type == "dotted_name":
                        target = _node_text(name_node, source)
                        edges.append(
                            GraphEdge(
                                source_fqn=module_fqn,
                                target_fqn=target,
                                kind=EdgeKind.IMPORTS,
                            )
                        )
                    elif name_node.type == "aliased_import":
                        dotted = name_node.child_by_field_name("name")
                        if dotted:
                            target = _node_text(dotted, source)
                            edges.append(
                                GraphEdge(
                                    source_fqn=module_fqn,
                                    target_fqn=target,
                                    kind=EdgeKind.IMPORTS,
                                )
                            )

            elif child.type == "import_from_statement":
                # from X import Y, from X import Y as Z
                module_name_node = child.child_by_field_name("module_name")
                if module_name_node is None:
                    # Might be a relative import: iterate to find dotted_name
                    for c in child.children:
                        if c.type == "dotted_name":
                            module_name_node = c
                            break
                        elif c.type == "relative_import":
                            # from . import something or from .pkg import something
                            inner = None
                            for rc in c.children:
                                if rc.type == "dotted_name":
                                    inner = rc
                                    break
                            if inner:
                                module_name_node = inner
                            break

                if module_name_node:
                    target_module = _node_text(module_name_node, source)
                    edges.append(
                        GraphEdge(
                            source_fqn=module_fqn,
                            target_fqn=target_module,
                            kind=EdgeKind.IMPORTS,
                        )
                    )

    # ── Classes ──────────────────────────────────────────────────

    def _extract_classes(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        module_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract class definitions, base classes, methods, and fields."""
        # Find all class_definition nodes by walking the tree
        all_classes = _walk_tree(tree.root_node, "class_definition")

        for class_node in all_classes:
            # Only extract top-level and first-level nested classes
            parent = class_node.parent
            if parent and parent.type == "block":
                grandparent = parent.parent
                if grandparent and grandparent.type == "class_definition":
                    # Nested class -- compute FQN relative to outer class
                    outer_name_node = grandparent.child_by_field_name("name")
                    if outer_name_node:
                        outer_name = _node_text(outer_name_node, source)
                        self._process_class(
                            class_node,
                            source,
                            file_path,
                            f"{module_fqn}.{outer_name}",
                            nodes,
                            edges,
                        )
                        continue
                elif grandparent and grandparent.type not in (
                    "module",
                    "class_definition",
                    "if_statement",
                    "try_statement",
                ):
                    # Inside a function or other non-class scope -- skip
                    continue

            self._process_class(class_node, source, file_path, module_fqn, nodes, edges)

    def _process_class(
        self,
        class_node: Node,
        source: bytes,
        file_path: str,
        parent_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Process a single class_definition node."""
        name_node = class_node.child_by_field_name("name")
        if name_node is None:
            return
        class_name = _node_text(name_node, source)
        class_fqn = f"{parent_fqn}.{class_name}"

        # Decorators
        decorators = self._get_decorators(class_node, source)

        class_graph_node = GraphNode(
            fqn=class_fqn,
            name=class_name,
            kind=NodeKind.CLASS,
            language="python",
            path=file_path,
            line=class_node.start_point[0] + 1,
            end_line=class_node.end_point[0] + 1,
            loc=_compute_loc(class_node),
            properties={"annotations": decorators} if decorators else {},
        )
        nodes.append(class_graph_node)

        # CONTAINS edge: module/parent -> class
        edges.append(
            GraphEdge(
                source_fqn=parent_fqn,
                target_fqn=class_fqn,
                kind=EdgeKind.CONTAINS,
            )
        )

        # Base classes -> INHERITS edges
        superclasses_node = class_node.child_by_field_name("superclasses")
        if superclasses_node:
            for arg_child in superclasses_node.children:
                if arg_child.type in ("identifier", "attribute"):
                    base_name = _node_text(arg_child, source)
                    edges.append(
                        GraphEdge(
                            source_fqn=class_fqn,
                            target_fqn=base_name,
                            kind=EdgeKind.INHERITS,
                            confidence=Confidence.LOW,
                            evidence="tree-sitter",
                        )
                    )

        # Body: methods and class-level fields
        body_node = class_node.child_by_field_name("body")
        if body_node:
            self._extract_methods(body_node, source, file_path, class_fqn, nodes, edges)
            self._extract_class_body_fields(
                body_node, source, file_path, class_fqn, nodes, edges
            )

    # ── Methods ──────────────────────────────────────────────────

    def _extract_methods(
        self,
        body_node: Node,
        source: bytes,
        file_path: str,
        class_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract method definitions from a class body."""
        for child in body_node.children:
            if child.type == "decorated_definition":
                # The actual function_definition is inside
                for sub in child.children:
                    if sub.type == "function_definition":
                        self._process_function(
                            sub,
                            source,
                            file_path,
                            class_fqn,
                            nodes,
                            edges,
                            is_method=True,
                            decorator_parent=child,
                        )
                        break
            elif child.type == "function_definition":
                self._process_function(
                    child,
                    source,
                    file_path,
                    class_fqn,
                    nodes,
                    edges,
                    is_method=True,
                )

    # ── Module-level functions ───────────────────────────────────

    def _extract_module_functions(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        module_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract top-level function definitions (not methods)."""
        root = tree.root_node
        for child in root.children:
            if child.type == "decorated_definition":
                for sub in child.children:
                    if sub.type == "function_definition":
                        self._process_function(
                            sub,
                            source,
                            file_path,
                            module_fqn,
                            nodes,
                            edges,
                            is_method=False,
                            decorator_parent=child,
                        )
                        break
            elif child.type == "function_definition":
                self._process_function(
                    child,
                    source,
                    file_path,
                    module_fqn,
                    nodes,
                    edges,
                    is_method=False,
                )

    def _process_function(
        self,
        func_node: Node,
        source: bytes,
        file_path: str,
        parent_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        *,
        is_method: bool = False,
        decorator_parent: Node | None = None,
    ) -> None:
        """Process a single function_definition node."""
        name_node = func_node.child_by_field_name("name")
        if name_node is None:
            return
        func_name = _node_text(name_node, source)
        func_fqn = f"{parent_fqn}.{func_name}"

        # Parameters with type annotations
        params = self._extract_parameters(func_node, source, is_method)

        # Return type
        return_type = None
        return_type_node = func_node.child_by_field_name("return_type")
        if return_type_node:
            return_type = _node_text(return_type_node, source)

        # Decorators
        deco_source = decorator_parent if decorator_parent else func_node
        decorators = self._get_decorators(deco_source, source)

        properties: dict[str, Any] = {}
        if decorators:
            properties["annotations"] = decorators
        if params:
            properties["params"] = params
        if return_type:
            properties["return_type"] = return_type
        if is_method:
            properties["is_method"] = True

        func_graph_node = GraphNode(
            fqn=func_fqn,
            name=func_name,
            kind=NodeKind.FUNCTION,
            language="python",
            path=file_path,
            line=func_node.start_point[0] + 1,
            end_line=func_node.end_point[0] + 1,
            loc=_compute_loc(func_node),
            complexity=_compute_complexity(func_node),
            properties=properties,
        )
        nodes.append(func_graph_node)

        # CONTAINS edge: parent -> function
        edges.append(
            GraphEdge(
                source_fqn=parent_fqn,
                target_fqn=func_fqn,
                kind=EdgeKind.CONTAINS,
            )
        )

        # Extract self.x = ... fields from __init__
        if is_method and func_name == "__init__":
            self._extract_init_fields(
                func_node, source, file_path, parent_fqn, nodes, edges
            )

    # ── Parameters ───────────────────────────────────────────────

    def _extract_parameters(
        self, func_node: Node, source: bytes, is_method: bool
    ) -> list[dict[str, str]]:
        """Extract parameter names and type annotations from a function."""
        params_node = func_node.child_by_field_name("parameters")
        if params_node is None:
            return []

        params: list[dict[str, str]] = []
        skip_first = is_method  # skip 'self' or 'cls'

        for child in params_node.children:
            if child.type == "identifier":
                if skip_first:
                    skip_first = False
                    continue
                params.append({"name": _node_text(child, source)})

            elif child.type == "typed_parameter":
                if skip_first:
                    skip_first = False
                    continue
                pname_node = child.children[0] if child.children else None
                ptype_node = child.child_by_field_name("type")
                entry: dict[str, str] = {}
                if pname_node:
                    entry["name"] = _node_text(pname_node, source)
                if ptype_node:
                    entry["type"] = _node_text(ptype_node, source)
                params.append(entry)

            elif child.type == "default_parameter":
                if skip_first:
                    skip_first = False
                    continue
                pname_node = child.child_by_field_name("name")
                entry = {}
                if pname_node:
                    entry["name"] = _node_text(pname_node, source)
                params.append(entry)

            elif child.type == "typed_default_parameter":
                if skip_first:
                    skip_first = False
                    continue
                pname_node = child.child_by_field_name("name")
                ptype_node = child.child_by_field_name("type")
                entry = {}
                if pname_node:
                    entry["name"] = _node_text(pname_node, source)
                if ptype_node:
                    entry["type"] = _node_text(ptype_node, source)
                params.append(entry)

            elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                # *args, **kwargs
                for sub in child.children:
                    if sub.type == "identifier":
                        params.append({"name": _node_text(sub, source)})

        return params

    # ── Fields ───────────────────────────────────────────────────

    def _extract_init_fields(
        self,
        func_node: Node,
        source: bytes,
        file_path: str,
        class_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract self.x = ... assignments from __init__ as FIELD nodes."""
        body = func_node.child_by_field_name("body")
        if body is None:
            return

        seen_fields: set[str] = set()
        self._walk_for_self_assignments(
            body, source, file_path, class_fqn, nodes, edges, seen_fields
        )

    def _walk_for_self_assignments(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        class_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen: set[str],
    ) -> None:
        """Recursively walk looking for self.attr = ... patterns."""
        for child in node.children:
            if child.type == "expression_statement":
                expr = child.children[0] if child.children else None
                if expr and expr.type == "assignment":
                    left = expr.child_by_field_name("left")
                    if left and left.type == "attribute":
                        obj = left.child_by_field_name("object")
                        attr = left.child_by_field_name("attribute")
                        if obj and attr and _node_text(obj, source) == "self":
                            field_name = _node_text(attr, source)
                            if field_name not in seen:
                                seen.add(field_name)
                                field_fqn = f"{class_fqn}.{field_name}"
                                nodes.append(
                                    GraphNode(
                                        fqn=field_fqn,
                                        name=field_name,
                                        kind=NodeKind.FIELD,
                                        language="python",
                                        path=file_path,
                                        line=child.start_point[0] + 1,
                                    )
                                )
                                edges.append(
                                    GraphEdge(
                                        source_fqn=class_fqn,
                                        target_fqn=field_fqn,
                                        kind=EdgeKind.CONTAINS,
                                    )
                                )
            # Recurse into blocks (if/for/try inside __init__)
            elif child.type in (
                "block",
                "if_statement",
                "for_statement",
                "try_statement",
                "with_statement",
            ):
                self._walk_for_self_assignments(
                    child, source, file_path, class_fqn, nodes, edges, seen
                )

    def _extract_module_fields(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        module_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract module-level (top-level) variable assignments as FIELD nodes.

        Walks only the root node's direct children — NOT class bodies or
        function bodies. Handles plain and annotated assignments::

            INSTALLED_APPS = ["auth", "admin"]
            DEBUG: bool = False
            DATABASES = {"default": {...}}

        The FIELD's ``properties["value"]`` is set to the verbatim source text
        of the assignment's right-hand side, so downstream plugins (e.g.
        DjangoSettingsPlugin) can read raw config values from the graph.

        Dunder assignments (``__all__``, ``__version__``, etc.) are skipped —
        they aren't useful as CONFIG_ENTRYs and would add noise.
        """
        root = tree.root_node
        for child in root.children:
            if child.type != "expression_statement":
                continue
            if not child.children:
                continue
            expr = child.children[0]
            if expr.type != "assignment":
                continue
            left = expr.child_by_field_name("left")
            if left is None or left.type != "identifier":
                # Skip tuple/subscript/attribute targets (a,b = ..., x[0] = ...).
                continue
            right = expr.child_by_field_name("right")
            if right is None:
                # e.g. bare type annotation: X: int (no RHS value)
                continue
            if right.type == "assignment":
                # Chained assignment (A = B = 42) — value is not a literal RHS; skip.
                continue

            field_name = _node_text(left, source)

            # Skip dunder names — noise for config-entry consumers.
            if field_name.startswith("__") and field_name.endswith("__"):
                continue

            field_fqn = f"{module_fqn}.{field_name}"
            value_text = _node_text(right, source)
            props: dict[str, Any] = {"value": value_text}

            type_node = expr.child_by_field_name("type")
            if type_node is not None:
                annotation = _node_text(type_node, source)
                # Store under both keys: ``type_annotation`` for legacy
                # Python-extractor consumers and ``type`` for cross-language
                # plugin consumers (Spring/JPA/Pydantic etc. all read ``type``).
                props["type_annotation"] = annotation
                props["type"] = annotation

            nodes.append(
                GraphNode(
                    fqn=field_fqn,
                    name=field_name,
                    kind=NodeKind.FIELD,
                    language="python",
                    path=file_path,
                    line=child.start_point[0] + 1,
                    properties=props,
                )
            )
            edges.append(
                GraphEdge(
                    source_fqn=module_fqn,
                    target_fqn=field_fqn,
                    kind=EdgeKind.CONTAINS,
                )
            )

    def _extract_class_body_fields(
        self,
        body_node: Node,
        source: bytes,
        file_path: str,
        class_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract class-level variable assignments as FIELD nodes.

        Example: ``name: str = "default"`` or ``count = 0`` in a class body.
        """
        for child in body_node.children:
            field_name: str | None = None
            field_type: str | None = None
            field_value: str | None = None
            line = child.start_point[0] + 1

            if child.type == "expression_statement":
                expr = child.children[0] if child.children else None
                if expr and expr.type == "assignment":
                    left = expr.child_by_field_name("left")
                    if left and left.type == "identifier":
                        field_name = _node_text(left, source)
                    # Capture RHS value (e.g. `mapped_column(...)`, string literal).
                    right = expr.child_by_field_name("right")
                    if right is not None:
                        field_value = _node_text(right, source)
                    # Capture type annotation from `x: T = value`.
                    type_node = expr.child_by_field_name("type")
                    if type_node:
                        field_type = _node_text(type_node, source)
                elif expr and expr.type == "type":
                    # annotated variable without assignment: x: int
                    for sub in expr.children:
                        if sub.type == "identifier":
                            field_name = _node_text(sub, source)
                            break
                    type_node = expr.child_by_field_name("type")
                    if type_node:
                        field_type = _node_text(type_node, source)

            elif child.type == "type_alias_statement":
                # type X = ... (Python 3.12)
                continue

            if field_name:
                field_fqn = f"{class_fqn}.{field_name}"
                props: dict[str, Any] = {}
                if field_type:
                    # See note above: dual-key for legacy ``type_annotation``
                    # tests and the cross-language ``type`` convention.
                    props["type_annotation"] = field_type
                    props["type"] = field_type
                if field_value is not None:
                    props["value"] = field_value
                nodes.append(
                    GraphNode(
                        fqn=field_fqn,
                        name=field_name,
                        kind=NodeKind.FIELD,
                        language="python",
                        path=file_path,
                        line=line,
                        properties=props,
                    )
                )
                edges.append(
                    GraphEdge(
                        source_fqn=class_fqn,
                        target_fqn=field_fqn,
                        kind=EdgeKind.CONTAINS,
                    )
                )

    # ── Calls ────────────────────────────────────────────────────

    def _extract_call_edges(
        self,
        tree: Tree,
        source: bytes,
        module_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract function/method call edges from the entire file.

        Walks all call expressions and creates CALLS edges with LOW confidence
        (unresolved -- SCIP will upgrade these later).
        """
        # Walk tree to find all call expressions
        self._walk_calls(tree.root_node, source, module_fqn, nodes, edges)

    def _walk_calls(
        self,
        node: Node,
        source: bytes,
        module_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Recursively walk looking for call expressions."""
        if node.type == "call":
            func_part = node.child_by_field_name("function")
            if func_part:
                callee_text = _node_text(func_part, source)
                # Find enclosing function to determine caller FQN
                caller_fqn = self._find_enclosing_function_fqn(
                    node, source, module_fqn, nodes
                )
                if caller_fqn:
                    edges.append(
                        GraphEdge(
                            source_fqn=caller_fqn,
                            target_fqn=callee_text,
                            kind=EdgeKind.CALLS,
                            confidence=Confidence.LOW,
                            evidence="tree-sitter",
                            properties={"line": node.start_point[0] + 1},
                        )
                    )

        for child in node.children:
            self._walk_calls(child, source, module_fqn, nodes, edges)

    def _find_enclosing_function_fqn(
        self,
        node: Node,
        source: bytes,
        module_fqn: str,
        nodes: list[GraphNode],
    ) -> str | None:
        """Walk up the tree to find the enclosing function and return its FQN."""
        current = node.parent
        fqn_parts: list[str] = []

        while current is not None:
            if current.type == "function_definition":
                name_node = current.child_by_field_name("name")
                if name_node:
                    fqn_parts.insert(0, _node_text(name_node, source))
            elif current.type == "class_definition":
                name_node = current.child_by_field_name("name")
                if name_node:
                    fqn_parts.insert(0, _node_text(name_node, source))
            current = current.parent

        if not fqn_parts:
            # Call at module level -- caller is the module
            return module_fqn

        return f"{module_fqn}.{'.'.join(fqn_parts)}"

    # ── SQL string detection ─────────────────────────────────────

    def _extract_sql_strings(
        self,
        tree: Tree,
        source: bytes,
        module_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Tag string literals that look like SQL queries."""
        # Walk tree to find all string nodes instead of using query API
        string_nodes = _walk_tree(tree.root_node, "string")

        for str_node in string_nodes:
            text = _node_text(str_node, source)
            # Strip quotes
            stripped = text.strip("\"'").strip()
            # Also handle triple-quoted strings
            for prefix in ('"""', "'''", 'f"""', "f'''", 'r"""', "r'''"):
                if stripped.startswith(prefix[1:]):
                    stripped = stripped[len(prefix) - 1 :]
                    break
            for suffix in ('"""', "'''"):
                if stripped.endswith(suffix):
                    stripped = stripped[: -len(suffix)]
                    break

            if _looks_like_sql(stripped):
                # Find which function contains this string
                enclosing = self._find_enclosing_function_fqn(
                    str_node, source, module_fqn, nodes
                )
                if enclosing:
                    # Store as a property tag -- downstream sqlglot stage will parse
                    for n in nodes:
                        if n.fqn == enclosing and n.kind == NodeKind.FUNCTION:
                            sql_strings = n.properties.setdefault("sql_strings", [])
                            sql_strings.append(
                                {
                                    "text": stripped,
                                    "line": str_node.start_point[0] + 1,
                                }
                            )
                            break

    # ── Decorators ───────────────────────────────────────────────

    def _get_decorators(self, node: Node, source: bytes) -> list[str]:
        """Extract decorator strings from a class/function definition.

        Handles both direct decorators on the node and decorators from a
        decorated_definition parent.
        """
        decorators: list[str] = []

        # Check if node is wrapped in decorated_definition
        parent = node.parent
        if parent and parent.type == "decorated_definition":
            for child in parent.children:
                if child.type == "decorator":
                    deco_text = _node_text(child, source)
                    # Strip leading @
                    if deco_text.startswith("@"):
                        deco_text = deco_text[1:]
                    decorators.append(deco_text)
        else:
            # Some tree-sitter versions put decorators as children of the node
            for child in node.children:
                if child.type == "decorator":
                    deco_text = _node_text(child, source)
                    if deco_text.startswith("@"):
                        deco_text = deco_text[1:]
                    decorators.append(deco_text)

        return decorators


# Register at module level
register_extractor("python", PythonExtractor())
