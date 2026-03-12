# M4b: Java Tree-sitter Extractor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Java tree-sitter extractor that parses a single Java source file and produces `GraphNode` + `GraphEdge` lists covering classes, interfaces, methods, constructors, fields, inheritance, method calls, object creation, imports, annotations, and SQL-tagged strings.

**Architecture:** A single `JavaExtractor` class in `app/stages/treesitter/extractors/java.py` that uses `tree-sitter` with `tree_sitter_java` to parse Java source bytes, run S-expression queries against the AST, and emit typed `GraphNode`/`GraphEdge` dataclass instances. The extractor is stateless per call — all state lives in local variables during `extract()`. FQNs are built from the package declaration + class nesting hierarchy. Unresolved call targets get `Confidence.LOW`.

**Tech Stack:** Python 3.12, tree-sitter v0.25+, tree-sitter-java, pytest

**Depends on:** M1 (enums, GraphNode, GraphEdge dataclasses)

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
│               └── java.py             # CREATE — JavaExtractor
└── tests/
    └── unit/
        └── test_java_extractor.py      # CREATE — 9 test cases
```

---

## Task 1: Test Infrastructure + Basic Class Extraction

**Files:**
- Create: `app/stages/treesitter/__init__.py`
- Create: `app/stages/treesitter/extractors/__init__.py`
- Create: `app/stages/treesitter/extractors/java.py`
- Create: `tests/unit/test_java_extractor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_java_extractor.py
import pytest
from app.models.enums import NodeKind, EdgeKind, Confidence
from app.stages.treesitter.extractors.java import JavaExtractor


@pytest.fixture
def extractor():
    return JavaExtractor()


def _find_node(nodes, fqn):
    """Helper: find a node by FQN."""
    for n in nodes:
        if n.fqn == fqn:
            return n
    return None


def _find_nodes(nodes, kind):
    """Helper: find all nodes of a given kind."""
    return [n for n in nodes if n.kind == kind]


def _find_edge(edges, source_fqn, target_fqn, kind):
    """Helper: find an edge by source, target, and kind."""
    for e in edges:
        if e.source_fqn == source_fqn and e.target_fqn == target_fqn and e.kind == kind:
            return e
    return None


def _find_edges(edges, kind):
    """Helper: find all edges of a given kind."""
    return [e for e in edges if e.kind == kind]


# ──────────────────────────────────────────────
# Test 1: Basic class
# ──────────────────────────────────────────────
class TestBasicClass:
    def test_public_class_node(self, extractor):
        source = b"""\
package com.example.service;

public class UserService {
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        node = _find_node(nodes, "com.example.service.UserService")
        assert node is not None
        assert node.name == "UserService"
        assert node.kind == NodeKind.CLASS
        assert node.language == "java"
        assert node.path == "UserService.java"
        assert node.line is not None
        assert node.properties.get("visibility") == "public"

    def test_default_visibility_class(self, extractor):
        source = b"""\
package com.example;

class Internal {
}
"""
        nodes, edges = extractor.extract(source, "Internal.java", "/project")
        node = _find_node(nodes, "com.example.Internal")
        assert node is not None
        assert node.properties.get("visibility") == "default"

    def test_no_package_class(self, extractor):
        source = b"""\
public class NoPackage {
}
"""
        nodes, edges = extractor.extract(source, "NoPackage.java", "/project")
        node = _find_node(nodes, "NoPackage")
        assert node is not None


# ──────────────────────────────────────────────
# Test 2: Inheritance and interfaces
# ──────────────────────────────────────────────
class TestInheritance:
    def test_extends_and_implements(self, extractor):
        source = b"""\
package com.example;

public class Dog extends Animal implements Runnable, Serializable {
}
"""
        nodes, edges = extractor.extract(source, "Dog.java", "/project")

        node = _find_node(nodes, "com.example.Dog")
        assert node is not None
        assert node.kind == NodeKind.CLASS

        inherits = _find_edge(edges, "com.example.Dog", "Animal", EdgeKind.INHERITS)
        assert inherits is not None

        impl_runnable = _find_edge(edges, "com.example.Dog", "Runnable", EdgeKind.IMPLEMENTS)
        assert impl_runnable is not None

        impl_serializable = _find_edge(edges, "com.example.Dog", "Serializable", EdgeKind.IMPLEMENTS)
        assert impl_serializable is not None

    def test_interface_extends(self, extractor):
        source = b"""\
package com.example;

