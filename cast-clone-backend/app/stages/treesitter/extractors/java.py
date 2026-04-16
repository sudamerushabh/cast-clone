"""Java tree-sitter extractor.

Parses a single Java source file and produces GraphNode + GraphEdge lists
covering: packages, imports, classes, interfaces, methods, constructors,
fields, method calls, object creation, annotations, and SQL-tagged strings.
"""
from __future__ import annotations

import re
from typing import Any

import structlog
import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.treesitter.extractors import register_extractor

logger = structlog.get_logger(__name__)

JAVA_LANGUAGE = Language(tsjava.language())

# SQL keyword pattern for tagging strings
_SQL_PATTERN = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|CREATE|ALTER|DROP)\b", re.IGNORECASE
)


def _node_text(node: Node) -> str:
    """Extract UTF-8 text from a tree-sitter node."""
    return node.text.decode("utf-8")


def _compute_loc(node: Node) -> int:
    """Compute lines of code for a tree-sitter node (end_line - start_line + 1)."""
    return node.end_point[0] - node.start_point[0] + 1


# Java AST node types that contribute to cyclomatic complexity.
_COMPLEXITY_NODE_TYPES: set[str] = {
    "if_statement",
    "for_statement",
    "enhanced_for_statement",
    "while_statement",
    "do_statement",
    "catch_clause",
    "ternary_expression",
}


def _compute_complexity(node: Node) -> int:
    """Compute cyclomatic complexity for a method/constructor body.

    Starts at 1 (base path) and increments for each branching construct:
    if, for, enhanced_for, while, do, catch, ternary, case label, &&, ||.
    """
    complexity = 1

    def _visit(n: Node) -> None:
        nonlocal complexity
        if n.type in _COMPLEXITY_NODE_TYPES:
            complexity += 1
        elif n.type == "switch_block_statement_group":
            # Each case label adds a branch (but we count the group once)
            complexity += 1
        elif n.type == "binary_expression":
            # Count && and || operators
            op_node = n.child_by_field_name("operator")
            if op_node is not None and _node_text(op_node) in ("&&", "||"):
                complexity += 1
        for child in n.children:
            _visit(child)

    body = node.child_by_field_name("body")
    if body is not None:
        _visit(body)
    return complexity


def _get_modifiers(node: Node) -> list[str]:
    """Extract modifier keywords from a declaration node."""
    modifiers: list[str] = []
    for child in node.children:
        if child.type == "modifiers":
            for mod_child in child.children:
                if mod_child.type in (
                    "public",
                    "private",
                    "protected",
                    "static",
                    "final",
                    "abstract",
                    "synchronized",
                    "native",
                    "transient",
                    "volatile",
                ):
                    modifiers.append(mod_child.type)
    return modifiers


def _get_annotations(node: Node) -> list[str]:
    """Extract annotation names from a declaration node's modifiers."""
    annotations: list[str] = []
    for child in node.children:
        if child.type == "modifiers":
            for mod_child in child.children:
                if mod_child.type in ("annotation", "marker_annotation"):
                    name_node = mod_child.child_by_field_name("name")
                    if name_node is not None:
                        annotations.append(_node_text(name_node))
    return annotations


def _extract_annotation_value(val_node: Node) -> str | list[str] | None:
    """Extract a value from an annotation element_value_pair or bare argument.

    Handles string literals, boolean/integer/enum literals, and array
    initializers (returning a list of strings for arrays).
    """
    if val_node.type == "string_literal":
        text = _node_text(val_node)
        if text.startswith('"') and text.endswith('"'):
            return text[1:-1]
        return text
    if val_node.type == "element_value_array_initializer":
        # e.g., topics = {"orders", "payments"}
        values: list[str] = []
        for child in val_node.children:
            extracted = _extract_annotation_value(child)
            if isinstance(extracted, str):
                values.append(extracted)
            elif isinstance(extracted, list):
                values.extend(extracted)
        return values if values else None
    if val_node.type in (
        "true", "false", "decimal_integer_literal",
        "decimal_floating_point_literal", "identifier",
        "field_access", "scoped_identifier",
    ):
        return _node_text(val_node)
    # Fallback: return raw text for other expression types
    text = _node_text(val_node).strip()
    return text if text else None


