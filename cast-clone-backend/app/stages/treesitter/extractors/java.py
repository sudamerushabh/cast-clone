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

        # Step 8: Parse method calls
        self._extract_method_calls(root, package, file_path, edges)

        # Step 9: Parse object creation
        self._extract_object_creation(
            root, package, file_path, import_map, edges
        )

        # Step 10: Tag SQL strings
        self._tag_sql_strings(root, package, nodes)

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

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
                "is_abstract": "abstract" in modifiers,
            }
            if annotations:
                properties["annotations"] = annotations

            nodes.append(
                GraphNode(
                    fqn=fqn,
                    name=name,
                    kind=NodeKind.CLASS,
                    language="java",
                    path=file_path,
                    line=class_node.start_point[0] + 1,
                    end_line=class_node.end_point[0] + 1,
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
                                if type_node.type == "type_identifier":
                                    edges.append(
                                        GraphEdge(
                                            source_fqn=fqn,
                                            target_fqn=_node_text(type_node),
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

            nodes.append(
                GraphNode(
                    fqn=fqn,
                    name=method_name,
                    kind=NodeKind.FUNCTION,
                    language="java",
                    path=file_path,
                    line=method_node.start_point[0] + 1,
                    end_line=method_node.end_point[0] + 1,
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

    def _extract_method_calls(
        self,
        root: Node,
        package: str,
        file_path: str,
        edges: list[GraphEdge],
    ) -> None:
        """Extract method invocation edges."""
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

            # Build target FQN
            receiver_node = call_node.child_by_field_name("object")
            if receiver_node is not None:
                receiver_text = _node_text(receiver_node)
                target_fqn = f"{receiver_text}.{method_name}"
            else:
                target_fqn = method_name

            edges.append(
                GraphEdge(
                    source_fqn=source_fqn,
                    target_fqn=target_fqn,
                    kind=EdgeKind.CALLS,
                    confidence=Confidence.LOW,
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


# Register this extractor at module level
register_extractor("java", JavaExtractor())
