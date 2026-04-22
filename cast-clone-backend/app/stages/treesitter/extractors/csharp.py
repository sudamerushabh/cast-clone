"""C# tree-sitter extractor.

Parses C# source files using tree-sitter-c-sharp and extracts:
- Namespace declarations (block-scoped and file-scoped)
- Using directives
- Class declarations (with base class, interfaces, attributes)
- Interface declarations
- Method declarations (with attributes, parameters, return type)
- Property declarations (auto-properties)
- Field declarations
- Constructor declarations
- Method invocations (CALLS edges, LOW confidence)
- Object creation expressions (CALLS edges to constructor)
- Attribute arguments (for framework plugins)
- SQL-like string literals

All FQNs are file-local: {namespace}.{Class}.{Member}. Cross-file
resolution happens in later pipeline stages (SCIP, global symbol pass).
"""

from __future__ import annotations

import re
from typing import Any

import structlog
import tree_sitter_c_sharp as tscsharp
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.treesitter.extractors import register_extractor

log = structlog.get_logger(__name__)

CS_LANGUAGE = Language(tscsharp.language())

# -- Precompiled Queries -------------------------------------------------------

Q_USING = Query(CS_LANGUAGE, "(using_directive (identifier) @name) @using")
Q_USING_QUALIFIED = Query(
    CS_LANGUAGE, "(using_directive (qualified_name) @name) @using"
)
Q_CLASS = Query(CS_LANGUAGE, "(class_declaration name: (identifier) @name) @class")
Q_INTERFACE = Query(
    CS_LANGUAGE, "(interface_declaration name: (identifier) @name) @iface"
)
Q_METHOD = Query(CS_LANGUAGE, "(method_declaration name: (identifier) @name) @method")
Q_CONSTRUCTOR = Query(
    CS_LANGUAGE, "(constructor_declaration name: (identifier) @name) @ctor"
)
Q_PROPERTY = Query(CS_LANGUAGE, "(property_declaration name: (identifier) @name) @prop")
Q_FIELD = Query(CS_LANGUAGE, "(field_declaration) @field")
Q_INVOCATION = Query(CS_LANGUAGE, "(invocation_expression function: (_) @func) @call")
Q_OBJECT_CREATION = Query(
    CS_LANGUAGE, "(object_creation_expression type: (_) @type) @creation"
)
Q_STRING = Query(CS_LANGUAGE, "(string_literal) @string")
Q_VERBATIM_STRING = Query(CS_LANGUAGE, "(verbatim_string_literal) @string")

# SQL keywords pattern for tagging
_SQL_PATTERN = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|FROM|WHERE|JOIN)\b",
    re.IGNORECASE,
)

# DI registration method names we recognise
_DI_METHODS: frozenset[str] = frozenset({
    "AddScoped", "AddTransient", "AddSingleton",
    "AddDbContext", "AddDbContextPool",
    "AddKeyedScoped", "AddKeyedTransient", "AddKeyedSingleton",
})

# Pattern to extract generic type args from an invocation like AddScoped<IFoo, Bar>
_GENERIC_ARGS_RE = re.compile(r"<\s*([^>]+)\s*>")


def _parse_type_args(type_str: str) -> list[str]:
    """Parse generic type arguments from a type string.

    Examples:
        "DbSet<Brand>"           -> ["Brand"]
        "ICollection<OrderItem>" -> ["OrderItem"]
        "Dictionary<string, int>" -> ["string", "int"]
        "string"                  -> []
    """
    lt = type_str.find("<")
    if lt == -1:
        return []
    gt = type_str.rfind(">")
    if gt == -1:
        return []
    inner = type_str[lt + 1 : gt].strip()
    if not inner:
        return []
    # Split on comma, strip whitespace, handle nested generics simply
    # by only splitting on top-level commas
    depth = 0
    parts: list[str] = []
    current: list[str] = []
    for ch in inner:
        if ch == "<":
            depth += 1
            current.append(ch)
        elif ch == ">":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return [p for p in parts if p]


def _query_matches(query: Query, node: Node) -> list[tuple[int, dict[str, list[Node]]]]:
    """Run a tree-sitter query against a node and return matches.

    Uses the QueryCursor API from tree-sitter 0.25+.
    """
    cursor = QueryCursor(query)
    return list(cursor.matches(node))