def _get_annotation_args(node: Node) -> dict[str, str]:
    """Extract primary string argument for each annotation.

    Returns a dict mapping annotation name -> primary string value.
    This is backward-compatible: always returns strings.

    Example: @RequestMapping("/api") -> {"RequestMapping": "/api"}
    For multi-param, extracts "value" or first string:
        @Column(name="user_id") -> {"Column": "user_id"}

    Marker annotations (@Override) are omitted.
    """
    args: dict[str, str] = {}
    for child in node.children:
        if child.type == "modifiers":
            for mod_child in child.children:
                if mod_child.type == "annotation":
                    name_node = mod_child.child_by_field_name("name")
                    if name_node is None:
                        continue
                    ann_name = _node_text(name_node)
                    args_node = mod_child.child_by_field_name("arguments")
                    if args_node is None:
                        continue

                    bare_value: str | None = None
                    first_pair_value: str | None = None

                    for arg_child in args_node.children:
                        if arg_child.type == "string_literal":
                            text = _node_text(arg_child)
                            if text.startswith('"') and text.endswith('"'):
                                bare_value = text[1:-1]
                        elif arg_child.type == "element_value_pair":
                            key_node = arg_child.child_by_field_name("key")
                            val_node = arg_child.child_by_field_name("value")
                            if key_node and val_node:
                                k = _node_text(key_node)
                                v = _extract_annotation_value(val_node)
                                if k in ("value", "path") and isinstance(v, str):
                                    bare_value = v
                                elif first_pair_value is None and isinstance(v, str):
                                    first_pair_value = v

                    value = bare_value or first_pair_value
                    if value is not None:
                        args[ann_name] = value
    return args


AnnotationParams = dict[str, str | list[str] | None]


def _get_annotation_params(
    node: Node,
) -> dict[str, AnnotationParams]:
    """Extract ALL named parameters for each annotation.

    Returns a dict mapping annotation name -> dict of all params.

    Example:
        @KafkaListener(topics={"a","b"}, groupId="g")
        -> {"KafkaListener": {"topics": ["a", "b"], "groupId": "g"}}

        @Scheduled(fixedRate=5000)
        -> {"Scheduled": {"fixedRate": "5000"}}

        @Column(name="user_id", nullable=false)
        -> {"Column": {"name": "user_id", "nullable": "false"}}

    Single-value annotations store the value under the "value" key:
        @RequestMapping("/api")
        -> {"RequestMapping": {"value": "/api"}}
    """
    result: dict[str, AnnotationParams] = {}
    for child in node.children:
        if child.type == "modifiers":
            for mod_child in child.children:
                if mod_child.type == "annotation":
                    name_node = mod_child.child_by_field_name("name")
                    if name_node is None:
                        continue
                    ann_name = _node_text(name_node)
                    args_node = mod_child.child_by_field_name("arguments")
                    if args_node is None:
                        continue

                    params: AnnotationParams = {}
                    for arg_child in args_node.children:
                        if arg_child.type == "element_value_pair":
                            key_node = arg_child.child_by_field_name("key")
                            val_node = arg_child.child_by_field_name("value")
                            if key_node and val_node:
                                extracted = _extract_annotation_value(val_node)
                                if extracted is not None:
                                    params[_node_text(key_node)] = extracted
                        elif arg_child.type == "string_literal":
                            text = _node_text(arg_child)
                            if text.startswith('"') and text.endswith('"'):
                                params["value"] = text[1:-1]

                    if params:
                        result[ann_name] = params
    return result


def _visibility_from_modifiers(modifiers: list[str]) -> str:
    """Determine visibility from modifier keywords."""
    if "public" in modifiers:
        return "public"
    if "private" in modifiers:
        return "private"
    if "protected" in modifiers:
        return "protected"
    return "default"


def _parse_formal_parameters(params_node: Node) -> list[str]:
    """Parse formal_parameters node into list of 'Type name' strings."""
    params: list[str] = []
    for child in params_node.children:
        if child.type == "formal_parameter":
            type_node = child.child_by_field_name("type")
            name_node = child.child_by_field_name("name")
            if type_node is not None and name_node is not None:
                params.append(f"{_node_text(type_node)} {_node_text(name_node)}")
        elif child.type == "spread_parameter":
            # varargs: Type... name
            params.append(_node_text(child))
    return params


def _find_enclosing_class(node: Node) -> Node | None:
    """Walk up the tree to find the enclosing class/interface/enum declaration."""
    current = node.parent
    while current is not None:
        if current.type in (
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
        ):
            return current
        current = current.parent
    return None


def _find_enclosing_method(node: Node) -> Node | None:
    """Walk up the tree to find the enclosing method or constructor declaration."""
    current = node.parent
    while current is not None:
        if current.type in ("method_declaration", "constructor_declaration"):
            return current
        current = current.parent
    return None


