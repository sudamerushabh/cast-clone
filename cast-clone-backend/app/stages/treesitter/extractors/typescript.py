"""TypeScript/JavaScript tree-sitter extractor.

Parses .ts, .tsx, .js, .jsx files and extracts structural information into
GraphNode and GraphEdge instances. This is Layer 1 (tree-sitter) of the
4-layer parsing strategy -- it produces the structural skeleton that SCIP
and framework plugins refine.

Handles:
  - Imports (ES6 named/default/namespace, CommonJS require)
  - Class declarations (with extends/implements, decorators)
  - Interface declarations
  - Function declarations (named, arrow, exported)
  - Method declarations (inside classes)
  - Method/function calls (unresolved, LOW confidence)
  - Decorators with arguments
  - JSX element references (PascalCase only -- React components)
  - Export tracking (default, named, re-exports)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import structlog
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node, Parser

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.treesitter.extractors import register_extractor

log = structlog.get_logger(__name__)

# Initialize both TypeScript and TSX languages
_TS_LANGUAGE = Language(tstypescript.language_typescript())
_TSX_LANGUAGE = Language(tstypescript.language_tsx())


@dataclass
class _ImportInfo:
    """Parsed import information."""

    kind: str  # "named", "default", "namespace", "commonjs"
    local_name: str
    imported_name: str | None  # None for default/namespace
    module: str


@dataclass
class _DecoratorInfo:
    """Parsed decorator information."""

    name: str
    arguments: list[str] = field(default_factory=list)


def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes from a string literal."""
    if len(s) >= 2 and s[0] in ('"', "'", "`") and s[-1] in ('"', "'", "`"):
        return s[1:-1]
    return s


def _module_path_from_file(file_path: str) -> str:
    """Derive module FQN from file path.

    Example: 'src/user/user.service.ts' -> 'src/user/user.service'
    """
    path = file_path
    for ext in (".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs"):
        if path.endswith(ext):
            path = path[: -len(ext)]
            break
    path = path.replace(os.sep, "/")
    if path.startswith("./"):
        path = path[2:]
    if path.endswith("/index"):
        path = path[: -len("/index")]
    return path


def _module_name_from_path(module_path: str) -> str:
    """Extract short module name from module path.

    Example: 'src/user/user.service' -> 'user.service'
    """
    return module_path.rsplit("/", 1)[-1]


def _is_pascal_case(name: str) -> bool:
    """Check if a name is PascalCase (React component convention)."""
    return bool(name) and name[0].isupper() and not name.isupper()


def _node_text(node: Node) -> str:
    """Get the text content of a tree-sitter node."""
    return node.text.decode("utf-8") if node.text else ""


def _find_child_by_type(node: Node, type_name: str) -> Node | None:
    """Find the first child of a given type."""
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def _find_children_by_type(node: Node, type_name: str) -> list[Node]:
    """Find all children of a given type."""
    return [child for child in node.children if child.type == type_name]


def _find_descendants_by_type(node: Node, type_name: str) -> list[Node]:
    """Find all descendants of a given type (DFS)."""
    results: list[Node] = []
    for child in node.children:
        if child.type == type_name:
            results.append(child)
        results.extend(_find_descendants_by_type(child, type_name))
    return results


def _compute_loc(node: Node) -> int:
    """Compute lines of code for a tree-sitter node."""
    return node.end_point[0] - node.start_point[0] + 1


_COMPLEXITY_NODE_TYPES: set[str] = {
    "if_statement",
    "for_statement",
    "for_in_statement",
    "while_statement",
    "do_statement",
    "catch_clause",
    "ternary_expression",
}


def _compute_complexity(node: Node) -> int:
    """Compute cyclomatic complexity for a function body."""
    complexity = 1

    def _visit(n: Node) -> None:
        nonlocal complexity
        if n.type in _COMPLEXITY_NODE_TYPES:
            complexity += 1
        elif n.type == "switch_case":
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