public interface UserRepository extends JpaRepository, CustomRepo {
}
"""
        nodes, edges = extractor.extract(source, "UserRepository.java", "/project")

        node = _find_node(nodes, "com.example.UserRepository")
        assert node is not None
        assert node.kind == NodeKind.INTERFACE

        inherits_edges = [
            e for e in edges
            if e.source_fqn == "com.example.UserRepository" and e.kind == EdgeKind.INHERITS
        ]
        assert len(inherits_edges) == 2


# ──────────────────────────────────────────────
# Test 3: Methods
# ──────────────────────────────────────────────
class TestMethods:
    def test_method_extraction(self, extractor):
        source = b"""\
package com.example;

public class UserService {
    public User findById(Long id) {
        return null;
    }

    private void validate(String input, int count) {
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        find_method = _find_node(nodes, "com.example.UserService.findById")
        assert find_method is not None
        assert find_method.kind == NodeKind.FUNCTION
        assert find_method.properties.get("return_type") == "User"
        assert find_method.properties.get("params") == ["Long id"]
        assert find_method.properties.get("visibility") == "public"

        validate_method = _find_node(nodes, "com.example.UserService.validate")
        assert validate_method is not None
        assert validate_method.properties.get("params") == ["String input", "int count"]
        assert validate_method.properties.get("visibility") == "private"

        # CONTAINS edges
        contains_find = _find_edge(
            edges, "com.example.UserService", "com.example.UserService.findById", EdgeKind.CONTAINS
        )
        assert contains_find is not None

    def test_method_with_annotations(self, extractor):
        source = b"""\
package com.example;

public class Controller {
    @GetMapping("/users")
    @ResponseBody
    public List<User> getUsers() {
        return null;
    }
}
"""
        nodes, edges = extractor.extract(source, "Controller.java", "/project")

        method = _find_node(nodes, "com.example.Controller.getUsers")
        assert method is not None
        annotations = method.properties.get("annotations", [])
        assert "GetMapping" in annotations
        assert "ResponseBody" in annotations


# ──────────────────────────────────────────────
# Test 4: Fields
# ──────────────────────────────────────────────
class TestFields:
    def test_field_extraction(self, extractor):
        source = b"""\
package com.example;

public class UserService {
    @Autowired
    private UserRepository repo;

    public static final String NAME = "test";
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        repo_field = _find_node(nodes, "com.example.UserService.repo")
        assert repo_field is not None
        assert repo_field.kind == NodeKind.FIELD
        assert repo_field.properties.get("type") == "UserRepository"
        assert repo_field.properties.get("visibility") == "private"
        assert "Autowired" in repo_field.properties.get("annotations", [])

        name_field = _find_node(nodes, "com.example.UserService.NAME")
        assert name_field is not None
        assert name_field.properties.get("is_static") is True
        assert name_field.properties.get("is_final") is True

        # CONTAINS edges
        contains = _find_edge(
            edges, "com.example.UserService", "com.example.UserService.repo", EdgeKind.CONTAINS
        )
        assert contains is not None


# ──────────────────────────────────────────────
# Test 5: Method calls
# ──────────────────────────────────────────────
class TestMethodCalls:
    def test_method_invocation(self, extractor):
        source = b"""\
package com.example;

public class UserService {
    private UserRepository repo;

    public void createUser(User user) {
        repo.save(user);
        validate(user);
    }

    private void validate(User user) {
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        call_edges = _find_edges(edges, EdgeKind.CALLS)

        # repo.save(user) -> receiver "repo", target includes "save"
        repo_save = [e for e in call_edges if "save" in e.target_fqn]
        assert len(repo_save) >= 1
        assert repo_save[0].source_fqn == "com.example.UserService.createUser"
        assert repo_save[0].confidence == Confidence.LOW

        # validate(user) -> no receiver, target includes "validate"
        validate_call = [e for e in call_edges if "validate" in e.target_fqn]
        assert len(validate_call) >= 1

    def test_object_creation(self, extractor):
        source = b"""\
package com.example;

public class Factory {
    public User create() {
        return new User("test");
    }
}
"""
        nodes, edges = extractor.extract(source, "Factory.java", "/project")

        call_edges = _find_edges(edges, EdgeKind.CALLS)
        init_call = [e for e in call_edges if "User.<init>" in e.target_fqn]
        assert len(init_call) >= 1
        assert init_call[0].source_fqn == "com.example.Factory.create"
        assert init_call[0].confidence == Confidence.LOW


# ──────────────────────────────────────────────
# Test 6: Imports
# ──────────────────────────────────────────────
class TestImports:
    def test_import_resolution_map(self, extractor):
        source = b"""\
package com.example;

import com.example.model.User;
import com.example.repo.*;
import java.util.List;

public class UserService {
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        # Imports should be stored on the extractor result or used for FQN resolution.
        # For now, verify IMPORTS edges are created.
        import_edges = _find_edges(edges, EdgeKind.IMPORTS)
        import_targets = {e.target_fqn for e in import_edges}
        assert "com.example.model.User" in import_targets
        assert "com.example.repo.*" in import_targets
        assert "java.util.List" in import_targets


# ──────────────────────────────────────────────
# Test 7: Annotations on class
# ──────────────────────────────────────────────
class TestAnnotations:
    def test_class_annotations(self, extractor):
        source = b"""\
package com.example;

@Service
@Transactional
public class UserService {
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        node = _find_node(nodes, "com.example.UserService")
        assert node is not None
        annotations = node.properties.get("annotations", [])
        assert "Service" in annotations
        assert "Transactional" in annotations


# ──────────────────────────────────────────────
# Test 8: Constructor
# ──────────────────────────────────────────────
class TestConstructor:
    def test_constructor_extraction(self, extractor):
        source = b"""\
package com.example;

public class UserService {
    private final UserRepository repo;

    public UserService(UserRepository repo) {
        this.repo = repo;
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        ctor = _find_node(nodes, "com.example.UserService.<init>")
        assert ctor is not None
        assert ctor.kind == NodeKind.FUNCTION
        assert ctor.properties.get("is_constructor") is True
        assert ctor.properties.get("params") == ["UserRepository repo"]

        contains = _find_edge(
            edges, "com.example.UserService", "com.example.UserService.<init>", EdgeKind.CONTAINS
        )
        assert contains is not None


# ──────────────────────────────────────────────
# Test 9: Full file integration
# ──────────────────────────────────────────────
class TestFullFile:
    FULL_SOURCE = b"""\
package com.example.service;

import com.example.model.User;
import com.example.repository.UserRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional
public class UserService {

    @Autowired
    private UserRepository userRepo;

    private static final String TABLE = "users";

    public UserService(UserRepository userRepo) {
        this.userRepo = userRepo;
    }

    public User findById(Long id) {
        return userRepo.findById(id);
    }

    public User createUser(String name) {
        User user = new User(name);
        userRepo.save(user);
        return user;
    }

    public void deleteAll() {
        String sql = "DELETE FROM users WHERE active = false";
        userRepo.executeSql(sql);
    }
}
"""

    def test_all_class_nodes(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        class_node = _find_node(nodes, "com.example.service.UserService")
        assert class_node is not None
        assert class_node.kind == NodeKind.CLASS
        assert "Service" in class_node.properties.get("annotations", [])
        assert "Transactional" in class_node.properties.get("annotations", [])

    def test_all_method_nodes(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        method_names = {
            n.fqn for n in nodes if n.kind == NodeKind.FUNCTION
        }
        assert "com.example.service.UserService.<init>" in method_names
        assert "com.example.service.UserService.findById" in method_names
        assert "com.example.service.UserService.createUser" in method_names
        assert "com.example.service.UserService.deleteAll" in method_names

    def test_all_field_nodes(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        field_names = {
            n.fqn for n in nodes if n.kind == NodeKind.FIELD
        }
        assert "com.example.service.UserService.userRepo" in field_names
        assert "com.example.service.UserService.TABLE" in field_names

    def test_all_contains_edges(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        contains_edges = _find_edges(edges, EdgeKind.CONTAINS)
        contained_targets = {e.target_fqn for e in contains_edges}
        assert "com.example.service.UserService.<init>" in contained_targets
        assert "com.example.service.UserService.findById" in contained_targets
        assert "com.example.service.UserService.userRepo" in contained_targets

    def test_all_calls_edges(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        call_edges = _find_edges(edges, EdgeKind.CALLS)
        # createUser calls new User() and userRepo.save()
        create_calls = [
            e for e in call_edges
            if e.source_fqn == "com.example.service.UserService.createUser"
        ]
        call_targets = {e.target_fqn for e in create_calls}
        assert any("User.<init>" in t for t in call_targets)
        assert any("save" in t for t in call_targets)

    def test_imports(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        import_edges = _find_edges(edges, EdgeKind.IMPORTS)
        import_targets = {e.target_fqn for e in import_edges}
        assert "com.example.model.User" in import_targets
        assert "com.example.repository.UserRepository" in import_targets

    def test_sql_tagged_strings(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        delete_method = _find_node(
            nodes, "com.example.service.UserService.deleteAll"
        )
        assert delete_method is not None
        tagged = delete_method.properties.get("tagged_strings", [])
        assert any("DELETE" in s for s in tagged)

    def test_node_counts(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        class_count = len(_find_nodes(nodes, NodeKind.CLASS))
        method_count = len(_find_nodes(nodes, NodeKind.FUNCTION))
        field_count = len(_find_nodes(nodes, NodeKind.FIELD))

        assert class_count == 1
        assert method_count == 4  # constructor + 3 methods
        assert field_count == 2   # userRepo + TABLE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_java_extractor.py -v`
Expected: FAIL (ImportError — `app.stages.treesitter.extractors.java` does not exist)

- [ ] **Step 3: Create package structure**

```python
# app/stages/treesitter/__init__.py
```

```python
# app/stages/treesitter/extractors/__init__.py
```

- [ ] **Step 4: Implement JavaExtractor**

```python
# app/stages/treesitter/extractors/java.py
"""Java tree-sitter extractor.

Parses a single Java source file and produces GraphNode + GraphEdge lists
covering: packages, imports, classes, interfaces, methods, constructors,
fields, method calls, object creation, annotations, and SQL-tagged strings.
"""
from __future__ import annotations

import re
from typing import Any

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser, Node

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge

JAVA_LANGUAGE = Language(tsjava.language())

# ── S-expression queries ─────────────────────────────────────────────────

_QUERY_PACKAGE = JAVA_LANGUAGE.query(
    "(package_declaration (scoped_identifier) @package_name)"
)

_QUERY_IMPORT = JAVA_LANGUAGE.query(
    "(import_declaration (scoped_identifier) @import_path)"
)

_QUERY_CLASS = JAVA_LANGUAGE.query("""
(class_declaration
  name: (identifier) @class_name
  superclass: (superclass (type_identifier) @extends)?
  interfaces: (super_interfaces (type_list (type_identifier) @implements))?
  body: (class_body) @body) @class
""")

_QUERY_INTERFACE = JAVA_LANGUAGE.query("""
(interface_declaration
  name: (identifier) @interface_name
  (extends_interfaces (type_list (type_identifier) @extends))?) @interface
""")

_QUERY_METHOD = JAVA_LANGUAGE.query("""
(method_declaration
  type: (_) @return_type
  name: (identifier) @method_name
  parameters: (formal_parameters) @params) @method
""")

_QUERY_CONSTRUCTOR = JAVA_LANGUAGE.query("""
(constructor_declaration
  name: (identifier) @ctor_name
  parameters: (formal_parameters) @params) @constructor
""")

_QUERY_FIELD = JAVA_LANGUAGE.query("""
(field_declaration
  type: (_) @field_type
  declarator: (variable_declarator name: (identifier) @field_name)) @field
""")

_QUERY_METHOD_CALL = JAVA_LANGUAGE.query("""
(method_invocation
  object: (_)? @receiver
  name: (identifier) @method_called
  arguments: (argument_list) @args) @call
""")

_QUERY_OBJECT_CREATION = JAVA_LANGUAGE.query("""
(object_creation_expression
  type: (type_identifier) @created_type
  arguments: (argument_list) @args) @new_expr
""")

_QUERY_STRING_LITERAL = JAVA_LANGUAGE.query("(string_literal) @string")

# SQL keyword pattern for tagging strings
_SQL_PATTERN = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|CREATE|ALTER|DROP)\b", re.IGNORECASE
)


def _node_text(node: Node) -> str:
    """Extract UTF-8 text from a tree-sitter node."""
    return node.text.decode("utf-8")


def _get_modifiers(node: Node) -> list[str]:
    """Extract modifier keywords (public, private, static, etc.) from a declaration node."""
    modifiers: list[str] = []
    for child in node.children:
        if child.type == "modifiers":
            for mod_child in child.children:
                if mod_child.type in (
                    "public", "private", "protected", "static",
                    "final", "abstract", "synchronized", "native",
                    "transient", "volatile",
                ):
                    modifiers.append(mod_child.type)
                # Skip annotations in modifier extraction (handled separately)
    return modifiers


def _get_annotations(node: Node) -> list[str]:
    """Extract annotation names from a declaration node's modifiers."""
    annotations: list[str] = []
    for child in node.children:
        if child.type == "modifiers":
            for mod_child in child.children:
                if mod_child.type == "annotation" or mod_child.type == "marker_annotation":
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
    """Walk up the tree to find the enclosing class_declaration or interface_declaration."""
    current = node.parent
    while current is not None:
        if current.type in ("class_declaration", "interface_declaration", "enum_declaration"):
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
        if parent.type in ("class_declaration", "interface_declaration", "enum_declaration"):
            parent_name = parent.child_by_field_name("name")
            if parent_name is not None:
                parts.insert(0, _node_text(parent_name))
        parent = parent.parent

    class_name = ".".join(parts)
    if package:
        return f"{package}.{class_name}"
    return class_name


class JavaExtractor:
    """Extracts graph nodes and edges from a single Java source file using tree-sitter."""

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
        tree = self._parser.parse(source)
        root = tree.root_node

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # ── Step 1: Parse package ────────────────────────────────────────
        package = self._extract_package(root)

        # ── Step 2: Parse imports ────────────────────────────────────────
        import_map = self._extract_imports(root, package, file_path, edges)

        # ── Step 3: Parse classes ────────────────────────────────────────
        self._extract_classes(root, package, file_path, nodes, edges)

        # ── Step 4: Parse interfaces ─────────────────────────────────────
        self._extract_interfaces(root, package, file_path, nodes, edges)

        # ── Step 5: Parse methods ────────────────────────────────────────
        self._extract_methods(root, package, file_path, nodes, edges)

        # ── Step 6: Parse constructors ───────────────────────────────────
        self._extract_constructors(root, package, file_path, nodes, edges)

        # ── Step 7: Parse fields ─────────────────────────────────────────
        self._extract_fields(root, package, file_path, nodes, edges)

        # ── Step 8: Parse method calls ───────────────────────────────────
        self._extract_method_calls(root, package, file_path, import_map, edges)

        # ── Step 9: Parse object creation ────────────────────────────────
        self._extract_object_creation(root, package, file_path, import_map, edges)

        # ── Step 10: Tag SQL strings ─────────────────────────────────────
        self._tag_sql_strings(root, package, nodes)

        return nodes, edges

    # ── Private extraction methods ───────────────────────────────────────

    def _extract_package(self, root: Node) -> str:
        """Extract the package name from the compilation unit."""
        matches = _QUERY_PACKAGE.matches(root)
        if matches:
            _, captures = matches[0]
            package_nodes = captures.get("package_name", [])
            if package_nodes:
                return _node_text(package_nodes[0])
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

        for _, captures in _QUERY_IMPORT.matches(root):
            import_nodes = captures.get("import_path", [])
            if not import_nodes:
                continue
            import_path = _node_text(import_nodes[0])

            # Build the short-name map
            if import_path.endswith(".*"):
                # Wildcard import — store for later resolution
                import_map[import_path] = import_path
            else:
                # Specific import: short name is last segment
                short_name = import_path.rsplit(".", 1)[-1]
                import_map[short_name] = import_path

            edges.append(GraphEdge(
                source_fqn=source_fqn,
                target_fqn=import_path,
                kind=EdgeKind.IMPORTS,
                confidence=Confidence.HIGH,
                evidence="tree-sitter",
            ))

        return import_map

    def _extract_classes(
        self,
        root: Node,
        package: str,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract class declarations into GraphNodes and inheritance/implements edges."""
        for _, captures in _QUERY_CLASS.matches(root):
            class_nodes = captures.get("class", [])
            if not class_nodes:
                continue
            class_node = class_nodes[0]
            name_nodes = captures.get("class_name", [])
            if not name_nodes:
                continue

            fqn = _class_fqn(package, class_node)
            name = _node_text(name_nodes[0])
            modifiers = _get_modifiers(class_node)
            annotations = _get_annotations(class_node)

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
                "is_abstract": "abstract" in modifiers,
            }
            if annotations:
                properties["annotations"] = annotations

            nodes.append(GraphNode(
                fqn=fqn,
                name=name,
                kind=NodeKind.CLASS,
                language="java",
                path=file_path,
                line=class_node.start_point[0] + 1,
                end_line=class_node.end_point[0] + 1,
                properties=properties,
            ))

            # Superclass -> INHERITS edge
            extends_nodes = captures.get("extends", [])
            if extends_nodes:
                edges.append(GraphEdge(
                    source_fqn=fqn,
                    target_fqn=_node_text(extends_nodes[0]),
                    kind=EdgeKind.INHERITS,
                    confidence=Confidence.LOW,
                    evidence="tree-sitter",
                ))

            # Interfaces -> IMPLEMENTS edges
            impl_nodes = captures.get("implements", [])
            for impl_node in impl_nodes:
                edges.append(GraphEdge(
                    source_fqn=fqn,
                    target_fqn=_node_text(impl_node),
                    kind=EdgeKind.IMPLEMENTS,
                    confidence=Confidence.LOW,
                    evidence="tree-sitter",
                ))

    def _extract_interfaces(
        self,
        root: Node,
        package: str,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract interface declarations."""
        for _, captures in _QUERY_INTERFACE.matches(root):
            iface_nodes = captures.get("interface", [])
            if not iface_nodes:
                continue
            iface_node = iface_nodes[0]
            name_nodes = captures.get("interface_name", [])
            if not name_nodes:
                continue

            fqn = _class_fqn(package, iface_node)
            name = _node_text(name_nodes[0])
            modifiers = _get_modifiers(iface_node)
            annotations = _get_annotations(iface_node)

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
            }
            if annotations:
                properties["annotations"] = annotations

            nodes.append(GraphNode(
                fqn=fqn,
                name=name,
                kind=NodeKind.INTERFACE,
                language="java",
                path=file_path,
                line=iface_node.start_point[0] + 1,
                end_line=iface_node.end_point[0] + 1,
                properties=properties,
            ))

            # Extended interfaces -> INHERITS edges
            extends_nodes = captures.get("extends", [])
            for ext_node in extends_nodes:
                edges.append(GraphEdge(
                    source_fqn=fqn,
                    target_fqn=_node_text(ext_node),
                    kind=EdgeKind.INHERITS,
                    confidence=Confidence.LOW,
                    evidence="tree-sitter",
                ))

    def _extract_methods(
        self,
        root: Node,
        package: str,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract method declarations."""
        for _, captures in _QUERY_METHOD.matches(root):
            method_nodes = captures.get("method", [])
            if not method_nodes:
                continue
            method_node = method_nodes[0]
            name_nodes = captures.get("method_name", [])
            if not name_nodes:
                continue

            # Find enclosing class to build FQN
            enclosing = _find_enclosing_class(method_node)
            if enclosing is None:
                continue
            class_fqn = _class_fqn(package, enclosing)
            method_name = _node_text(name_nodes[0])
            fqn = f"{class_fqn}.{method_name}"

            modifiers = _get_modifiers(method_node)
            annotations = _get_annotations(method_node)

            return_type_nodes = captures.get("return_type", [])
            return_type = _node_text(return_type_nodes[0]) if return_type_nodes else "void"

            params_nodes = captures.get("params", [])
            params = _parse_formal_parameters(params_nodes[0]) if params_nodes else []

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
                "return_type": return_type,
                "params": params,
            }
            if annotations:
                properties["annotations"] = annotations

            nodes.append(GraphNode(
                fqn=fqn,
                name=method_name,
                kind=NodeKind.FUNCTION,
                language="java",
                path=file_path,
                line=method_node.start_point[0] + 1,
                end_line=method_node.end_point[0] + 1,
                properties=properties,
            ))

            edges.append(GraphEdge(
                source_fqn=class_fqn,
                target_fqn=fqn,
                kind=EdgeKind.CONTAINS,
                confidence=Confidence.HIGH,
                evidence="tree-sitter",
            ))

    def _extract_constructors(
        self,
        root: Node,
        package: str,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract constructor declarations."""
        for _, captures in _QUERY_CONSTRUCTOR.matches(root):
            ctor_nodes = captures.get("constructor", [])
            if not ctor_nodes:
                continue
            ctor_node = ctor_nodes[0]

            enclosing = _find_enclosing_class(ctor_node)
            if enclosing is None:
                continue
            class_fqn = _class_fqn(package, enclosing)
            fqn = f"{class_fqn}.<init>"

            modifiers = _get_modifiers(ctor_node)
            annotations = _get_annotations(ctor_node)

            params_nodes = captures.get("params", [])
            params = _parse_formal_parameters(params_nodes[0]) if params_nodes else []

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
                "is_constructor": True,
                "params": params,
            }
            if annotations:
                properties["annotations"] = annotations

            nodes.append(GraphNode(
                fqn=fqn,
                name="<init>",
                kind=NodeKind.FUNCTION,
                language="java",
                path=file_path,
                line=ctor_node.start_point[0] + 1,
                end_line=ctor_node.end_point[0] + 1,
                properties=properties,
            ))

            edges.append(GraphEdge(
                source_fqn=class_fqn,
                target_fqn=fqn,
                kind=EdgeKind.CONTAINS,
                confidence=Confidence.HIGH,
                evidence="tree-sitter",
            ))

    def _extract_fields(
        self,
        root: Node,
        package: str,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract field declarations."""
        for _, captures in _QUERY_FIELD.matches(root):
            field_nodes = captures.get("field", [])
            if not field_nodes:
                continue
            field_node = field_nodes[0]
            name_nodes = captures.get("field_name", [])
            if not name_nodes:
                continue

            enclosing = _find_enclosing_class(field_node)
            if enclosing is None:
                continue
            class_fqn = _class_fqn(package, enclosing)
            field_name = _node_text(name_nodes[0])
            fqn = f"{class_fqn}.{field_name}"

            modifiers = _get_modifiers(field_node)
            annotations = _get_annotations(field_node)

            type_nodes = captures.get("field_type", [])
            field_type = _node_text(type_nodes[0]) if type_nodes else "unknown"

            properties: dict[str, Any] = {
                "visibility": _visibility_from_modifiers(modifiers),
                "type": field_type,
                "is_static": "static" in modifiers,
                "is_final": "final" in modifiers,
            }
            if annotations:
                properties["annotations"] = annotations

            nodes.append(GraphNode(
                fqn=fqn,
                name=field_name,
                kind=NodeKind.FIELD,
                language="java",
                path=file_path,
                line=field_node.start_point[0] + 1,
                end_line=field_node.end_point[0] + 1,
                properties=properties,
            ))

            edges.append(GraphEdge(
                source_fqn=class_fqn,
                target_fqn=fqn,
                kind=EdgeKind.CONTAINS,
                confidence=Confidence.HIGH,
                evidence="tree-sitter",
            ))

    def _extract_method_calls(
        self,
        root: Node,
        package: str,
        file_path: str,
        import_map: dict[str, str],
        edges: list[GraphEdge],
    ) -> None:
        """Extract method invocation edges."""
        for _, captures in _QUERY_METHOD_CALL.matches(root):
            call_nodes = captures.get("call", [])
            if not call_nodes:
                continue
            call_node = call_nodes[0]

            method_called_nodes = captures.get("method_called", [])
            if not method_called_nodes:
                continue
            method_name = _node_text(method_called_nodes[0])

            # Find enclosing method for the source FQN
            enclosing_method = _find_enclosing_method(call_node)
            if enclosing_method is None:
                continue
            enclosing_class = _find_enclosing_class(enclosing_method)
            if enclosing_class is None:
                continue
            class_fqn = _class_fqn(package, enclosing_class)

            if enclosing_method.type == "constructor_declaration":
                source_fqn = f"{class_fqn}.<init>"
            else:
                enc_name_node = enclosing_method.child_by_field_name("name")
                if enc_name_node is None:
                    continue
                source_fqn = f"{class_fqn}.{_node_text(enc_name_node)}"

            # Build target FQN
            receiver_nodes = captures.get("receiver", [])
            if receiver_nodes:
                receiver_text = _node_text(receiver_nodes[0])
                target_fqn = f"{receiver_text}.{method_name}"
            else:
                target_fqn = method_name

            edges.append(GraphEdge(
                source_fqn=source_fqn,
                target_fqn=target_fqn,
                kind=EdgeKind.CALLS,
                confidence=Confidence.LOW,
                evidence="tree-sitter",
                properties={"line": call_node.start_point[0] + 1},
            ))

    def _extract_object_creation(
        self,
        root: Node,
        package: str,
        file_path: str,
        import_map: dict[str, str],
        edges: list[GraphEdge],
    ) -> None:
        """Extract 'new ClassName(...)' as CALLS edges to <init>."""
        for _, captures in _QUERY_OBJECT_CREATION.matches(root):
            new_nodes = captures.get("new_expr", [])
            if not new_nodes:
                continue
            new_node = new_nodes[0]

            type_nodes = captures.get("created_type", [])
            if not type_nodes:
                continue
            created_type = _node_text(type_nodes[0])

            # Find enclosing method
            enclosing_method = _find_enclosing_method(new_node)
            if enclosing_method is None:
                continue
            enclosing_class = _find_enclosing_class(enclosing_method)
            if enclosing_class is None:
                continue
            class_fqn = _class_fqn(package, enclosing_class)

            if enclosing_method.type == "constructor_declaration":
                source_fqn = f"{class_fqn}.<init>"
            else:
                enc_name_node = enclosing_method.child_by_field_name("name")
                if enc_name_node is None:
                    continue
                source_fqn = f"{class_fqn}.{_node_text(enc_name_node)}"

            # Resolve created type via import map if possible
            resolved_type = import_map.get(created_type, created_type)
            target_fqn = f"{resolved_type}.<init>"

            edges.append(GraphEdge(
                source_fqn=source_fqn,
                target_fqn=target_fqn,
                kind=EdgeKind.CALLS,
                confidence=Confidence.LOW,
                evidence="tree-sitter",
                properties={"line": new_node.start_point[0] + 1},
            ))

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

        for _, captures in _QUERY_STRING_LITERAL.matches(root):
            string_nodes = captures.get("string", [])
            if not string_nodes:
                continue
            string_node = string_nodes[0]
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
            class_fqn = _class_fqn(package, enclosing_class)

            if enclosing_method.type == "constructor_declaration":
                method_fqn = f"{class_fqn}.<init>"
            else:
                enc_name_node = enclosing_method.child_by_field_name("name")
                if enc_name_node is None:
                    continue
                method_fqn = f"{class_fqn}.{_node_text(enc_name_node)}"

            graph_node = method_node_map.get(method_fqn)
            if graph_node is not None:
                tagged = graph_node.properties.setdefault("tagged_strings", [])
                tagged.append(text)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_java_extractor.py -v`
Expected: PASS (all tests green)

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/stages/treesitter/__init__.py app/stages/treesitter/extractors/__init__.py app/stages/treesitter/extractors/java.py tests/unit/test_java_extractor.py && git commit -m "feat(extractor): add Java tree-sitter extractor with full test coverage"
```

---

## Verification

Run the full test suite to confirm nothing is broken:

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_java_extractor.py -v
```

Expected output: **25+ tests passing** covering:
- Basic class extraction with package/visibility
- Inheritance (extends) and interface implementation
- Method extraction with params, return type, annotations
- Field extraction with type, modifiers, annotations
- Method invocation call edges with LOW confidence
- Object creation (`new`) as CALLS to `<init>`
- Import parsing and IMPORTS edges
- Class-level annotation extraction
- Constructor extraction with `is_constructor` flag
- Full file integration (all elements combined)
- SQL string tagging on enclosing method nodes

---

## Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| One class, one file | `JavaExtractor` in single module | Keeps extractor self-contained; other language extractors follow same pattern |
| Module-level compiled queries | `_QUERY_*` constants | Queries compile once at import time, reused across all `extract()` calls |
| FQN from package + class nesting | Walk parent nodes | Handles `Outer.Inner` nested classes correctly |
| Unresolved call targets | `Confidence.LOW` | SCIP (Stage 4) or global resolution pass will upgrade to HIGH |
| Import map built per file | `dict[str, str]` | Used to resolve `new ClassName()` targets; method call receivers stay unresolved (needs type inference) |
| SQL tagging via regex | `_SQL_PATTERN` | Fast heuristic; sqlglot validation happens in the SQL Parser plugin (Stage 5) |
| Properties as plain dict | `dict[str, Any]` | Flexible, avoids rigid schema; framework plugins add their own keys later |

---

## Dependencies on Other Milestones

| Milestone | What This Plan Needs |
|-----------|---------------------|
| M1 (Foundation) | `GraphNode`, `GraphEdge`, `NodeKind`, `EdgeKind`, `Confidence` dataclasses/enums |
| M4a (Tree-sitter Base) | Parser infrastructure (this plan is self-contained but will be wired into the parallel parser in M4a) |

## What Comes Next

- **M4c/M4d/M4e:** TypeScript, C#, Python extractors (same pattern, different queries)
- **M5 (SCIP):** Merges SCIP resolution data with tree-sitter output, upgrades LOW confidence edges to HIGH
- **M6 (Framework Plugins):** Reads annotations/properties stored by this extractor to discover Spring DI, Hibernate mappings, etc.