def _class_fqn(package: str, class_node: Node) -> str:
    """Build FQN for a class, handling nested classes."""
    name_node = class_node.child_by_field_name("name")
    name = _node_text(name_node) if name_node is not None else "Unknown"

    # Check for nesting
    parts = [name]
    parent = class_node.parent
    while parent is not None:
        if parent.type in (
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
        ):
            parent_name = parent.child_by_field_name("name")
            if parent_name is not None:
                parts.insert(0, _node_text(parent_name))
        parent = parent.parent

    class_name = ".".join(parts)
    if package:
        return f"{package}.{class_name}"
    return class_name


def _walk_all(root: Node, node_type: str) -> list[Node]:
    """Recursively collect all descendant nodes of a given type."""
    result: list[Node] = []

    def _visit(node: Node) -> None:
        if node.type == node_type:
            result.append(node)
        for child in node.children:
            _visit(child)

    _visit(root)
    return result


def _strip_generics(type_str: str) -> str:
    """Strip generic type parameters: 'List<User>' -> 'List'."""
    idx = type_str.find("<")
    return type_str[:idx] if idx != -1 else type_str


def _resolve_receiver_type(
    receiver_text: str,
    field_type_map: dict[str, str],
    local_var_map: dict[str, str],
    import_map: dict[str, str],
    package: str = "",
) -> str | None:
    """Resolve a receiver expression to a fully-qualified type.

    Looks up the receiver in local variables, then fields, then checks
    if it's a static call on a class name. Resolves through import_map,
    falling back to same-package qualification for unimported types.
    Returns None if unresolvable.
    """
    name = receiver_text
    # Strip 'this.' prefix
    if name.startswith("this."):
        name = name[5:]

    # Look up in local vars first (narrower scope), then fields
    raw_type = local_var_map.get(name) or field_type_map.get(name)

    if raw_type is None:
        # Check if receiver starts with uppercase (static call on class name)
        if name and name[0].isupper():
            raw_type = name
        else:
            return None

    raw_type = _strip_generics(raw_type)

    # Resolve through import_map to get full FQN
    if raw_type in import_map:
        return import_map[raw_type]

    # If not in imports but looks like a simple class name, qualify with package
    if "." not in raw_type and package and raw_type[0:1].isupper():
        return f"{package}.{raw_type}"

    return raw_type