def _node_text(node: Node, source: bytes) -> str:
    """Extract UTF-8 text from a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _get_modifiers(node: Node, source: bytes) -> tuple[str | None, list[str]]:
    """Extract visibility and modifier keywords from a declaration node.

    Returns:
        Tuple of (visibility, [modifier_keywords]).
    """
    visibility = None
    modifiers: list[str] = []
    for child in node.children:
        if child.type == "modifier":
            text = _node_text(child, source)
            if text in ("public", "private", "protected", "internal"):
                visibility = text
            else:
                modifiers.append(text)
    return visibility, modifiers


def _get_attributes(node: Node, source: bytes) -> tuple[list[str], dict[str, str]]:
    """Extract attributes (annotations) and their arguments from a declaration.

    Returns:
        Tuple of (attribute_names, {attr_name: argument_string, "": first_unnamed_arg}).

    The unnamed first positional argument is stored under the empty-string key
    ``""`` so that framework plugins can read it without knowing the attribute
    name.  Named arguments (``key = "value"``) are stored under their key.
    """
    attr_names: list[str] = []
    attr_args: dict[str, str] = {}

    for child in node.children:
        if child.type == "attribute_list":
            for attr_node in child.children:
                if attr_node.type == "attribute":
                    name_node = attr_node.child_by_field_name("name")
                    if name_node:
                        attr_name = _node_text(name_node, source)
                        attr_names.append(attr_name)
                        # Extract attribute_argument_list if present
                        for attr_child in attr_node.children:
                            if attr_child.type == "attribute_argument_list":
                                arg_text = _node_text(attr_child, source)
                                # Strip parentheses
                                arg_text = arg_text.strip("()")
                                # Remove surrounding quotes from simple string args
                                clean = arg_text.strip().strip('"')
                                # Store under attr name for direct lookup
                                attr_args[attr_name] = clean
                                # Store first positional arg under "" for
                                # plugins that expect unnamed args
                                if "=" not in clean:
                                    attr_args[""] = clean

    return attr_names, attr_args


def _get_base_types(node: Node, source: bytes) -> list[str]:
    """Extract base types from a class/interface base_list."""
    base_types: list[str] = []
    for child in node.children:
        if child.type == "base_list":
            for base_child in child.children:
                if base_child.type in (
                    "identifier",
                    "qualified_name",
                    "generic_name",
                ):
                    base_types.append(_node_text(base_child, source))
                elif base_child.type == "simple_base_type":
                    for inner in base_child.children:
                        if inner.type in (
                            "identifier",
                            "qualified_name",
                            "generic_name",
                        ):
                            base_types.append(_node_text(inner, source))
    return base_types


def _get_parameters(node: Node, source: bytes) -> list[dict[str, str]]:
    """Extract parameter list from a method/constructor."""
    params: list[dict[str, str]] = []
    param_list = node.child_by_field_name("parameters")
    if not param_list:
        return params
    for child in param_list.children:
        if child.type == "parameter":
            ptype = child.child_by_field_name("type")
            pname = child.child_by_field_name("name")
            param: dict[str, str] = {}
            if pname:
                param["name"] = _node_text(pname, source)
            if ptype:
                param["type"] = _node_text(ptype, source)
            if param:
                params.append(param)
    return params


def _get_return_type(node: Node, source: bytes) -> str | None:
    """Extract return type from a method declaration.

    The C# tree-sitter grammar uses the field name ``returns`` for the
    return type on method declarations.
    """
    rtype = node.child_by_field_name("returns")
    if rtype:
        return _node_text(rtype, source)
    # Fallback: try 'type' field
    rtype = node.child_by_field_name("type")
    if rtype:
        return _node_text(rtype, source)
    return None


def _compute_loc(node: Node) -> int:
    """Compute lines of code for a tree-sitter node."""
    return node.end_point[0] - node.start_point[0] + 1


_COMPLEXITY_NODE_TYPES: set[str] = {
    "if_statement",
    "for_statement",
    "for_each_statement",
    "while_statement",
    "do_statement",
    "catch_clause",
    "conditional_expression",
    "case_switch_label",
}


def _compute_complexity(node: Node) -> int:
    """Compute cyclomatic complexity for a method body."""
    complexity = 1

    def _visit(n: Node) -> None:
        nonlocal complexity
        if n.type in _COMPLEXITY_NODE_TYPES:
            complexity += 1
        elif n.type == "binary_expression":
            op_node = n.child_by_field_name("operator")
            if op_node is not None and op_node.text and op_node.text.decode("utf-8") in ("&&", "||"):
                complexity += 1
        for child in n.children:
            _visit(child)

    body = node.child_by_field_name("body")
    if body is not None:
        _visit(body)
    return complexity


def _resolve_namespace(node: Node, source: bytes) -> str:
    """Walk up the tree to find the enclosing namespace(s).

    Handles both block-scoped and file-scoped namespaces.
    Returns dotted namespace string or empty string.
    """
    parts: list[str] = []
    current = node.parent
    while current:
        if current.type in (
            "namespace_declaration",
            "file_scoped_namespace_declaration",
        ):
            name_node = current.child_by_field_name("name")
            if name_node:
                parts.append(_node_text(name_node, source))
        current = current.parent
    parts.reverse()
    return ".".join(parts)


def _resolve_file_scoped_namespace(root: Node, source: bytes) -> str:
    """Find a file-scoped namespace declaration at the compilation_unit level.

    For file-scoped namespaces (``namespace X;``), the class declarations are
    siblings of the namespace node rather than children.  This helper returns
    the namespace string so callers can prepend it to FQNs.
    """
    for child in root.children:
        if child.type == "file_scoped_namespace_declaration":
            name_node = child.child_by_field_name("name")
            if name_node:
                return _node_text(name_node, source)
    return ""


def _resolve_class_chain(node: Node, source: bytes) -> list[str]:
    """Walk up to find enclosing class names (for nested classes)."""
    parts: list[str] = []
    current = node.parent
    while current:
        if current.type in ("class_declaration", "struct_declaration"):
            name_node = current.child_by_field_name("name")
            if name_node:
                parts.append(_node_text(name_node, source))
        current = current.parent
    parts.reverse()
    return parts


def _make_fqn(namespace: str, *parts: str) -> str:
    """Build a fully qualified name from namespace and name parts."""
    all_parts = [p for p in (namespace, *parts) if p]
    return ".".join(all_parts)


# Base Class Library (BCL) namespaces — skipped when guessing the
# namespace of an unqualified base type at extract time.
_BCL_ROOTS: frozenset[str] = frozenset({"System", "Microsoft"})


def _is_bcl_namespace(ns: str) -> bool:
    """Return True if ``ns`` is (or nests under) a .NET BCL root namespace."""
    root = ns.split(".", 1)[0]
    return root in _BCL_ROOTS


class CSharpExtractor:
    """Extracts graph nodes and edges from C# source code using tree-sitter.

    This is a file-level extractor.  It produces:
    - CLASS / INTERFACE / FUNCTION / FIELD nodes
    - CONTAINS edges (class -> member)
    - INHERITS / IMPLEMENTS edges (class -> base type)
    - CALLS edges (method -> method invocation, LOW confidence)

    Cross-file resolution (upgrading CALLS to HIGH confidence, resolving
    interface -> implementation) happens in SCIP (Stage 4) and the global
    symbol pass.
    """

    def __init__(self) -> None:
        self._parser = Parser(CS_LANGUAGE)

    def extract(
        self,
        source: bytes,
        file_path: str,
        root_path: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Parse a C# source file and return extracted nodes and edges.

        Args:
            source: Raw bytes of the .cs file.
            file_path: Relative path of the file within the project.
            root_path: Absolute path to the project root.

        Returns:
            Tuple of (nodes, edges).
        """
        log.debug("csharp_extract_start", file_path=file_path)
        tree = self._parser.parse(source)
        root = tree.root_node

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # Collect using directives for later reference
        usings = self._extract_usings(root, source)

        # Determine file-scoped namespace (sibling to classes, not parent)
        file_ns = _resolve_file_scoped_namespace(root, source)

        # Extract classes
        for _idx, captures in _query_matches(Q_CLASS, root):
            class_node = captures["class"][0]
            name_node = captures["name"][0]
            self._extract_class(
                class_node,
                name_node,
                source,
                file_path,
                usings,
                nodes,
                edges,
                file_ns=file_ns,
            )

        # Extract interfaces
        for _idx, captures in _query_matches(Q_INTERFACE, root):
            iface_node = captures["iface"][0]
            name_node = captures["name"][0]
            self._extract_interface(
                iface_node,
                name_node,
                source,
                file_path,
                usings,
                nodes,
                edges,
                file_ns=file_ns,
            )

        # Create MODULE nodes from namespaces (analogous to Java packages).
        # Group top-level classes/interfaces by their namespace and create
        # MODULE -> CONTAINS -> CLASS/INTERFACE edges so the dependencies
        # view can aggregate cross-module relationships.
        self._create_module_nodes(nodes, edges, file_path)

        log.debug(
            "csharp_extract_complete",
            file=file_path,
            nodes=len(nodes),
            edges=len(edges),
        )

        return nodes, edges

    # -- Using directives -------------------------------------------------------

    def _extract_usings(self, root: Node, source: bytes) -> list[str]:
        """Extract all using directive namespace strings."""
        usings: list[str] = []
        for _idx, captures in _query_matches(Q_USING, root):
            usings.append(_node_text(captures["name"][0], source))
        for _idx, captures in _query_matches(Q_USING_QUALIFIED, root):
            usings.append(_node_text(captures["name"][0], source))
        return usings

    # -- Module (namespace) node creation ----------------------------------------

    def _create_module_nodes(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        file_path: str,
    ) -> None:
        """Create MODULE nodes from C# namespaces.

        Groups top-level CLASS and INTERFACE nodes by their namespace and
        creates a MODULE node per namespace with CONTAINS edges to each
        direct child class/interface.  Nested classes are skipped (they are
        already contained by their outer class).

        The MODULE FQN is the namespace string (e.g.
        ``SimplCommerce.Module.Core.Models``), matching Java's use of the
        package name as MODULE FQN.
        """
        # Collect namespace -> [class/interface FQNs]
        ns_to_children: dict[str, list[str]] = {}
        for node in nodes:
            if node.kind not in (NodeKind.CLASS, NodeKind.INTERFACE):
                continue
            # Derive namespace: strip the last dotted component (the class name)
            dot_idx = node.fqn.rfind(".")
            if dot_idx <= 0:
                continue
            namespace = node.fqn[:dot_idx]
            # Only direct children — skip nested classes (those whose
            # relative part after the namespace still contains a dot)
            relative = node.fqn[dot_idx + 1 :]
            if "." in relative:
                continue
            ns_to_children.setdefault(namespace, []).append(node.fqn)

        for namespace, child_fqns in ns_to_children.items():
            module_name = namespace.rsplit(".", 1)[-1]
            module_node = GraphNode(
                fqn=namespace,
                name=module_name,
                kind=NodeKind.MODULE,
                language="csharp",
                path=file_path,
                line=1,
            )
            nodes.append(module_node)

            for child_fqn in child_fqns:
                edges.append(
                    GraphEdge(
                        source_fqn=namespace,
                        target_fqn=child_fqn,
                        kind=EdgeKind.CONTAINS,
                        confidence=Confidence.HIGH,
                        evidence="tree-sitter",
                    )
                )

    # -- Class extraction -------------------------------------------------------

    def _extract_class(
        self,
        class_node: Node,
        name_node: Node,
        source: bytes,
        file_path: str,
        usings: list[str],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        *,
        file_ns: str = "",
    ) -> None:
        """Extract a class declaration and all its members."""
        class_name = _node_text(name_node, source)
        namespace = _resolve_namespace(class_node, source)
        # For file-scoped namespaces the class is a sibling, not a child
        if not namespace and file_ns:
            namespace = file_ns
        enclosing = _resolve_class_chain(class_node, source)
        fqn = _make_fqn(namespace, *enclosing, class_name)

        visibility, modifiers = _get_modifiers(class_node, source)
        attr_names, attr_args = _get_attributes(class_node, source)
        base_types = _get_base_types(class_node, source)

        props: dict[str, Any] = {}
        if attr_names:
            props["annotations"] = attr_names
        if attr_args:
            props["annotation_args"] = attr_args
        if "abstract" in modifiers:
            props["is_abstract"] = True
        if "static" in modifiers:
            props["is_static"] = True
        if "sealed" in modifiers:
            props["is_sealed"] = True
        if usings:
            props["usings"] = usings

        # Classify base types into base_class and implements list
        interfaces: list[str] = []
        for bt in base_types:
            bare_name = bt.split("<")[0]
            if self._looks_like_interface(bare_name):
                interfaces.append(bt)
            elif "base_class" not in props:
                props["base_class"] = bare_name
        if interfaces:
            props["implements"] = interfaces

        node = GraphNode(
            fqn=fqn,
            name=class_name,
            kind=NodeKind.CLASS,
            language="csharp",
            path=file_path,
            line=class_node.start_point[0] + 1,
            end_line=class_node.end_point[0] + 1,
            visibility=visibility,
            loc=_compute_loc(class_node),
            properties=props,
        )
        nodes.append(node)

        # Base types -> INHERITS / IMPLEMENTS edges
        for bt in base_types:
            bare_name = bt.split("<")[0]
            target_fqn = self._resolve_base_type_fqn(
                bare_name, namespace, usings
            )
            if self._looks_like_interface(bare_name):
                edges.append(
                    GraphEdge(
                        source_fqn=fqn,
                        target_fqn=target_fqn,
                        kind=EdgeKind.IMPLEMENTS,
                        confidence=Confidence.HIGH,
                        evidence="tree-sitter",
                    )
                )
            else:
                edges.append(
                    GraphEdge(
                        source_fqn=fqn,
                        target_fqn=target_fqn,
                        kind=EdgeKind.INHERITS,
                        confidence=Confidence.HIGH,
                        evidence="tree-sitter",
                    )
                )

        # Extract members
        body = class_node.child_by_field_name("body")
        if body:
            self._extract_members(body, fqn, namespace, source, file_path, nodes, edges)

            # Scan all method bodies in the class for DI registrations
            di_regs: list[dict[str, str]] = []
            for child in body.children:
                if child.type in ("method_declaration", "constructor_declaration"):
                    mbody = child.child_by_field_name("body")
                    if mbody:
                        di_regs.extend(self._extract_di_registrations(mbody, source))
            if di_regs:
                node.properties["di_registrations"] = di_regs

    # -- Interface extraction ---------------------------------------------------

    def _extract_interface(
        self,
        iface_node: Node,
        name_node: Node,
        source: bytes,
        file_path: str,
        usings: list[str],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        *,
        file_ns: str = "",
    ) -> None:
        """Extract an interface declaration."""
        iface_name = _node_text(name_node, source)
        namespace = _resolve_namespace(iface_node, source)
        if not namespace and file_ns:
            namespace = file_ns
        fqn = _make_fqn(namespace, iface_name)

        visibility, modifiers = _get_modifiers(iface_node, source)
        attr_names, attr_args = _get_attributes(iface_node, source)

        props: dict[str, Any] = {}
        if attr_names:
            props["annotations"] = attr_names
        if attr_args:
            props["annotation_args"] = attr_args

        node = GraphNode(
            fqn=fqn,
            name=iface_name,
            kind=NodeKind.INTERFACE,
            language="csharp",
            path=file_path,
            line=iface_node.start_point[0] + 1,
            end_line=iface_node.end_point[0] + 1,
            visibility=visibility,
            loc=_compute_loc(iface_node),
            properties=props,
        )
        nodes.append(node)

        # Interface base types -> IMPLEMENTS edges
        base_types = _get_base_types(iface_node, source)
        for bt in base_types:
            bare_name = bt.split("<")[0]
            target_fqn = self._resolve_base_type_fqn(
                bare_name, namespace, usings
            )
            edges.append(
                GraphEdge(
                    source_fqn=fqn,
                    target_fqn=target_fqn,
                    kind=EdgeKind.IMPLEMENTS,
                    confidence=Confidence.HIGH,
                    evidence="tree-sitter",
                )
            )

        # Extract interface method signatures
        body = iface_node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "method_declaration":
                    mn = child.child_by_field_name("name")
                    if mn:
                        self._extract_method(
                            child,
                            mn,
                            fqn,
                            namespace,
                            source,
                            file_path,
                            nodes,
                            edges,
                        )

    # -- Member extraction ------------------------------------------------------

    def _extract_members(
        self,
        body: Node,
        class_fqn: str,
        namespace: str,
        source: bytes,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract all members from a class body (declaration_list)."""
        # Methods
        for _idx, captures in _query_matches(Q_METHOD, body):
            method_node = captures["method"][0]
            name_node = captures["name"][0]
            if method_node.parent == body:
                self._extract_method(
                    method_node,
                    name_node,
                    class_fqn,
                    namespace,
                    source,
                    file_path,
                    nodes,
                    edges,
                )

        # Constructors
        for _idx, captures in _query_matches(Q_CONSTRUCTOR, body):
            ctor_node = captures["ctor"][0]
            name_node = captures["name"][0]
            if ctor_node.parent == body:
                self._extract_constructor(
                    ctor_node,
                    name_node,
                    class_fqn,
                    namespace,
                    source,
                    file_path,
                    nodes,
                    edges,
                )

        # Properties
        for _idx, captures in _query_matches(Q_PROPERTY, body):
            prop_node = captures["prop"][0]
            name_node = captures["name"][0]
            if prop_node.parent == body:
                self._extract_property(
                    prop_node,
                    name_node,
                    class_fqn,
                    source,
                    file_path,
                    nodes,
                    edges,
                )

        # Fields
        for _idx, captures in _query_matches(Q_FIELD, body):
            field_node = captures["field"][0]
            if field_node.parent == body:
                self._extract_field(
                    field_node,
                    class_fqn,
                    source,
                    file_path,
                    nodes,
                    edges,
                )

    # -- Method extraction ------------------------------------------------------

    def _extract_method(
        self,
        method_node: Node,
        name_node: Node,
        class_fqn: str,
        namespace: str,
        source: bytes,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract a method declaration."""
        method_name = _node_text(name_node, source)
        fqn = f"{class_fqn}.{method_name}"

        visibility, modifiers = _get_modifiers(method_node, source)
        attr_names, attr_args = _get_attributes(method_node, source)
        params = _get_parameters(method_node, source)
        return_type = _get_return_type(method_node, source)

        props: dict[str, Any] = {}
        if attr_names:
            props["annotations"] = attr_names
        if attr_args:
            props["annotation_args"] = attr_args
        if params:
            props["parameters"] = params
        if return_type:
            props["return_type"] = return_type
        if "async" in modifiers:
            props["is_async"] = True
        if "static" in modifiers:
            props["is_static"] = True
        if "override" in modifiers:
            props["is_override"] = True
        if "virtual" in modifiers:
            props["is_virtual"] = True
        if "abstract" in modifiers:
            props["is_abstract"] = True

        node = GraphNode(
            fqn=fqn,
            name=method_name,
            kind=NodeKind.FUNCTION,
            language="csharp",
            path=file_path,
            line=method_node.start_point[0] + 1,
            end_line=method_node.end_point[0] + 1,
            visibility=visibility,
            loc=_compute_loc(method_node),
            complexity=_compute_complexity(method_node),
            properties=props,
        )
        nodes.append(node)

        # CONTAINS edge from class
        edges.append(
            GraphEdge(
                source_fqn=class_fqn,
                target_fqn=fqn,
                kind=EdgeKind.CONTAINS,
                confidence=Confidence.HIGH,
                evidence="tree-sitter",
            )
        )

        # Extract method body for calls and strings
        method_body = method_node.child_by_field_name("body")
        if method_body:
            self._extract_calls(method_body, fqn, namespace, source, edges)
            self._extract_sql_strings(method_body, fqn, source, nodes)

    # -- Constructor extraction -------------------------------------------------

    def _extract_constructor(
        self,
        ctor_node: Node,
        name_node: Node,
        class_fqn: str,
        namespace: str,
        source: bytes,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract a constructor declaration."""
        ctor_name = _node_text(name_node, source)
        fqn = f"{class_fqn}.{ctor_name}"

        visibility, modifiers = _get_modifiers(ctor_node, source)
        attr_names, attr_args = _get_attributes(ctor_node, source)
        params = _get_parameters(ctor_node, source)

        props: dict[str, Any] = {"is_constructor": True}
        if attr_names:
            props["annotations"] = attr_names
        if attr_args:
            props["annotation_args"] = attr_args
        if params:
            props["parameters"] = params

        node = GraphNode(
            fqn=fqn,
            name=ctor_name,
            kind=NodeKind.FUNCTION,
            language="csharp",
            path=file_path,
            line=ctor_node.start_point[0] + 1,
            end_line=ctor_node.end_point[0] + 1,
            visibility=visibility,
            loc=_compute_loc(ctor_node),
            complexity=_compute_complexity(ctor_node),
            properties=props,
        )
        nodes.append(node)

        # CONTAINS edge
        edges.append(
            GraphEdge(
                source_fqn=class_fqn,
                target_fqn=fqn,
                kind=EdgeKind.CONTAINS,
                confidence=Confidence.HIGH,
                evidence="tree-sitter",
            )
        )

        # Extract constructor body for calls
        body = ctor_node.child_by_field_name("body")
        if body:
            self._extract_calls(body, fqn, namespace, source, edges)

    # -- Property extraction ----------------------------------------------------

    def _extract_property(
        self,
        prop_node: Node,
        name_node: Node,
        class_fqn: str,
        source: bytes,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract a property declaration as a FIELD node."""
        prop_name = _node_text(name_node, source)
        fqn = f"{class_fqn}.{prop_name}"

        visibility, modifiers = _get_modifiers(prop_node, source)
        attr_names, attr_args = _get_attributes(prop_node, source)
        prop_type = prop_node.child_by_field_name("type")
        type_str = _node_text(prop_type, source) if prop_type else None

        props: dict[str, Any] = {"is_property": True}
        if type_str:
            props["type"] = type_str
            # Parse generic type arguments: DbSet<Brand> -> ["Brand"]
            type_args = _parse_type_args(type_str)
            if type_args:
                props["type_args"] = type_args
        if attr_names:
            props["annotations"] = attr_names
        if attr_args:
            props["annotation_args"] = attr_args
        if "static" in modifiers:
            props["is_static"] = True

        node = GraphNode(
            fqn=fqn,
            name=prop_name,
            kind=NodeKind.FIELD,
            language="csharp",
            path=file_path,
            line=prop_node.start_point[0] + 1,
            visibility=visibility,
            properties=props,
        )
        nodes.append(node)

        edges.append(
            GraphEdge(
                source_fqn=class_fqn,
                target_fqn=fqn,
                kind=EdgeKind.CONTAINS,
                confidence=Confidence.HIGH,
                evidence="tree-sitter",
            )
        )

    # -- Field extraction -------------------------------------------------------

    def _extract_field(
        self,
        field_node: Node,
        class_fqn: str,
        source: bytes,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract a field_declaration (may contain multiple declarators)."""
        visibility, modifiers = _get_modifiers(field_node, source)
        attr_names, attr_args = _get_attributes(field_node, source)

        type_str: str | None = None

        # Extract variable declarators
        for child in field_node.children:
            if child.type == "variable_declaration":
                vtype = child.child_by_field_name("type")
                if vtype:
                    type_str = _node_text(vtype, source)
                for declarator in child.children:
                    if declarator.type == "variable_declarator":
                        fname_node = declarator.child_by_field_name("name")
                        if not fname_node:
                            for dc in declarator.children:
                                if dc.type == "identifier":
                                    fname_node = dc
                                    break
                        if fname_node:
                            field_name = _node_text(fname_node, source)
                            fqn = f"{class_fqn}.{field_name}"

                            props: dict[str, Any] = {}
                            if type_str:
                                props["type"] = type_str
                            if attr_names:
                                props["annotations"] = attr_names
                            if "static" in modifiers:
                                props["is_static"] = True
                            if "readonly" in modifiers:
                                props["is_readonly"] = True
                            if "const" in modifiers:
                                props["is_const"] = True

                            node = GraphNode(
                                fqn=fqn,
                                name=field_name,
                                kind=NodeKind.FIELD,
                                language="csharp",
                                path=file_path,
                                line=field_node.start_point[0] + 1,
                                visibility=visibility,
                                properties=props,
                            )
                            nodes.append(node)

                            edges.append(
                                GraphEdge(
                                    source_fqn=class_fqn,
                                    target_fqn=fqn,
                                    kind=EdgeKind.CONTAINS,
                                    confidence=Confidence.HIGH,
                                    evidence="tree-sitter",
                                )
                            )

    # -- Call extraction --------------------------------------------------------

    def _extract_calls(
        self,
        body: Node,
        caller_fqn: str,
        namespace: str,
        source: bytes,
        edges: list[GraphEdge],
    ) -> None:
        """Extract method invocations and object creations from a method body."""
        seen_targets: set[str] = set()

        # Method invocations
        for _idx, captures in _query_matches(Q_INVOCATION, body):
            func_node = captures["func"][0]
            call_node = captures["call"][0]

            callee_name = self._resolve_callee_name(
                func_node, source
            )
            if not callee_name:
                continue
            target_fqn = callee_name

            # Deduplicate within the same method
            dedup_key = target_fqn
            if dedup_key in seen_targets:
                continue
            seen_targets.add(dedup_key)

            edges.append(
                GraphEdge(
                    source_fqn=caller_fqn,
                    target_fqn=target_fqn,
                    kind=EdgeKind.CALLS,
                    confidence=Confidence.LOW,
                    evidence="tree-sitter",
                    properties={
                        "line": call_node.start_point[0] + 1,
                    },
                )
            )

        # Object creation: `new Foo()`
        # Try to resolve the type using usings + namespace
        for _idx, captures in _query_matches(Q_OBJECT_CREATION, body):
            type_node = captures["type"][0]
            creation_node = captures["creation"][0]
            type_name = _node_text(type_node, source)
            bare_type = type_name.split("<")[0]

            # Try to resolve to a fully-qualified constructor
            resolved = self._resolve_new_type(
                bare_type, namespace
            )
            target_fqn = f"{resolved}.{bare_type}"

            dedup_key = target_fqn
            if dedup_key in seen_targets:
                continue
            seen_targets.add(dedup_key)

            edges.append(
                GraphEdge(
                    source_fqn=caller_fqn,
                    target_fqn=target_fqn,
                    kind=EdgeKind.CALLS,
                    confidence=Confidence.LOW,
                    evidence="tree-sitter",
                    properties={
                        "line": creation_node.start_point[0] + 1,
                        "is_constructor_call": True,
                    },
                )
            )

    # -- SQL string tagging -----------------------------------------------------

    def _extract_sql_strings(
        self,
        body: Node,
        method_fqn: str,
        source: bytes,
        nodes: list[GraphNode],
    ) -> None:
        """Tag SQL-like string literals found in a method body."""
        sql_strings: list[str] = []

        for q in (Q_STRING, Q_VERBATIM_STRING):
            for _idx, captures in _query_matches(q, body):
                string_node = captures["string"][0]
                text = _node_text(string_node, source)
                # Strip surrounding quotes
                clean = text.strip('"').lstrip("@").strip('"')
                if _SQL_PATTERN.search(clean):
                    sql_strings.append(clean)

        if sql_strings:
            for n in nodes:
                if n.fqn == method_fqn:
                    n.properties["sql_strings"] = sql_strings
                    break

    # -- DI registration extraction ---------------------------------------------

    def _extract_di_registrations(
        self,
        body: Node,
        source: bytes,
    ) -> list[dict[str, str]]:
        """Extract DI service registrations from a method body.

        Detects patterns like:
        - services.AddScoped<IFoo, Bar>()
        - builder.Services.AddTransient<Baz>()
        - services.AddDbContext<AppDbContext>(...)

        Returns a list of registration dicts with keys:
        ``method``, ``interface``, ``implementation``.
        """
        registrations: list[dict[str, str]] = []

        for _idx, captures in _query_matches(Q_INVOCATION, body):
            # Match member access ending with a DI method:
            # e.g. "services.AddScoped<IFoo, Bar>" or "builder.Services.AddTransient<X>"
            # The func_node may be a member_access_expression or generic_name
            # We need the full text including generic args.
            call_text = _node_text(captures["call"][0], source)

            # Find the DI method name in the call text
            method_name: str | None = None
            for dm in _DI_METHODS:
                if dm in call_text:
                    method_name = dm
                    break

            if method_name is None:
                continue

            # Extract generic type arguments from the call
            m = _GENERIC_ARGS_RE.search(call_text)
            if m is None:
                continue

            type_args = [t.strip() for t in m.group(1).split(",")]
            if not type_args:
                continue

            reg: dict[str, str] = {"method": method_name}
            if len(type_args) == 2:
                # AddScoped<IService, ServiceImpl>()
                reg["interface"] = type_args[0]
                reg["implementation"] = type_args[1]
            elif len(type_args) == 1:
                # AddScoped<Service>() — self-registration
                reg["interface"] = type_args[0]
                reg["implementation"] = type_args[0]
            else:
                continue

            registrations.append(reg)

        return registrations

    # -- Helpers ----------------------------------------------------------------

    def _resolve_callee_name(self, func_node: Node, source: bytes) -> str | None:
        """Extract a callee name from an invocation_expression function child.

        Handles:
        - Simple: ``DoSomething()``            -> "DoSomething"
        - Member access: ``_repo.FindById()``  -> "_repo.FindById"
        - Chained: ``a.Query().Where()``       -> "Query.Where" (not full chain)
        - Static: ``CsvConverter.Export()``     -> "CsvConverter.Export"
        - Await: ``await _repo.FindById()``    -> "_repo.FindById"
        """
        if func_node.type == "identifier":
            return _node_text(func_node, source)
        elif func_node.type == "member_access_expression":
            return self._decompose_member_access(
                func_node, source
            )
        elif func_node.type == "generic_name":
            name = func_node.child_by_field_name("name")
            if name:
                return _node_text(name, source)
            return _node_text(func_node, source).split("<")[0]
        elif func_node.type == "member_binding_expression":
            return _node_text(func_node, source)
        return None

    def _decompose_member_access(
        self, node: Node, source: bytes
    ) -> str | None:
        """Decompose a member_access_expression into receiver.method.

        For simple access like ``_repo.FindById``, returns as-is.
        For chained calls like ``_repo.Query().Include().Where``,
        returns only ``Include.Where`` (the last two parts) instead
        of dumping the entire multi-line LINQ chain.
        """
        name_child = node.child_by_field_name("name")
        expr_child = node.child_by_field_name("expression")
        if not name_child:
            return None
        method_name = _node_text(name_child, source)

        if expr_child is None:
            return method_name

        # Simple: _repo.Method or CsvConverter.Export
        if expr_child.type == "identifier":
            receiver = _node_text(expr_child, source)
            return f"{receiver}.{method_name}"

        # Nested member access without invocation: a.b.Method
        if expr_child.type == "member_access_expression":
            inner = expr_child.child_by_field_name("name")
            inner_expr = expr_child.child_by_field_name(
                "expression"
            )
            # If the inner expression is a simple identifier:
            # e.g. x.Customer.FullName -> Customer.FullName
            if inner and inner_expr:
                if inner_expr.type == "identifier":
                    recv = _node_text(inner_expr, source)
                    mid = _node_text(inner, source)
                    return f"{recv}.{mid}.{method_name}"
            if inner:
                return (
                    f"{_node_text(inner, source)}.{method_name}"
                )
            return method_name

        # Chained invocation: prev().Method (LINQ chain)
        # Only keep the method name — the receiver is the
        # result of a previous call, not a named type.
        if expr_child.type == "invocation_expression":
            return None

        # Fallback: keep short, single-line results only
        text = _node_text(node, source)
        if "\n" in text or len(text) > 100:
            return None
        return text

    @staticmethod
    def _resolve_new_type(
        bare_type: str,
        namespace: str,
    ) -> str:
        """Best-effort FQN prefix for a type in a ``new`` expression.

        Returns bare type name so the global resolver in parser.py
        can match it against ALL known classes (not just same-namespace).
        For ``new OrderDetailGot()``, returns ``OrderDetailGot`` so
        the target becomes ``OrderDetailGot.OrderDetailGot`` which
        Strategy 0c in the resolver will match to the correct class.
        """
        if "." in bare_type:
            return bare_type
        return bare_type

    @staticmethod
    def _resolve_base_type_fqn(
        bare_name: str,
        namespace: str,
        usings: list[str],
    ) -> str:
        """Resolve a base-type short name to a fully-qualified name.

        Resolution order, mirroring how other C# resolvers handle imports:

        1. Already-qualified names (``Foo.Bar.Base``) are returned unchanged.
        2. If any ``using X.Y.Z;`` directive's last segment equals the short
           name, treat it as a type alias import and return ``X.Y.Z``
           directly (covers ``using My.App.ExternalBase;``).
        3. Otherwise prefer the first user-land imported namespace (i.e.
           skipping BCL namespaces like ``System.*`` and ``Microsoft.*``)
           as the candidate container: ``using Foo.Bar;`` +
           ``ExternalBase`` yields ``Foo.Bar.ExternalBase``.
        4. Fallback: assume the base type lives in the same namespace as the
           declaring class. This preserves pre-existing behavior for bases
           defined in the declaring file's namespace and is the rule used
           when no user-land using is present. The edge is never dropped.
        """
        if "." in bare_name:
            return bare_name
        # Step 2: alias-style import (`using X.Y.TypeName;`).
        for ns in usings:
            last = ns.rsplit(".", 1)[-1]
            if last == bare_name:
                return ns
        # Step 3: first non-BCL using directive as candidate container.
        for ns in usings:
            if _is_bcl_namespace(ns):
                continue
            return f"{ns}.{bare_name}"
        # Step 4: same-namespace fallback.
        return _make_fqn(namespace, bare_name)

    @staticmethod
    def _looks_like_interface(name: str) -> bool:
        """Heuristic: C# interfaces conventionally start with 'I' + uppercase.

        Examples: IUserService -> True, Item -> False, IEnumerable -> True
        """
        return len(name) >= 2 and name[0] == "I" and name[1].isupper()


# Register the extractor at module level
register_extractor("csharp", CSharpExtractor())
