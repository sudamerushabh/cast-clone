# M4d: Python Tree-sitter Extractor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python-language tree-sitter extractor that parses `.py` source files and produces `GraphNode` + `GraphEdge` lists representing modules, classes, functions, fields, imports, calls, inheritance, and decorators.

**Architecture:** Single `PythonExtractor` class with an `extract(source, file_path, root_path)` method. Uses `tree-sitter-python` grammar (v0.25+) with S-expression queries to extract structural and call-graph information from Python source. FQNs derived from file path relative to root (dots instead of slashes, no `.py` extension). Decorators stored in `properties["annotations"]`. SQL-like string literals tagged for downstream sqlglot processing.

**Tech Stack:** Python 3.12, tree-sitter (v0.25+), tree-sitter-python, pytest

**Dependencies:** M1 foundation models (`GraphNode`, `GraphEdge`, `NodeKind`, `EdgeKind`, `Confidence` from `app.models`)

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       └── treesitter/
│           ├── __init__.py              # CREATE (empty)
│           └── extractors/
│               ├── __init__.py          # CREATE (empty)
│               └── python.py            # CREATE — PythonExtractor
├── tests/
│   ├── unit/
│   │   └── test_python_extractor.py     # CREATE — 10 test cases
│   └── fixtures/
│       └── python-sample/
│           └── mypackage/
│               ├── __init__.py          # CREATE (empty)
│               └── service.py           # CREATE — full integration fixture
└── pyproject.toml                       # MODIFY — add tree-sitter-python dependency
```

---

## Prerequisites

- [ ] **Step 0a: Add tree-sitter-python dependency**

```bash
cd cast-clone-backend && uv add tree-sitter tree-sitter-python
```

- [ ] **Step 0b: Create directory structure**

```bash
cd cast-clone-backend
mkdir -p app/stages/treesitter/extractors
touch app/stages/__init__.py
touch app/stages/treesitter/__init__.py
touch app/stages/treesitter/extractors/__init__.py
mkdir -p tests/unit
mkdir -p tests/fixtures/python-sample/mypackage
touch tests/fixtures/python-sample/mypackage/__init__.py
```

- [ ] **Step 0c: Verify tree-sitter-python works**

```bash
cd cast-clone-backend && uv run python -c "
import tree_sitter_python as tspython
from tree_sitter import Language, Parser
PY = Language(tspython.language())
parser = Parser(PY)
tree = parser.parse(b'class Foo: pass')
print(tree.root_node.sexp())
print('OK')
"
```

Expected: S-expression output containing `class_definition` and "OK".

---

## Task 1: FQN Helper and Module Node Extraction

**Files:**
- Create: `app/stages/treesitter/extractors/python.py`
- Create: `tests/unit/test_python_extractor.py`

### What this task covers

The `PythonExtractor` class skeleton, FQN derivation from file paths, and MODULE node creation for every file processed.

FQN derivation rules:
- `root_path="/code"`, `file_path="/code/mypackage/service.py"` -> module FQN = `mypackage.service`
- `root_path="/code"`, `file_path="/code/mypackage/__init__.py"` -> module FQN = `mypackage`
- Strips `.py` extension, replaces `/` with `.`, removes leading dots

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_python_extractor.py
import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.treesitter.extractors.python import PythonExtractor


@pytest.fixture
def extractor():
    return PythonExtractor()


class TestFQNDerivation:
    """Task 1: FQN derivation and MODULE node creation."""

    def test_module_fqn_from_file_path(self, extractor):
        source = b"x = 1\n"
        nodes, edges = extractor.extract(source, "/code/mypackage/service.py", "/code")
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1
        assert module_nodes[0].fqn == "mypackage.service"
        assert module_nodes[0].name == "service"
        assert module_nodes[0].language == "python"
        assert module_nodes[0].path == "/code/mypackage/service.py"

    def test_module_fqn_init_file(self, extractor):
        source = b""
        nodes, edges = extractor.extract(
            source, "/code/mypackage/__init__.py", "/code"
        )
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1
        assert module_nodes[0].fqn == "mypackage"

    def test_module_fqn_top_level_file(self, extractor):
        source = b"pass\n"
        nodes, edges = extractor.extract(source, "/code/main.py", "/code")
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert module_nodes[0].fqn == "main"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_python_extractor.py::TestFQNDerivation -v`
Expected: FAIL (ImportError -- module doesn't exist)

- [ ] **Step 3: Implement FQN helper and extract skeleton**

```python
# app/stages/treesitter/extractors/python.py
"""Python tree-sitter extractor.

Parses Python source files into GraphNode and GraphEdge lists using
tree-sitter-python S-expression queries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Tree

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode

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
        tree = self._parser.parse(source)
        module_fqn = _derive_module_fqn(file_path, root_path)
        module_name = module_fqn.rsplit(".", 1)[-1] if "." in module_fqn else module_fqn

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # MODULE node for the file itself
        nodes.append(
            GraphNode(
                fqn=module_fqn,
                name=module_name,
                kind=NodeKind.MODULE,
                language="python",
                path=file_path,
                line=1,
            )
        )

        # Extract each category
        self._extract_imports(tree, source, module_fqn, nodes, edges)
        self._extract_classes(tree, source, file_path, module_fqn, nodes, edges)
        self._extract_module_functions(tree, source, file_path, module_fqn, nodes, edges)
        self._extract_call_edges(tree, source, module_fqn, nodes, edges)
        self._extract_sql_strings(tree, source, module_fqn, nodes, edges)

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
        query = PY_LANGUAGE.query("(class_definition) @class")
        matches = query.matches(tree.root_node)

        for _pattern_idx, captures in matches:
            class_node = captures["class"]
            if isinstance(class_node, list):
                class_node = class_node[0]

            # Only extract top-level and first-level nested classes
            parent = class_node.parent
            if parent and parent.type == "block":
                grandparent = parent.parent
                if grandparent and grandparent.type == "class_definition":
                    # Nested class — compute FQN relative to outer class
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
                    # Inside a function or other non-class scope — skip
                    continue

            self._process_class(
                class_node, source, file_path, module_fqn, nodes, edges
            )

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
            self._extract_methods(
                body_node, source, file_path, class_fqn, nodes, edges
            )
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
                            sub, source, file_path, class_fqn, nodes, edges,
                            is_method=True,
                            decorator_parent=child,
                        )
                        break
            elif child.type == "function_definition":
                self._process_function(
                    child, source, file_path, class_fqn, nodes, edges,
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
                            sub, source, file_path, module_fqn, nodes, edges,
                            is_method=False,
                            decorator_parent=child,
                        )
                        break
            elif child.type == "function_definition":
                self._process_function(
                    child, source, file_path, module_fqn, nodes, edges,
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
            if child.type in ("identifier",):
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
                        if (
                            obj
                            and attr
                            and _node_text(obj, source) == "self"
                        ):
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
            elif child.type in ("block", "if_statement", "for_statement",
                                "try_statement", "with_statement"):
                self._walk_for_self_assignments(
                    child, source, file_path, class_fqn, nodes, edges, seen
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

        Example: `name: str = "default"` or `count = 0` in a class body.
        """
        for child in body_node.children:
            field_name: str | None = None
            field_type: str | None = None
            line = child.start_point[0] + 1

            if child.type == "expression_statement":
                expr = child.children[0] if child.children else None
                if expr and expr.type == "assignment":
                    left = expr.child_by_field_name("left")
                    if left and left.type == "identifier":
                        field_name = _node_text(left, source)
                elif expr and expr.type == "type_alias_statement":
                    continue

            elif child.type == "type_alias_statement":
                # type X = ... (Python 3.12)
                continue

            # Annotated assignment: name: str = "default" or name: str
            if child.type == "expression_statement":
                expr = child.children[0] if child.children else None
                if expr is None:
                    continue
                # Check for bare annotation (x: int) which is also expression_statement
                # containing a type node
                if expr.type == "type":
                    # annotated variable without assignment
                    for sub in expr.children:
                        if sub.type == "identifier":
                            field_name = _node_text(sub, source)
                            break
                    type_node = expr.child_by_field_name("type")
                    if type_node:
                        field_type = _node_text(type_node, source)

            if field_name is None and child.type == "expression_statement":
                # Check for annotated assignments
                pass

            if field_name:
                field_fqn = f"{class_fqn}.{field_name}"
                props: dict[str, Any] = {}
                if field_type:
                    props["type_annotation"] = field_type
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
        # Build a map of function FQNs defined in this file for caller resolution
        func_fqns: dict[tuple[int, int], str] = {}
        for n in nodes:
            if n.kind == NodeKind.FUNCTION and n.line is not None:
                func_fqns[(n.line, 0)] = n.fqn

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
            # Call at module level — caller is the module
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
        query = PY_LANGUAGE.query("(string) @str")
        matches = query.matches(tree.root_node)
        for _idx, captures in matches:
            str_node = captures["str"]
            if isinstance(str_node, list):
                str_node = str_node[0]
            text = _node_text(str_node, source)
            # Strip quotes
            stripped = text.strip("\"'").strip()
            # Also handle triple-quoted strings
            for prefix in ('"""', "'''", 'f"""', "f'''", 'r"""', "r'''"):
                if stripped.startswith(prefix[1:]):
                    stripped = stripped[len(prefix) - 1:]
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_python_extractor.py::TestFQNDerivation -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/ tests/unit/test_python_extractor.py && git commit -m "feat(extractor): add PythonExtractor skeleton with FQN derivation and MODULE node creation"
```

---

## Task 2: Class Extraction with Bases and Decorators

**Files:**
- Modify: `tests/unit/test_python_extractor.py`

### What this task covers

Class definitions with base classes creating INHERITS edges, decorators stored in `properties["annotations"]`, and CONTAINS edges from module to class.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_python_extractor.py`:

```python
class TestClassExtraction:
    """Task 2: Class definitions, inheritance, and decorators."""

    def test_class_with_bases(self, extractor):
        source = b"""\
class Animal:
    pass

class Dog(Animal, Serializable):
    pass
"""
        nodes, edges = extractor.extract(source, "/code/models.py", "/code")

        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        assert len(class_nodes) == 2
        dog = next(n for n in class_nodes if n.name == "Dog")
        assert dog.fqn == "models.Dog"
        assert dog.language == "python"
        assert dog.line is not None

        inherits = [e for e in edges if e.kind == EdgeKind.INHERITS]
        assert len(inherits) == 2
        targets = {e.target_fqn for e in inherits}
        assert "Animal" in targets
        assert "Serializable" in targets
        for e in inherits:
            assert e.source_fqn == "models.Dog"
            assert e.confidence == Confidence.LOW

    def test_class_with_decorators(self, extractor):
        source = b"""\
@dataclass
@frozen
class Config:
    name: str
"""
        nodes, edges = extractor.extract(source, "/code/config.py", "/code")
        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        assert len(class_nodes) == 1
        cfg = class_nodes[0]
        assert cfg.fqn == "config.Config"
        assert "dataclass" in cfg.properties["annotations"]
        assert "frozen" in cfg.properties["annotations"]

    def test_class_contains_edge(self, extractor):
        source = b"""\
class Foo:
    pass
"""
        nodes, edges = extractor.extract(source, "/code/foo.py", "/code")
        contains = [
            e for e in edges
            if e.kind == EdgeKind.CONTAINS
            and e.source_fqn == "foo"
            and e.target_fqn == "foo.Foo"
        ]
        assert len(contains) == 1
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_python_extractor.py::TestClassExtraction -v`
Expected: PASS (3 tests) — implementation already done in Task 1.

- [ ] **Step 3: Commit (if any fixes were needed)**

```bash
cd cast-clone-backend && git add -u && git commit -m "test(extractor): add class extraction tests with bases and decorators"
```

---

## Task 3: Method and Module-Level Function Extraction

**Files:**
- Modify: `tests/unit/test_python_extractor.py`

### What this task covers

Methods inside classes (with `self` skipped in parameters), module-level functions, type annotations on parameters and return types, decorator storage, and CONTAINS edges from class/module to function.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_python_extractor.py`:

```python
class TestFunctionExtraction:
    """Task 3: Methods and module-level functions."""

    def test_method_with_type_hints(self, extractor):
        source = b"""\
class UserService:
    def create_user(self, name: str, age: int) -> bool:
        pass
"""
        nodes, edges = extractor.extract(source, "/code/svc.py", "/code")
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) == 1
        method = func_nodes[0]
        assert method.fqn == "svc.UserService.create_user"
        assert method.name == "create_user"
        assert method.properties.get("is_method") is True
        assert method.properties.get("return_type") == "bool"
        params = method.properties.get("params", [])
        assert len(params) == 2  # self is excluded
        assert params[0]["name"] == "name"
        assert params[0]["type"] == "str"
        assert params[1]["name"] == "age"
        assert params[1]["type"] == "int"

    def test_method_with_decorators(self, extractor):
        source = b"""\
class Router:
    @app.route('/users')
    def get_users(self):
        pass

    @staticmethod
    def helper():
        pass
"""
        nodes, edges = extractor.extract(source, "/code/router.py", "/code")
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) == 2

        get_users = next(n for n in func_nodes if n.name == "get_users")
        assert "app.route('/users')" in get_users.properties["annotations"]

        helper = next(n for n in func_nodes if n.name == "helper")
        assert "staticmethod" in helper.properties["annotations"]

    def test_module_level_function(self, extractor):
        source = b"""\
def top_level_func(x: int) -> str:
    return str(x)

class Foo:
    def method(self):
        pass
"""
        nodes, edges = extractor.extract(source, "/code/util.py", "/code")
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) == 2

        top = next(n for n in func_nodes if n.name == "top_level_func")
        assert top.fqn == "util.top_level_func"
        # Module-level functions should NOT have is_method
        assert top.properties.get("is_method") is None

        # CONTAINS edge from module to function
        contains = [
            e for e in edges
            if e.kind == EdgeKind.CONTAINS
            and e.source_fqn == "util"
            and e.target_fqn == "util.top_level_func"
        ]
        assert len(contains) == 1

    def test_decorated_module_function(self, extractor):
        source = b"""\
@click.command()
def main():
    pass
"""
        nodes, edges = extractor.extract(source, "/code/cli.py", "/code")
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) == 1
        assert "click.command()" in func_nodes[0].properties["annotations"]
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_python_extractor.py::TestFunctionExtraction -v`
Expected: PASS (4 tests) — implementation already done in Task 1.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add -u && git commit -m "test(extractor): add method and module-level function extraction tests"
```

---

## Task 4: Import Extraction

**Files:**
- Modify: `tests/unit/test_python_extractor.py`

### What this task covers

All import forms: `import X`, `from X import Y`, `from X import Y as Z`, `import X as Z`. Each creates an IMPORTS edge from the module to the imported module.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_python_extractor.py`:

```python
class TestImportExtraction:
    """Task 4: Import statements -> IMPORTS edges."""

    def test_import_statement(self, extractor):
        source = b"""\
import os
import sys
"""
        nodes, edges = extractor.extract(source, "/code/mod.py", "/code")
        imports = [e for e in edges if e.kind == EdgeKind.IMPORTS]
        targets = {e.target_fqn for e in imports}
        assert "os" in targets
        assert "sys" in targets
        for e in imports:
            assert e.source_fqn == "mod"

    def test_from_import(self, extractor):
        source = b"""\
from os.path import join
from collections import defaultdict, OrderedDict
"""
        nodes, edges = extractor.extract(source, "/code/mod.py", "/code")
        imports = [e for e in edges if e.kind == EdgeKind.IMPORTS]
        targets = {e.target_fqn for e in imports}
        assert "os.path" in targets
        assert "collections" in targets

    def test_aliased_import(self, extractor):
        source = b"""\
import numpy as np
from pandas import DataFrame as DF
"""
        nodes, edges = extractor.extract(source, "/code/mod.py", "/code")
        imports = [e for e in edges if e.kind == EdgeKind.IMPORTS]
        targets = {e.target_fqn for e in imports}
        assert "numpy" in targets
        assert "pandas" in targets
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_python_extractor.py::TestImportExtraction -v`
Expected: PASS (3 tests) — implementation already done in Task 1.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add -u && git commit -m "test(extractor): add import extraction tests for all import forms"
```

---

## Task 5: Function Call Extraction

**Files:**
- Modify: `tests/unit/test_python_extractor.py`

### What this task covers

Function and method calls create CALLS edges with LOW confidence. The caller is the enclosing function, the callee is the unresolved name (e.g. `obj.method`, `func`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_python_extractor.py`:

```python
class TestCallExtraction:
    """Task 5: Function/method calls -> CALLS edges."""

    def test_simple_function_call(self, extractor):
        source = b"""\
def caller():
    result = helper()
    return result

def helper():
    pass
"""
        nodes, edges = extractor.extract(source, "/code/mod.py", "/code")
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert len(calls) >= 1
        helper_call = [e for e in calls if e.target_fqn == "helper"]
        assert len(helper_call) == 1
        assert helper_call[0].source_fqn == "mod.caller"
        assert helper_call[0].confidence == Confidence.LOW

    def test_method_call_on_object(self, extractor):
        source = b"""\
class Service:
    def process(self):
        self.db.execute("query")
        logger.info("done")
"""
        nodes, edges = extractor.extract(source, "/code/svc.py", "/code")
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        callee_names = {e.target_fqn for e in calls}
        assert "self.db.execute" in callee_names
        assert "logger.info" in callee_names
        for call in calls:
            if call.target_fqn in ("self.db.execute", "logger.info"):
                assert call.source_fqn == "svc.Service.process"

    def test_call_at_module_level(self, extractor):
        source = b"""\
setup()
"""
        nodes, edges = extractor.extract(source, "/code/mod.py", "/code")
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        setup_calls = [e for e in calls if e.target_fqn == "setup"]
        assert len(setup_calls) == 1
        assert setup_calls[0].source_fqn == "mod"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_python_extractor.py::TestCallExtraction -v`
Expected: PASS (3 tests) — implementation already done in Task 1.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add -u && git commit -m "test(extractor): add function call extraction tests"
```

---

## Task 6: Class Field Extraction

**Files:**
- Modify: `tests/unit/test_python_extractor.py`

### What this task covers

Fields from `self.x = ...` in `__init__` and class-body assignments. Each creates a FIELD node and CONTAINS edge from the class.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_python_extractor.py`:

```python
class TestFieldExtraction:
    """Task 6: self.x = ... and class-body fields -> FIELD nodes."""

    def test_init_fields(self, extractor):
        source = b"""\
class User:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age
        self._active = True
"""
        nodes, edges = extractor.extract(source, "/code/user.py", "/code")
        field_nodes = [n for n in nodes if n.kind == NodeKind.FIELD]
        field_names = {n.name for n in field_nodes}
        assert "name" in field_names
        assert "age" in field_names
        assert "_active" in field_names

        for fn in field_nodes:
            assert fn.fqn.startswith("user.User.")
            # CONTAINS edge from class to field
            contains = [
                e for e in edges
                if e.kind == EdgeKind.CONTAINS
                and e.target_fqn == fn.fqn
                and e.source_fqn == "user.User"
            ]
            assert len(contains) == 1

    def test_class_body_fields(self, extractor):
        source = b"""\
class Config:
    DEBUG = False
    MAX_RETRIES = 3
"""
        nodes, edges = extractor.extract(source, "/code/cfg.py", "/code")
        field_nodes = [n for n in nodes if n.kind == NodeKind.FIELD]
        field_names = {n.name for n in field_nodes}
        assert "DEBUG" in field_names
        assert "MAX_RETRIES" in field_names

    def test_no_duplicate_fields(self, extractor):
        source = b"""\
class Foo:
    def __init__(self):
        self.x = 1
        self.x = 2
"""
        nodes, edges = extractor.extract(source, "/code/foo.py", "/code")
        field_nodes = [n for n in nodes if n.kind == NodeKind.FIELD]
        assert len(field_nodes) == 1
        assert field_nodes[0].name == "x"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_python_extractor.py::TestFieldExtraction -v`
Expected: PASS (3 tests) — implementation already done in Task 1.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add -u && git commit -m "test(extractor): add class field extraction tests"
```

---

## Task 7: SQL String Detection

**Files:**
- Modify: `tests/unit/test_python_extractor.py`

### What this task covers

String literals matching SQL patterns are tagged in the enclosing function's `properties["sql_strings"]` for downstream sqlglot processing.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_python_extractor.py`:

```python
class TestSQLStringDetection:
    """Task 7: SQL-like string literals tagged on enclosing function."""

    def test_sql_string_detected(self, extractor):
        source = b'''\
class Repository:
    def find_users(self):
        query = "SELECT id, name FROM users WHERE active = 1"
        return self.execute(query)
'''
        nodes, edges = extractor.extract(source, "/code/repo.py", "/code")
        func = next(
            n for n in nodes
            if n.kind == NodeKind.FUNCTION and n.name == "find_users"
        )
        sql_strings = func.properties.get("sql_strings", [])
        assert len(sql_strings) >= 1
        assert any("SELECT" in s["text"] and "FROM" in s["text"] for s in sql_strings)

    def test_non_sql_string_not_tagged(self, extractor):
        source = b'''\
def greet():
    return "Hello, world!"
'''
        nodes, edges = extractor.extract(source, "/code/greet.py", "/code")
        func = next(n for n in nodes if n.kind == NodeKind.FUNCTION and n.name == "greet")
        assert func.properties.get("sql_strings") is None

    def test_triple_quoted_sql(self, extractor):
        source = b"""\
def get_report():
    sql = \"\"\"
        SELECT u.name, COUNT(o.id)
        FROM users u
        JOIN orders o ON o.user_id = u.id
        GROUP BY u.name
    \"\"\"
    return execute(sql)
"""
        nodes, edges = extractor.extract(source, "/code/report.py", "/code")
        func = next(n for n in nodes if n.kind == NodeKind.FUNCTION and n.name == "get_report")
        sql_strings = func.properties.get("sql_strings", [])
        assert len(sql_strings) >= 1
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_python_extractor.py::TestSQLStringDetection -v`
Expected: PASS (3 tests) — implementation already done in Task 1.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add -u && git commit -m "test(extractor): add SQL string detection tests"
```

---

## Task 8: Full Integration Test

**Files:**
- Create: `tests/fixtures/python-sample/mypackage/service.py`
- Modify: `tests/unit/test_python_extractor.py`

### What this task covers

A realistic Python file exercising all features: imports, decorated class with bases, methods with type hints, `__init__` fields, module-level function, function calls, and SQL strings. Verifies the full extraction pipeline end-to-end.

- [ ] **Step 1: Create the fixture file**

```python
# tests/fixtures/python-sample/mypackage/service.py
"""User service module."""

import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class BaseService:
    """Abstract base for all services."""

    def __init__(self, db: Session):
        self.db = db


@dataclass
class UserService(BaseService):
    """Manages user operations."""

    DEFAULT_PAGE_SIZE = 20

    def __init__(self, db: Session, cache: Optional[object] = None):
        super().__init__(db)
        self.cache = cache
        self._initialized = True

    def find_by_email(self, email: str) -> Optional[dict]:
        """Find a user by email address."""
        query = "SELECT id, name, email FROM users WHERE email = :email"
        result = self.db.execute(query, {"email": email})
        logger.info("Looked up user by email")
        return result.first()

    def count_active(self) -> int:
        sql = "SELECT COUNT(*) FROM users WHERE active = 1 AND deleted_at IS NULL"
        return self.db.execute(sql).scalar()

    @staticmethod
    def validate_email(email: str) -> bool:
        return "@" in email


def create_service(db: Session) -> UserService:
    """Factory function for UserService."""
    return UserService(db)
```

- [ ] **Step 2: Write the integration test**

Add to `tests/unit/test_python_extractor.py`:

```python
from pathlib import Path


class TestFullIntegration:
    """Task 8: End-to-end integration test with realistic fixture."""

    @pytest.fixture
    def fixture_source(self):
        fixture_path = (
            Path(__file__).parent.parent
            / "fixtures"
            / "python-sample"
            / "mypackage"
            / "service.py"
        )
        return fixture_path.read_bytes(), str(fixture_path)

    def test_full_extraction(self, extractor, fixture_source):
        source, file_path = fixture_source
        root_path = str(
            Path(__file__).parent.parent / "fixtures" / "python-sample"
        )
        nodes, edges = extractor.extract(source, file_path, root_path)

        # MODULE
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1
        assert module_nodes[0].fqn == "mypackage.service"

        # CLASSES
        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        class_names = {n.name for n in class_nodes}
        assert "BaseService" in class_names
        assert "UserService" in class_names

        # UserService inherits BaseService
        inherits = [
            e for e in edges
            if e.kind == EdgeKind.INHERITS and e.source_fqn == "mypackage.service.UserService"
        ]
        assert any(e.target_fqn == "BaseService" for e in inherits)

        # FUNCTIONS (methods + module-level)
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        func_names = {n.name for n in func_nodes}
        assert "find_by_email" in func_names
        assert "count_active" in func_names
        assert "validate_email" in func_names
        assert "create_service" in func_names
        assert "__init__" in func_names

        # Method type hints
        find_by = next(n for n in func_nodes if n.name == "find_by_email")
        assert find_by.properties.get("return_type") is not None
        params = find_by.properties.get("params", [])
        assert any(p.get("name") == "email" for p in params)

        # Decorator on validate_email
        validate = next(n for n in func_nodes if n.name == "validate_email")
        assert "staticmethod" in validate.properties.get("annotations", [])

        # FIELDS from __init__
        field_nodes = [n for n in nodes if n.kind == NodeKind.FIELD]
        field_names = {n.name for n in field_nodes}
        assert "cache" in field_names
        assert "_initialized" in field_names

        # Class-body field
        assert "DEFAULT_PAGE_SIZE" in field_names

        # IMPORTS
        import_edges = [e for e in edges if e.kind == EdgeKind.IMPORTS]
        import_targets = {e.target_fqn for e in import_edges}
        assert "logging" in import_targets
        assert "typing" in import_targets
        assert "sqlalchemy.orm" in import_targets

        # CALLS edges exist
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert len(calls) > 0
        # find_by_email calls self.db.execute
        db_calls = [
            e for e in calls
            if "find_by_email" in e.source_fqn and "execute" in e.target_fqn
        ]
        assert len(db_calls) >= 1

        # SQL strings tagged
        sql_funcs = [
            n for n in func_nodes
            if n.properties.get("sql_strings")
        ]
        assert len(sql_funcs) >= 1

        # Module-level function CONTAINS edge
        factory_contains = [
            e for e in edges
            if e.kind == EdgeKind.CONTAINS
            and e.target_fqn == "mypackage.service.create_service"
        ]
        assert len(factory_contains) == 1
        assert factory_contains[0].source_fqn == "mypackage.service"

    def test_node_and_edge_counts_reasonable(self, extractor, fixture_source):
        source, file_path = fixture_source
        root_path = str(
            Path(__file__).parent.parent / "fixtures" / "python-sample"
        )
        nodes, edges = extractor.extract(source, file_path, root_path)

        # Sanity: we should have a reasonable number of items
        assert len(nodes) >= 10   # 1 module + 2 classes + 5+ functions + fields
        assert len(edges) >= 10   # contains + inherits + imports + calls
```

- [ ] **Step 3: Run all tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_python_extractor.py -v`
Expected: PASS (all tests across all test classes)

- [ ] **Step 4: Run with coverage**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_python_extractor.py --cov=app.stages.treesitter.extractors.python --cov-report=term-missing -v`
Expected: Coverage >= 85% on `python.py`

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add tests/fixtures/python-sample/ tests/unit/test_python_extractor.py && git commit -m "test(extractor): add full integration test with realistic Python fixture"
```

---

## Task 9: Lint and Final Validation

- [ ] **Step 1: Run ruff check**

```bash
cd cast-clone-backend && uv run ruff check app/stages/treesitter/extractors/python.py tests/unit/test_python_extractor.py
```

Fix any issues reported.

- [ ] **Step 2: Run ruff format**

```bash
cd cast-clone-backend && uv run ruff format app/stages/treesitter/extractors/python.py tests/unit/test_python_extractor.py
```

- [ ] **Step 3: Run mypy (if configured)**

```bash
cd cast-clone-backend && uv run mypy app/stages/treesitter/extractors/python.py --ignore-missing-imports
```

Fix any type errors.

- [ ] **Step 4: Run full test suite to ensure no regressions**

```bash
cd cast-clone-backend && uv run pytest tests/ -v
```

- [ ] **Step 5: Final commit**

```bash
cd cast-clone-backend && git add -u && git commit -m "chore(extractor): lint and format Python extractor"
```

---

## Summary

### Files Created
| File | Purpose |
|------|---------|
| `app/stages/__init__.py` | Package init |
| `app/stages/treesitter/__init__.py` | Package init |
| `app/stages/treesitter/extractors/__init__.py` | Package init |
| `app/stages/treesitter/extractors/python.py` | PythonExtractor implementation |
| `tests/unit/test_python_extractor.py` | 10 test classes, 20+ test cases |
| `tests/fixtures/python-sample/mypackage/__init__.py` | Empty package init |
| `tests/fixtures/python-sample/mypackage/service.py` | Realistic fixture file |

### Files Modified
| File | Change |
|------|--------|
| `pyproject.toml` | Add `tree-sitter`, `tree-sitter-python` dependencies |

### What Gets Extracted

| Python Construct | Node/Edge | Kind | Confidence |
|-----------------|-----------|------|------------|
| Module (file) | GraphNode | MODULE | — |
| `import X` | GraphEdge | IMPORTS | HIGH |
| `from X import Y` | GraphEdge | IMPORTS | HIGH |
| `class Foo:` | GraphNode | CLASS | — |
| `class Foo(Base):` | GraphEdge | INHERITS | LOW |
| `@decorator` | properties["annotations"] | — | — |
| `def method(self):` | GraphNode | FUNCTION | — |
| `def func():` | GraphNode | FUNCTION | — |
| `self.x = val` | GraphNode | FIELD | — |
| `X = val` (class body) | GraphNode | FIELD | — |
| `func()` / `obj.method()` | GraphEdge | CALLS | LOW |
| SQL-like strings | properties["sql_strings"] | — | — |
| Parent -> child | GraphEdge | CONTAINS | HIGH |

### Architecture Decisions

1. **FQN derivation** — File-path based (`mypackage.service.UserService`), matching Python's module system. `__init__.py` maps to the package name without `.__init__`.

2. **INHERITS edges use LOW confidence** — Base class names are unresolved short names (e.g., `"BaseModel"` not `"pydantic.BaseModel"`). SCIP will upgrade these to HIGH with fully qualified targets.

3. **CALLS edges use LOW confidence** — Same reasoning. `obj.method()` is recorded as-is; SCIP resolves the actual target.

4. **Decorators stored as strings** — Including arguments (e.g., `"app.route('/users')"`) so framework plugins can pattern-match without re-parsing.

5. **SQL detection is heuristic** — Requires 2+ SQL keywords to reduce false positives. Downstream sqlglot stage does actual parsing.

6. **Fields from `__init__` only** — We extract `self.x = ...` from `__init__` (not from arbitrary methods) to avoid false positives. Class-body assignments are also extracted.

7. **No cross-file resolution** — The extractor operates on a single file. Cross-file resolution (import -> actual class, base class name -> FQN) happens in the global resolution pass and SCIP merger.