class JavaExtractor:
    """Extracts graph nodes and edges from a Java source file."""

    def __init__(self) -> None:
        self._parser = Parser(JAVA_LANGUAGE)

    def extract(
        self,
        source: bytes,
        file_path: str,
        root_path: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Parse a Java source file and return (nodes, edges).

        Args:
            source: Raw bytes of the Java source file.
            file_path: Relative or absolute path to the file (stored on nodes).
            root_path: Root path of the project (unused for now, reserved for future).

        Returns:
            Tuple of (list[GraphNode], list[GraphEdge]).
        """
        logger.debug("java_extract_start", file_path=file_path)
        tree = self._parser.parse(source)
        root = tree.root_node

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # Step 1: Parse package
        package = self._extract_package(root)

        # Step 2: Parse imports
        import_map = self._extract_imports(root, package, file_path, edges)

        # Step 3: Parse classes
        self._extract_classes(root, package, file_path, nodes, edges)

        # Step 4: Parse interfaces
        self._extract_interfaces(root, package, file_path, nodes, edges)

        # Step 5: Parse methods
        self._extract_methods(root, package, file_path, nodes, edges)

        # Step 6: Parse constructors
        self._extract_constructors(root, package, file_path, nodes, edges)

        # Step 7: Parse fields
        self._extract_fields(root, package, file_path, nodes, edges)

        # Build field_type_map for method call resolution
        field_type_map: dict[str, str] = {}
        for node in nodes:
            if node.kind == NodeKind.FIELD:
                field_type = node.properties.get("type", "unknown")
                if field_type != "unknown":
                    field_type_map[node.name] = _strip_generics(field_type)

        # Step 8: Parse method calls
        self._extract_method_calls(
            root, package, file_path, import_map, field_type_map, edges
        )

        # Step 9: Parse object creation
        self._extract_object_creation(
            root, package, file_path, import_map, edges
        )

        # Step 10: Tag SQL strings
        self._tag_sql_strings(root, package, nodes)

        # Step 10b: Extract type references (DEPENDS_ON edges)
        self._extract_type_references(root, package, import_map, edges)

        # Step 11: Create MODULE node for the package and CONTAINS edges
        if package:
            module_name = package.rsplit(".", 1)[-1]
            module_node = GraphNode(
                fqn=package,
                name=module_name,
                kind=NodeKind.MODULE,
                language="java",
                path=file_path,
                line=1,
            )
            nodes.append(module_node)

            # Add CONTAINS edges from module to top-level classes/interfaces
            for node in nodes:
                if node.kind in (NodeKind.CLASS, NodeKind.INTERFACE) and node.fqn.startswith(package + "."):
                    # Only direct children (no nested dots after the package prefix)
                    relative = node.fqn[len(package) + 1:]
                    if "." not in relative:
                        edges.append(
                            GraphEdge(
                                source_fqn=package,
                                target_fqn=node.fqn,
                                kind=EdgeKind.CONTAINS,
                                evidence="tree-sitter",
                            )
                        )

        logger.debug(
            "java_extract_done",
            file_path=file_path,
            nodes=len(nodes),
            edges=len(edges),
        )
        return nodes, edges

    # ── Private extraction methods ───────────────────────────────────────

    def _extract_package(self, root: Node) -> str:
        """Extract the package name from the compilation unit."""
        for child in root.children:
            if child.type == "package_declaration":
                # The scoped_identifier child holds the package name
                for sub in child.children:
                    if sub.type == "scoped_identifier":
                        return _node_text(sub)
                    if sub.type == "identifier":
                        return _node_text(sub)
        return ""

    def _extract_imports(
        self,
        root: Node,
        package: str,
        file_path: str,
        edges: list[GraphEdge],
    ) -> dict[str, str]:
        """Extract imports and return a short-name -> FQN map.

        Also emits IMPORTS edges from the file's package to each import target.
        """
        import_map: dict[str, str] = {}
        source_fqn = package if package else file_path

        for child in root.children:
            if child.type != "import_declaration":
                continue

            # Check if wildcard import (has asterisk child)
            has_asterisk = any(c.type == "asterisk" for c in child.children)

            # Get the scoped_identifier
            scoped = None
            for sub in child.children:
                if sub.type == "scoped_identifier":
                    scoped = sub
                    break

            if scoped is None:
                continue

            import_path = _node_text(scoped)

            if has_asterisk:
                # Wildcard import: com.example.repo.*
                full_path = f"{import_path}.*"
                import_map[full_path] = full_path
            else:
                # Specific import: short name is last segment
                full_path = import_path
                short_name = import_path.rsplit(".", 1)[-1]
                import_map[short_name] = import_path

            edges.append(
                GraphEdge(
                    source_fqn=source_fqn,
                    target_fqn=full_path,
                    kind=EdgeKind.IMPORTS,
                    confidence=Confidence.HIGH,
                    evidence="tree-sitter",
                )
            )

        return import_map

    def _extract_classes(
        self,
        root: Node,
        package: str,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract class declarations into nodes and edges."""
        for class_node in _walk_all(root, "class_declaration"):
            name_node = class_node.child_by_field_name("name")
            if name_node is None:
                continue

            fqn = _class_fqn(package, class_node)
            name = _node_text(name_node)
            modifiers = _get_modifiers(class_node)
            annotations = _get_annotations(class_node)
            annotation_args = _get_annotation_args(class_node)
            annotation_params = _get_annotation_params(class_node)

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
                "is_abstract": "abstract" in modifiers,
            }
            if annotations:
                properties["annotations"] = annotations
            if annotation_args:
                properties["annotation_args"] = annotation_args
            if annotation_params:
                properties["annotation_params"] = annotation_params

            nodes.append(
                GraphNode(
                    fqn=fqn,
                    name=name,
                    kind=NodeKind.CLASS,
                    language="java",
                    path=file_path,
                    line=class_node.start_point[0] + 1,
                    end_line=class_node.end_point[0] + 1,
                    loc=_compute_loc(class_node),
                    properties=properties,
                )
            )

            # Superclass -> INHERITS edge
            superclass_node = class_node.child_by_field_name("superclass")
            if superclass_node is not None:
                for sc_child in superclass_node.children:
                    if sc_child.type == "type_identifier":
                        edges.append(
                            GraphEdge(
                                source_fqn=fqn,
                                target_fqn=_node_text(sc_child),
                                kind=EdgeKind.INHERITS,
                                confidence=Confidence.LOW,
                                evidence="tree-sitter",
                            )
                        )

            # Interfaces -> IMPLEMENTS edges
            interfaces_node = class_node.child_by_field_name("interfaces")
            if interfaces_node is not None:
                for iface_child in interfaces_node.children:
                    if iface_child.type == "type_list":
                        for type_node in iface_child.children:
                            if type_node.type == "type_identifier":
                                edges.append(
                                    GraphEdge(
                                        source_fqn=fqn,
                                        target_fqn=_node_text(type_node),
                                        kind=EdgeKind.IMPLEMENTS,
                                        confidence=Confidence.LOW,
                                        evidence="tree-sitter",
                                    )
                                )

    def _extract_interfaces(
        self,
        root: Node,
        package: str,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract interface declarations."""
        for iface_node in _walk_all(root, "interface_declaration"):
            name_node = iface_node.child_by_field_name("name")
            if name_node is None:
                continue

            fqn = _class_fqn(package, iface_node)
            name = _node_text(name_node)
            modifiers = _get_modifiers(iface_node)
            annotations = _get_annotations(iface_node)

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
            }
            if annotations:
                properties["annotations"] = annotations

            nodes.append(
                GraphNode(
                    fqn=fqn,
                    name=name,
                    kind=NodeKind.INTERFACE,
                    language="java",
                    path=file_path,
                    line=iface_node.start_point[0] + 1,
                    end_line=iface_node.end_point[0] + 1,
                    loc=_compute_loc(iface_node),
                    properties=properties,
                )
            )

            # Extended interfaces -> INHERITS edges
            # Interface extends uses extends_interfaces node
            for child in iface_node.children:
                if child.type == "extends_interfaces":
                    for sub in child.children:
                        if sub.type == "type_list":
                            for type_node in sub.children:
                                # Handle both plain type_identifier and
                                # generic_type (e.g., JpaRepository<Account, Long>)
                                if type_node.type == "type_identifier":
                                    target_name = _node_text(type_node)
                                elif type_node.type == "generic_type":
                                    ti = type_node.child_by_field_name("type") or next(
                                        (c for c in type_node.children
                                         if c.type == "type_identifier"), None
                                    )
                                    if ti is None:
                                        continue
                                    target_name = _node_text(ti)
                                else:
                                    continue
                                edges.append(
                                    GraphEdge(
                                        source_fqn=fqn,
                                        target_fqn=target_name,
                                        kind=EdgeKind.INHERITS,
                                        confidence=Confidence.LOW,
                                        evidence="tree-sitter",
                                    )
                                )

    def _extract_methods(
        self,
        root: Node,
        package: str,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract method declarations."""
        for method_node in _walk_all(root, "method_declaration"):
            name_node = method_node.child_by_field_name("name")
            if name_node is None:
                continue

            # Find enclosing class to build FQN
            enclosing = _find_enclosing_class(method_node)
            if enclosing is None:
                continue
            class_fqn_str = _class_fqn(package, enclosing)
            method_name = _node_text(name_node)
            fqn = f"{class_fqn_str}.{method_name}"

            modifiers = _get_modifiers(method_node)
            annotations = _get_annotations(method_node)
            annotation_args = _get_annotation_args(method_node)
            annotation_params = _get_annotation_params(method_node)

            # Return type
            type_node = method_node.child_by_field_name("type")
            return_type = _node_text(type_node) if type_node is not None else "void"

            # Parameters
            params_node = method_node.child_by_field_name("parameters")
            params = (
                _parse_formal_parameters(params_node)
                if params_node is not None
                else []
            )

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
                "return_type": return_type,
                "params": params,
            }
            if annotations:
                properties["annotations"] = annotations
            if annotation_args:
                properties["annotation_args"] = annotation_args
            if annotation_params:
                properties["annotation_params"] = annotation_params

            nodes.append(
                GraphNode(
                    fqn=fqn,
                    name=method_name,
                    kind=NodeKind.FUNCTION,
                    language="java",
                    path=file_path,
                    line=method_node.start_point[0] + 1,
                    end_line=method_node.end_point[0] + 1,
                    loc=_compute_loc(method_node),
                    complexity=_compute_complexity(method_node),
                    properties=properties,
                )
            )

            edges.append(
                GraphEdge(
                    source_fqn=class_fqn_str,
                    target_fqn=fqn,
                    kind=EdgeKind.CONTAINS,
                    confidence=Confidence.HIGH,
                    evidence="tree-sitter",
                )
            )

    def _extract_constructors(
        self,
        root: Node,
        package: str,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract constructor declarations."""
        for ctor_node in _walk_all(root, "constructor_declaration"):
            enclosing = _find_enclosing_class(ctor_node)
            if enclosing is None:
                continue
            class_fqn_str = _class_fqn(package, enclosing)
            fqn = f"{class_fqn_str}.<init>"

            modifiers = _get_modifiers(ctor_node)
            annotations = _get_annotations(ctor_node)

            params_node = ctor_node.child_by_field_name("parameters")
            params = (
                _parse_formal_parameters(params_node)
                if params_node is not None
                else []
            )

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
                "is_constructor": True,
                "params": params,
            }
            if annotations:
                properties["annotations"] = annotations

            nodes.append(
                GraphNode(
                    fqn=fqn,
                    name="<init>",
                    kind=NodeKind.FUNCTION,
                    language="java",
                    path=file_path,
                    line=ctor_node.start_point[0] + 1,
                    end_line=ctor_node.end_point[0] + 1,
                    loc=_compute_loc(ctor_node),
                    complexity=_compute_complexity(ctor_node),
                    properties=properties,
                )
            )

            edges.append(
                GraphEdge(
                    source_fqn=class_fqn_str,
                    target_fqn=fqn,
                    kind=EdgeKind.CONTAINS,
                    confidence=Confidence.HIGH,
                    evidence="tree-sitter",
                )
            )

    def _extract_fields(
        self,
        root: Node,
        package: str,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract field declarations."""
        for field_node in _walk_all(root, "field_declaration"):
            # Get field name from declarator
            declarator = field_node.child_by_field_name("declarator")
            if declarator is None:
                continue
            name_node = declarator.child_by_field_name("name")
            if name_node is None:
                continue

            enclosing = _find_enclosing_class(field_node)
            if enclosing is None:
                continue
            class_fqn_str = _class_fqn(package, enclosing)
            field_name = _node_text(name_node)
            fqn = f"{class_fqn_str}.{field_name}"

            modifiers = _get_modifiers(field_node)
            annotations = _get_annotations(field_node)
            annotation_args = _get_annotation_args(field_node)
            annotation_params = _get_annotation_params(field_node)

            type_node = field_node.child_by_field_name("type")
            field_type = _node_text(type_node) if type_node is not None else "unknown"

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
                "type": field_type,
                "is_static": "static" in modifiers,
                "is_final": "final" in modifiers,
            }
            if annotations:
                properties["annotations"] = annotations
            if annotation_args:
                properties["annotation_args"] = annotation_args
            if annotation_params:
                properties["annotation_params"] = annotation_params

            nodes.append(
                GraphNode(
                    fqn=fqn,
                    name=field_name,
                    kind=NodeKind.FIELD,
                    language="java",
                    path=file_path,
                    line=field_node.start_point[0] + 1,
                    end_line=field_node.end_point[0] + 1,
                    properties=properties,
                )
            )

            edges.append(
                GraphEdge(
                    source_fqn=class_fqn_str,
                    target_fqn=fqn,
                    kind=EdgeKind.CONTAINS,
                    confidence=Confidence.HIGH,
                    evidence="tree-sitter",
                )
            )

    def _build_local_var_map(self, method_node: Node) -> dict[str, str]:
        """Walk local_variable_declaration nodes in a method body to build {name: type}."""
        result: dict[str, str] = {}
        for decl in _walk_all(method_node, "local_variable_declaration"):
            type_node = decl.child_by_field_name("type")
            if type_node is None:
                continue
            raw_type = _strip_generics(_node_text(type_node))

            declarator = decl.child_by_field_name("declarator")
            if declarator is None:
                continue
            name_node = declarator.child_by_field_name("name")
            if name_node is None:
                continue
            result[_node_text(name_node)] = raw_type
        return result

    def _extract_method_calls(
        self,
        root: Node,
        package: str,
        file_path: str,
        import_map: dict[str, str],
        field_type_map: dict[str, str],
        edges: list[GraphEdge],
    ) -> None:
        """Extract method invocation edges."""
        # Cache local var maps per enclosing method (keyed by start_byte)
        local_var_cache: dict[int, dict[str, str]] = {}

        for call_node in _walk_all(root, "method_invocation"):
            method_name_node = call_node.child_by_field_name("name")
            if method_name_node is None:
                continue
            method_name = _node_text(method_name_node)

            # Find enclosing method for the source FQN
            enclosing_method = _find_enclosing_method(call_node)
            if enclosing_method is None:
                continue
            enclosing_class = _find_enclosing_class(enclosing_method)
            if enclosing_class is None:
                continue
            class_fqn_str = _class_fqn(package, enclosing_class)

            if enclosing_method.type == "constructor_declaration":
                source_fqn = f"{class_fqn_str}.<init>"
            else:
                enc_name_node = enclosing_method.child_by_field_name("name")
                if enc_name_node is None:
                    continue
                source_fqn = f"{class_fqn_str}.{_node_text(enc_name_node)}"

            # Build target FQN with receiver type resolution
            receiver_node = call_node.child_by_field_name("object")
            if receiver_node is not None:
                receiver_text = _node_text(receiver_node)

                # Build local var map (cached per method)
                key = enclosing_method.start_byte
                if key not in local_var_cache:
                    local_var_cache[key] = self._build_local_var_map(enclosing_method)
                local_var_map = local_var_cache[key]

                resolved_type = _resolve_receiver_type(
                    receiver_text, field_type_map, local_var_map, import_map, package
                )
                if resolved_type is not None:
                    target_fqn = f"{resolved_type}.{method_name}"
                    confidence = Confidence.MEDIUM
                else:
                    target_fqn = f"{receiver_text}.{method_name}"
                    confidence = Confidence.LOW
            else:
                # No receiver — same-class call
                target_fqn = f"{class_fqn_str}.{method_name}"
                confidence = Confidence.MEDIUM

            edges.append(
                GraphEdge(
                    source_fqn=source_fqn,
                    target_fqn=target_fqn,
                    kind=EdgeKind.CALLS,
                    confidence=confidence,
                    evidence="tree-sitter",
                    properties={"line": call_node.start_point[0] + 1},
                )
            )

    def _extract_object_creation(
        self,
        root: Node,
        package: str,
        file_path: str,
        import_map: dict[str, str],
        edges: list[GraphEdge],
    ) -> None:
        """Extract 'new ClassName(...)' as CALLS edges to <init>."""
        for new_node in _walk_all(root, "object_creation_expression"):
            type_node = new_node.child_by_field_name("type")
            if type_node is None:
                continue
            created_type = _node_text(type_node)

            # Find enclosing method
            enclosing_method = _find_enclosing_method(new_node)
            if enclosing_method is None:
                continue
            enclosing_class = _find_enclosing_class(enclosing_method)
            if enclosing_class is None:
                continue
            class_fqn_str = _class_fqn(package, enclosing_class)

            if enclosing_method.type == "constructor_declaration":
                source_fqn = f"{class_fqn_str}.<init>"
            else:
                enc_name_node = enclosing_method.child_by_field_name("name")
                if enc_name_node is None:
                    continue
                source_fqn = f"{class_fqn_str}.{_node_text(enc_name_node)}"

            # Resolve created type via import map if possible
            resolved_type = import_map.get(created_type, created_type)
            target_fqn = f"{resolved_type}.<init>"

            edges.append(
                GraphEdge(
                    source_fqn=source_fqn,
                    target_fqn=target_fqn,
                    kind=EdgeKind.CALLS,
                    confidence=Confidence.LOW,
                    evidence="tree-sitter",
                    properties={"line": new_node.start_point[0] + 1},
                )
            )

    def _tag_sql_strings(
        self,
        root: Node,
        package: str,
        nodes: list[GraphNode],
    ) -> None:
        """Scan string literals for SQL keywords and tag the enclosing method."""
        # Build a lookup of method nodes by FQN for tagging
        method_node_map: dict[str, GraphNode] = {
            n.fqn: n for n in nodes if n.kind == NodeKind.FUNCTION
        }

        for string_node in _walk_all(root, "string_literal"):
            text = _node_text(string_node)

            if not _SQL_PATTERN.search(text):
                continue

            # Find enclosing method
            enclosing_method = _find_enclosing_method(string_node)
            if enclosing_method is None:
                continue
            enclosing_class = _find_enclosing_class(enclosing_method)
            if enclosing_class is None:
                continue
            class_fqn_str = _class_fqn(package, enclosing_class)

            if enclosing_method.type == "constructor_declaration":
                method_fqn = f"{class_fqn_str}.<init>"
            else:
                enc_name_node = enclosing_method.child_by_field_name("name")
                if enc_name_node is None:
                    continue
                method_fqn = f"{class_fqn_str}.{_node_text(enc_name_node)}"

            graph_node = method_node_map.get(method_fqn)
            if graph_node is not None:
                tagged = graph_node.properties.setdefault("tagged_strings", [])
                tagged.append(text)


    # Primitives and java.lang types that should not generate DEPENDS_ON edges
    _SKIP_TYPES: set[str] = {
        "void", "int", "long", "short", "byte", "float", "double",
        "boolean", "char", "String", "Integer", "Long", "Short",
        "Byte", "Float", "Double", "Boolean", "Character", "Object",
        "Class", "Void", "Number",
    }

    def _resolve_type_fqn(
        self, type_text: str, import_map: dict[str, str], package: str,
    ) -> str | None:
        """Resolve a type name to a FQN, skipping primitives and java.lang types.

        Returns None if the type should be skipped (primitive, java.lang, etc.).
        """
        name = _strip_generics(type_text).strip()
        # Handle fully-qualified names used inline
        if "." in name:
            return name
        if name in self._SKIP_TYPES or not name or not name[0].isupper():
            return None
        # Resolve through imports, fall back to same-package
        if name in import_map:
            return import_map[name]
        if package:
            return f"{package}.{name}"
        return name

    def _extract_type_references(
        self,
        root: Node,
        package: str,
        import_map: dict[str, str],
        edges: list[GraphEdge],
    ) -> None:
        """Extract DEPENDS_ON edges from type references.

        Scans field types, method return types, method parameter types,
        and generic type arguments in superclass/interface declarations
        to create class-level DEPENDS_ON edges.
        """
        seen: set[tuple[str, str]] = set()

        def _add_dep(source_fqn: str, type_text: str) -> None:
            resolved = self._resolve_type_fqn(type_text, import_map, package)
            if resolved is None or resolved == source_fqn:
                return
            key = (source_fqn, resolved)
            if key in seen:
                return
            seen.add(key)
            edges.append(
                GraphEdge(
                    source_fqn=source_fqn,
                    target_fqn=resolved,
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=Confidence.MEDIUM,
                    evidence="tree-sitter",
                )
            )

        def _extract_type_names(type_node: Node) -> list[str]:
            """Extract all type names from a type node, including generics."""
            results: list[str] = []
            if type_node.type == "type_identifier":
                results.append(_node_text(type_node))
            elif type_node.type == "generic_type":
                # e.g., List<Pet> — extract both List and Pet
                for child in type_node.children:
                    results.extend(_extract_type_names(child))
            elif type_node.type == "type_arguments":
                for child in type_node.children:
                    results.extend(_extract_type_names(child))
            elif type_node.type == "scoped_type_identifier":
                results.append(_node_text(type_node))
            return results

        # Walk all class and interface declarations
        for class_type in ("class_declaration", "interface_declaration"):
            for class_node in _walk_all(root, class_type):
                class_fqn_str = _class_fqn(package, class_node)

                # 1. Field types
                for field_node in _walk_all(class_node, "field_declaration"):
                    type_node = field_node.child_by_field_name("type")
                    if type_node is not None:
                        for type_name in _extract_type_names(type_node):
                            _add_dep(class_fqn_str, type_name)

                # 2. Method return types and parameter types
                for method_node in _walk_all(class_node, "method_declaration"):
                    # Return type
                    ret_node = method_node.child_by_field_name("type")
                    if ret_node is not None:
                        for type_name in _extract_type_names(ret_node):
                            _add_dep(class_fqn_str, type_name)
                    # Parameter types
                    params_node = method_node.child_by_field_name("parameters")
                    if params_node is not None:
                        for param in params_node.children:
                            if param.type == "formal_parameter":
                                ptype = param.child_by_field_name("type")
                                if ptype is not None:
                                    for type_name in _extract_type_names(ptype):
                                        _add_dep(class_fqn_str, type_name)

                # 3. Constructor parameter types
                for ctor_node in _walk_all(class_node, "constructor_declaration"):
                    params_node = ctor_node.child_by_field_name("parameters")
                    if params_node is not None:
                        for param in params_node.children:
                            if param.type == "formal_parameter":
                                ptype = param.child_by_field_name("type")
                                if ptype is not None:
                                    for type_name in _extract_type_names(ptype):
                                        _add_dep(class_fqn_str, type_name)

                # 4. Superclass and interface generic type arguments
                superclass = class_node.child_by_field_name("superclass")
                if superclass is not None:
                    for type_name in _extract_type_names(superclass):
                        _add_dep(class_fqn_str, type_name)
                interfaces = class_node.child_by_field_name("interfaces")
                if interfaces is not None:
                    for type_name in _extract_type_names(interfaces):
                        _add_dep(class_fqn_str, type_name)


# Register this extractor at module level
register_extractor("java", JavaExtractor())