class TypeScriptExtractor:
    """Extracts structural information from TypeScript/JavaScript files.

    Thread-safe: no mutable state. Each call to extract() is independent.
    """

    def extract(
        self,
        source: bytes,
        file_path: str,
        root_path: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Parse a TypeScript/JavaScript file and return nodes + edges.

        Args:
            source: Raw file bytes.
            file_path: Path relative to root_path (e.g., 'src/app.ts').
            root_path: Absolute path to project root (used for context, not
                       for reading files).

        Returns:
            Tuple of (nodes, edges) extracted from the file.
        """
        log.debug("typescript_extract_start", file_path=file_path)
        is_tsx = file_path.endswith((".tsx", ".jsx"))
        lang = _TSX_LANGUAGE if is_tsx else _TS_LANGUAGE
        parser = Parser(lang)
        tree = parser.parse(source)

        module_path = _module_path_from_file(file_path)
        module_name = _module_name_from_path(module_path)
        language = self._detect_language(file_path)

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # Track context for cross-referencing
        imports = self._extract_imports(tree.root_node)
        exports = self._extract_exports(tree.root_node)
        export_names = {e["name"] for e in exports if "name" in e}

        # --- Extract children first, create MODULE only if file has content ---
        class_fqns: dict[str, str] = {}
        self._extract_classes(
            tree.root_node,
            module_path,
            file_path,
            language,
            export_names,
            nodes,
            edges,
            class_fqns,
            is_tsx,
        )

        self._extract_interfaces(
            tree.root_node,
            module_path,
            file_path,
            language,
            export_names,
            nodes,
        )

        self._extract_functions(
            tree.root_node,
            module_path,
            file_path,
            language,
            export_names,
            nodes,
            edges,
            is_tsx,
        )

        self._extract_arrow_functions(
            tree.root_node,
            module_path,
            file_path,
            language,
            export_names,
            nodes,
            edges,
            is_tsx,
        )

        # --- Create MODULE node only if the file produced children ---
        # Files with zero extracted declarations (e.g. AngularJS scripts
        # with only angular.module() calls) don't get a MODULE node.
        if not nodes:
            return nodes, edges

        module_node = GraphNode(
            fqn=module_path,
            name=module_name,
            kind=NodeKind.MODULE,
            language=language,
            path=file_path,
            line=1,
            end_line=tree.root_node.end_point[0] + 1,
            properties={
                "imports": [
                    {
                        "kind": imp.kind,
                        "local_name": imp.local_name,
                        "module": imp.module,
                    }
                    for imp in imports
                ],
                "exports": exports,
            },
        )
        nodes.append(module_node)

        # --- CONTAINS edges from module to top-level declarations ---
        for n in nodes:
            if n.fqn != module_path and n.fqn.startswith(module_path + "."):
                # Only direct children (no dots after the module prefix)
                suffix = n.fqn[len(module_path) + 1 :]
                if "." not in suffix:
                    edges.append(
                        GraphEdge(
                            source_fqn=module_path,
                            target_fqn=n.fqn,
                            kind=EdgeKind.CONTAINS,
                            confidence=Confidence.HIGH,
                            evidence="tree-sitter",
                        )
                    )

        log.debug(
            "typescript_extract_done",
            file_path=file_path,
            nodes=len(nodes),
            edges=len(edges),
        )

        return nodes, edges

    def _detect_language(self, file_path: str) -> str:
        """Detect language from file extension."""
        if file_path.endswith((".ts", ".tsx")):
            return "typescript"
        return "javascript"

    # -------------------------------------------------------------------
    # Import extraction
    # -------------------------------------------------------------------
    def _extract_imports(self, root: Node) -> list[_ImportInfo]:
        """Extract all import declarations."""
        imports: list[_ImportInfo] = []

        for node in root.children:
            if node.type == "import_statement":
                self._parse_es6_import(node, imports)

        # CommonJS require
        self._extract_commonjs_requires(root, imports)

        return imports

    def _parse_es6_import(self, node: Node, imports: list[_ImportInfo]) -> None:
        """Parse a single ES6 import statement."""
        source_node = _find_child_by_type(node, "string")
        if source_node is None:
            return
        module = _strip_quotes(_node_text(source_node))

        import_clause = _find_child_by_type(node, "import_clause")
        if import_clause is None:
            return

        for child in import_clause.children:
            if child.type == "identifier":
                # Default import: import Foo from 'module'
                imports.append(
                    _ImportInfo(
                        kind="default",
                        local_name=_node_text(child),
                        imported_name=None,
                        module=module,
                    )
                )
            elif child.type == "named_imports":
                # Named imports: import { A, B as C } from 'module'
                for spec in child.children:
                    if spec.type == "import_specifier":
                        name_node = _find_child_by_type(spec, "identifier")
                        if name_node is None:
                            continue
                        imported_name = _node_text(name_node)
                        # Check for alias: import { X as Y }
                        alias_node = None
                        found_as = False
                        for sub in spec.children:
                            if _node_text(sub) == "as":
                                found_as = True
                            elif found_as and sub.type == "identifier":
                                alias_node = sub
                                break
                        local_name = (
                            _node_text(alias_node) if alias_node else imported_name
                        )
                        imports.append(
                            _ImportInfo(
                                kind="named",
                                local_name=local_name,
                                imported_name=imported_name,
                                module=module,
                            )
                        )
            elif child.type == "namespace_import":
                # Namespace import: import * as Foo from 'module'
                id_node = _find_child_by_type(child, "identifier")
                if id_node:
                    imports.append(
                        _ImportInfo(
                            kind="namespace",
                            local_name=_node_text(id_node),
                            imported_name=None,
                            module=module,
                        )
                    )

    def _extract_commonjs_requires(
        self, root: Node, imports: list[_ImportInfo]
    ) -> None:
        """Extract CommonJS require() calls assigned to variables."""
        for node in root.children:
            if node.type not in ("lexical_declaration", "variable_declaration"):
                continue
            for declarator in _find_children_by_type(node, "variable_declarator"):
                name_node = _find_child_by_type(declarator, "identifier")
                value_node = _find_child_by_type(declarator, "call_expression")
                if name_node is None or value_node is None:
                    continue
                func_node = _find_child_by_type(value_node, "identifier")
                if func_node is None or _node_text(func_node) != "require":
                    continue
                args_node = _find_child_by_type(value_node, "arguments")
                if args_node is None:
                    continue
                str_node = _find_child_by_type(args_node, "string")
                if str_node is None:
                    continue
                imports.append(
                    _ImportInfo(
                        kind="commonjs",
                        local_name=_node_text(name_node),
                        imported_name=None,
                        module=_strip_quotes(_node_text(str_node)),
                    )
                )

    # -------------------------------------------------------------------
    # Export extraction
    # -------------------------------------------------------------------
    def _extract_exports(self, root: Node) -> list[dict[str, Any]]:
        """Extract export declarations and build an export manifest."""
        exports: list[dict[str, Any]] = []

        for node in root.children:
            if node.type == "export_statement":
                self._parse_export(node, exports)

        return exports

    def _parse_export(self, node: Node, exports: list[dict[str, Any]]) -> None:
        """Parse a single export statement."""
        text = _node_text(node)
        is_default = "default" in text.split("{")[0].split("(")[0][:30]

        # export default class Foo / export class Foo
        class_decl = _find_child_by_type(node, "class_declaration")
        if class_decl:
            name_node = _find_child_by_type(class_decl, "type_identifier")
            if name_node:
                exports.append(
                    {
                        "name": _node_text(name_node),
                        "kind": "default" if is_default else "named",
                        "type": "class",
                    }
                )
            return

        # export default function foo / export function foo
        func_decl = _find_child_by_type(node, "function_declaration")
        if func_decl:
            name_node = _find_child_by_type(func_decl, "identifier")
            if name_node:
                exports.append(
                    {
                        "name": _node_text(name_node),
                        "kind": "default" if is_default else "named",
                        "type": "function",
                    }
                )
            return

        # export const foo = ...
        lex_decl = _find_child_by_type(node, "lexical_declaration")
        if lex_decl:
            for declarator in _find_children_by_type(lex_decl, "variable_declarator"):
                name_node = _find_child_by_type(declarator, "identifier")
                if name_node:
                    exports.append(
                        {
                            "name": _node_text(name_node),
                            "kind": "named",
                            "type": "const",
                        }
                    )
            return

        # export { foo, bar } or export { foo, bar } from './module'
        export_clause = _find_child_by_type(node, "export_clause")
        if export_clause:
            for spec in _find_children_by_type(export_clause, "export_specifier"):
                name_node = _find_child_by_type(spec, "identifier")
                if name_node:
                    exports.append(
                        {
                            "name": _node_text(name_node),
                            "kind": "named",
                            "type": "re-export",
                        }
                    )

    # -------------------------------------------------------------------
    # Class extraction
    # -------------------------------------------------------------------
    def _extract_classes(
        self,
        root: Node,
        module_path: str,
        file_path: str,
        language: str,
        export_names: set[str],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        class_fqns: dict[str, str],
        is_tsx: bool,
    ) -> None:
        """Extract class declarations from the AST."""
        for node in root.children:
            class_node = None
            is_exported = False
            is_default = False

            if node.type == "class_declaration":
                class_node = node
            elif node.type == "export_statement":
                class_node = _find_child_by_type(node, "class_declaration")
                if class_node:
                    is_exported = True
                    text = _node_text(node)
                    is_default = text.lstrip().startswith("export default")

            if class_node is None:
                continue

            name_node = _find_child_by_type(class_node, "type_identifier")
            if name_node is None:
                continue
            class_name = _node_text(name_node)
            fqn = f"{module_path}.{class_name}"
            class_fqns[class_name] = fqn

            if class_name in export_names:
                is_exported = True

            # Extract decorators -- they can be children of the class_declaration,
            # children of the export_statement, or preceding siblings
            decorators = self._extract_decorators_for_node(
                node if node.type == "export_statement" else class_node,
                root,
            )

            # Extract extends / implements
            extends_name = None
            implements_names: list[str] = []
            heritage = _find_child_by_type(class_node, "class_heritage")
            if heritage:
                extends_clause = _find_child_by_type(heritage, "extends_clause")
                if extends_clause:
                    ext_id = _find_child_by_type(extends_clause, "identifier")
                    if ext_id:
                        extends_name = _node_text(ext_id)

                implements_clause = _find_child_by_type(heritage, "implements_clause")
                if implements_clause:
                    for ti in _find_children_by_type(
                        implements_clause, "type_identifier"
                    ):
                        implements_names.append(_node_text(ti))

            properties: dict[str, Any] = {}
            if decorators:
                properties["annotations"] = [
                    {"name": d.name, "arguments": d.arguments} for d in decorators
                ]
            if is_exported:
                properties["exported"] = True
            if is_default:
                properties["export_kind"] = "default"

            graph_node = GraphNode(
                fqn=fqn,
                name=class_name,
                kind=NodeKind.CLASS,
                language=language,
                path=file_path,
                line=class_node.start_point[0] + 1,
                end_line=class_node.end_point[0] + 1,
                loc=_compute_loc(class_node),
                properties=properties,
            )
            nodes.append(graph_node)

            # INHERITS edge
            if extends_name:
                edges.append(
                    GraphEdge(
                        source_fqn=fqn,
                        target_fqn=f"{module_path}.{extends_name}",
                        kind=EdgeKind.INHERITS,
                        confidence=Confidence.LOW,
                        evidence="tree-sitter",
                    )
                )

            # IMPLEMENTS edges
            for impl_name in implements_names:
                edges.append(
                    GraphEdge(
                        source_fqn=fqn,
                        target_fqn=f"{module_path}.{impl_name}",
                        kind=EdgeKind.IMPLEMENTS,
                        confidence=Confidence.LOW,
                        evidence="tree-sitter",
                    )
                )

            # Extract methods inside the class
            body_node = _find_child_by_type(class_node, "class_body")
            if body_node:
                self._extract_methods(
                    body_node,
                    fqn,
                    file_path,
                    language,
                    nodes,
                    edges,
                    is_tsx,
                )

    # -------------------------------------------------------------------
    # Method extraction (inside classes)
    # -------------------------------------------------------------------
    def _extract_methods(
        self,
        class_body: Node,
        class_fqn: str,
        file_path: str,
        language: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        is_tsx: bool,
    ) -> None:
        """Extract method definitions from a class body."""
        for child in class_body.children:
            if child.type != "method_definition":
                continue

            name_node = _find_child_by_type(child, "property_identifier")
            if name_node is None:
                continue
            method_name = _node_text(name_node)

            # Skip constructor for node creation (but still extract calls)
            if method_name == "constructor":
                body = _find_child_by_type(child, "statement_block")
                if body:
                    self._extract_calls_from_body(
                        body, f"{class_fqn}.constructor", edges
                    )
                continue

            fqn = f"{class_fqn}.{method_name}"

            # Decorators on methods are siblings in class_body
            decorators = self._extract_decorators_for_node(child, class_body)

            properties: dict[str, Any] = {}
            if decorators:
                properties["annotations"] = [
                    {"name": d.name, "arguments": d.arguments} for d in decorators
                ]

            # Visibility
            visibility = "public"
            for mod_child in child.children:
                if mod_child.type == "accessibility_modifier":
                    visibility = _node_text(mod_child)
                    break

            graph_node = GraphNode(
                fqn=fqn,
                name=method_name,
                kind=NodeKind.FUNCTION,
                language=language,
                path=file_path,
                line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                loc=_compute_loc(child),
                complexity=_compute_complexity(child),
                visibility=visibility,
                properties=properties,
            )
            nodes.append(graph_node)

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

            # Extract calls from method body
            body = _find_child_by_type(child, "statement_block")
            if body:
                self._extract_calls_from_body(body, fqn, edges)

            # Extract JSX elements if TSX
            if is_tsx and body:
                self._extract_jsx_from_body(body, graph_node)

    # -------------------------------------------------------------------
    # Function extraction (top-level named functions)
    # -------------------------------------------------------------------
    def _extract_functions(
        self,
        root: Node,
        module_path: str,
        file_path: str,
        language: str,
        export_names: set[str],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        is_tsx: bool,
    ) -> None:
        """Extract top-level function declarations."""
        for node in root.children:
            func_node = None
            is_exported = False
            is_default = False

            if node.type == "function_declaration":
                func_node = node
            elif node.type == "export_statement":
                func_node = _find_child_by_type(node, "function_declaration")
                if func_node:
                    is_exported = True
                    text = _node_text(node)
                    is_default = text.lstrip().startswith("export default")

            if func_node is None:
                continue

            name_node = _find_child_by_type(func_node, "identifier")
            if name_node is None:
                continue
            func_name = _node_text(name_node)
            fqn = f"{module_path}.{func_name}"

            if func_name in export_names:
                is_exported = True

            properties: dict[str, Any] = {}
            if is_exported:
                properties["exported"] = True
            if is_default:
                properties["export_kind"] = "default"

            graph_node = GraphNode(
                fqn=fqn,
                name=func_name,
                kind=NodeKind.FUNCTION,
                language=language,
                path=file_path,
                line=func_node.start_point[0] + 1,
                end_line=func_node.end_point[0] + 1,
                loc=_compute_loc(func_node),
                complexity=_compute_complexity(func_node),
                properties=properties,
            )
            nodes.append(graph_node)

            # Extract calls from function body
            body = _find_child_by_type(func_node, "statement_block")
            if body:
                self._extract_calls_from_body(body, fqn, edges)

            # Extract JSX elements if TSX
            if is_tsx:
                self._extract_jsx_from_body(func_node, graph_node)

    # -------------------------------------------------------------------
    # Arrow function extraction (top-level const/let)
    # -------------------------------------------------------------------
    def _extract_arrow_functions(
        self,
        root: Node,
        module_path: str,
        file_path: str,
        language: str,
        export_names: set[str],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        is_tsx: bool,
    ) -> None:
        """Extract top-level arrow functions assigned to const/let/var."""
        for node in root.children:
            lex_node = None
            is_exported = False

            if node.type in ("lexical_declaration", "variable_declaration"):
                lex_node = node
            elif node.type == "export_statement":
                lex_node = _find_child_by_type(node, "lexical_declaration")
                if lex_node is None:
                    lex_node = _find_child_by_type(node, "variable_declaration")
                if lex_node:
                    is_exported = True

            if lex_node is None:
                continue

            for declarator in _find_children_by_type(lex_node, "variable_declarator"):
                name_node = _find_child_by_type(declarator, "identifier")
                if name_node is None:
                    continue

                # Check if the value is an arrow function
                arrow_node = _find_child_by_type(declarator, "arrow_function")
                if arrow_node is None:
                    continue

                func_name = _node_text(name_node)
                fqn = f"{module_path}.{func_name}"

                if func_name in export_names:
                    is_exported = True

                properties: dict[str, Any] = {}
                if is_exported:
                    properties["exported"] = True

                graph_node = GraphNode(
                    fqn=fqn,
                    name=func_name,
                    kind=NodeKind.FUNCTION,
                    language=language,
                    path=file_path,
                    line=declarator.start_point[0] + 1,
                    end_line=declarator.end_point[0] + 1,
                    loc=_compute_loc(arrow_node),
                    complexity=_compute_complexity(arrow_node),
                    properties=properties,
                )
                nodes.append(graph_node)

                # Extract calls from arrow function body
                body = _find_child_by_type(arrow_node, "statement_block")
                if body:
                    self._extract_calls_from_body(body, fqn, edges)
                else:
                    # Single expression body (no braces)
                    self._extract_calls_from_body(arrow_node, fqn, edges)

                # Extract JSX elements if TSX
                if is_tsx:
                    self._extract_jsx_from_body(arrow_node, graph_node)

    # -------------------------------------------------------------------
    # Interface extraction
    # -------------------------------------------------------------------
    def _extract_interfaces(
        self,
        root: Node,
        module_path: str,
        file_path: str,
        language: str,
        export_names: set[str],
        nodes: list[GraphNode],
    ) -> None:
        """Extract interface declarations."""
        for node in root.children:
            iface_node = None
            is_exported = False

            if node.type == "interface_declaration":
                iface_node = node
            elif node.type == "export_statement":
                iface_node = _find_child_by_type(node, "interface_declaration")
                if iface_node:
                    is_exported = True

            if iface_node is None:
                continue

            name_node = _find_child_by_type(iface_node, "type_identifier")
            if name_node is None:
                continue
            iface_name = _node_text(name_node)
            fqn = f"{module_path}.{iface_name}"

            if iface_name in export_names:
                is_exported = True

            properties: dict[str, Any] = {}
            if is_exported:
                properties["exported"] = True

            graph_node = GraphNode(
                fqn=fqn,
                name=iface_name,
                kind=NodeKind.INTERFACE,
                language=language,
                path=file_path,
                line=iface_node.start_point[0] + 1,
                end_line=iface_node.end_point[0] + 1,
                loc=_compute_loc(iface_node),
                properties=properties,
            )
            nodes.append(graph_node)

    # -------------------------------------------------------------------
    # Call extraction
    # -------------------------------------------------------------------
    def _extract_calls_from_body(
        self,
        body: Node,
        caller_fqn: str,
        edges: list[GraphEdge],
    ) -> None:
        """Extract function/method calls from a code block."""
        call_nodes = _find_descendants_by_type(body, "call_expression")

        for call_node in call_nodes:
            func_part = _find_child_by_type(call_node, "member_expression")
            if func_part:
                # obj.method() or this.service.method()
                prop = _find_child_by_type(func_part, "property_identifier")
                if prop:
                    callee_name = _node_text(prop)
                    edges.append(
                        GraphEdge(
                            source_fqn=caller_fqn,
                            target_fqn=callee_name,
                            kind=EdgeKind.CALLS,
                            confidence=Confidence.LOW,
                            evidence="tree-sitter",
                            properties={"line": call_node.start_point[0] + 1},
                        )
                    )
                continue

            func_id = _find_child_by_type(call_node, "identifier")
            if func_id:
                callee_name = _node_text(func_id)
                # Skip common built-ins that are not interesting
                if callee_name in ("require", "import"):
                    continue
                edges.append(
                    GraphEdge(
                        source_fqn=caller_fqn,
                        target_fqn=callee_name,
                        kind=EdgeKind.CALLS,
                        confidence=Confidence.LOW,
                        evidence="tree-sitter",
                        properties={"line": call_node.start_point[0] + 1},
                    )
                )

    # -------------------------------------------------------------------
    # JSX extraction
    # -------------------------------------------------------------------
    def _extract_jsx_from_body(
        self,
        body: Node,
        owner_node: GraphNode,
    ) -> None:
        """Extract JSX component references (PascalCase only)."""
        jsx_elements: list[dict[str, Any]] = []
        seen: set[str] = set()

        for type_name in ("jsx_opening_element", "jsx_self_closing_element"):
            for jsx_node in _find_descendants_by_type(body, type_name):
                name_node = _find_child_by_type(jsx_node, "identifier")
                if name_node is None:
                    continue
                name = _node_text(name_node)
                if _is_pascal_case(name) and name not in seen:
                    seen.add(name)
                    jsx_elements.append(
                        {
                            "name": name,
                            "line": jsx_node.start_point[0] + 1,
                        }
                    )

        if jsx_elements:
            owner_node.properties["jsx_elements"] = jsx_elements

    # -------------------------------------------------------------------
    # Decorator extraction
    # -------------------------------------------------------------------
    def _extract_decorators_for_node(
        self,
        node: Node,
        parent: Node,
    ) -> list[_DecoratorInfo]:
        """Extract decorators attached to a class or method node.

        In tree-sitter for TypeScript, decorators can be:
        - Direct children of the node (e.g., decorators on class_declaration)
        - Direct children of export_statement wrapping a class
        - Preceding siblings in the parent (e.g., method decorators in class_body)
        """
        decorators: list[_DecoratorInfo] = []

        # Decorators can be direct children of the node
        for child in node.children:
            if child.type == "decorator":
                dec = self._parse_decorator(child)
                if dec:
                    decorators.append(dec)

        # For export statements, decorators may be children of the
        # inner declaration too
        if node.type == "export_statement":
            for child in node.children:
                if child.type in ("class_declaration", "function_declaration"):
                    for sub in child.children:
                        if sub.type == "decorator":
                            dec = self._parse_decorator(sub)
                            if dec:
                                decorators.append(dec)

        # Also check preceding siblings (method decorators in class_body
        # are siblings preceding the method_definition)
        if parent is not None:
            idx = None
            for i, sibling in enumerate(parent.children):
                if sibling.id == node.id:
                    idx = i
                    break
            if idx is not None:
                j = idx - 1
                while j >= 0 and parent.children[j].type == "decorator":
                    dec = self._parse_decorator(parent.children[j])
                    if dec:
                        decorators.insert(0, dec)
                    j -= 1

        return decorators

    def _parse_decorator(self, node: Node) -> _DecoratorInfo | None:
        """Parse a single decorator node into name + arguments."""
        # Decorator with call: @Foo('bar')
        call_expr = _find_child_by_type(node, "call_expression")
        if call_expr:
            func = _find_child_by_type(call_expr, "identifier")
            if func is None:
                return None
            name = _node_text(func)
            args = self._extract_decorator_args(call_expr)
            return _DecoratorInfo(name=name, arguments=args)

        # Decorator without call: @Injectable
        id_node = _find_child_by_type(node, "identifier")
        if id_node:
            return _DecoratorInfo(name=_node_text(id_node), arguments=[])

        return None

    def _extract_decorator_args(self, call_node: Node) -> list[str]:
        """Extract string arguments from a decorator call."""
        args: list[str] = []
        args_node = _find_child_by_type(call_node, "arguments")
        if args_node is None:
            return args

        for child in args_node.children:
            if child.type == "string":
                args.append(_strip_quotes(_node_text(child)))
            elif child.type == "identifier":
                args.append(_node_text(child))

        return args


# Register for both TypeScript and JavaScript
_extractor = TypeScriptExtractor()
register_extractor("typescript", _extractor)
register_extractor("javascript", _extractor)
