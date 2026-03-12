# M4c: TypeScript/JavaScript Tree-sitter Extractor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the TypeScript/JavaScript tree-sitter extractor that parses `.ts`, `.tsx`, `.js`, and `.jsx` files into `GraphNode` and `GraphEdge` instances. This extractor is consumed by Stage 3 (tree-sitter parsing) and provides the structural skeleton that SCIP (Stage 4) and framework plugins (Stage 5 — React, Express, NestJS) refine.

**Architecture:** A single `TypeScriptExtractor` class with one public `extract()` method. Internally organized into focused private methods per concern (imports, classes, functions, calls, decorators, JSX). Uses tree-sitter S-expression queries for AST matching. Returns `tuple[list[GraphNode], list[GraphEdge]]` — no side effects, no state between files. Module FQN derived from file path relative to project root.

**Tech Stack:** Python 3.12, tree-sitter >= 0.25.2, tree-sitter-typescript >= 0.23.2 (provides both `language_typescript()` and `language_tsx()`), pytest

**Depends on:** M1 (models — `GraphNode`, `GraphEdge`, `NodeKind`, `EdgeKind`, `Confidence`)

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       └── treesitter/
│           ├── __init__.py                      # CREATE (empty)
│           └── extractors/
│               ├── __init__.py                  # CREATE (empty)
│               └── typescript.py                # CREATE — TypeScriptExtractor
└── tests/
    └── unit/
        └── test_typescript_extractor.py         # CREATE — 9 test cases
```

---

## Task 1: Create Package Structure

**Files:**
- Create: `app/stages/__init__.py`
- Create: `app/stages/treesitter/__init__.py`
- Create: `app/stages/treesitter/extractors/__init__.py`

- [ ] **Step 1: Create empty `__init__.py` files for the package hierarchy**

```python
# app/stages/__init__.py
# (empty)
```

```python
# app/stages/treesitter/__init__.py
# (empty)
```

```python
# app/stages/treesitter/extractors/__init__.py
# (empty)
```

---

## Task 2: Write Tests

**File:** `tests/unit/test_typescript_extractor.py`

- [ ] **Step 1: Write all test cases**

```python
# tests/unit/test_typescript_extractor.py
"""Tests for the TypeScript/JavaScript tree-sitter extractor.

Covers: classes, interfaces, functions (named + arrow), methods, imports,
decorators, JSX elements, exports, method calls, and a full-file integration test.
"""

import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.treesitter.extractors.typescript import TypeScriptExtractor


@pytest.fixture
def extractor() -> TypeScriptExtractor:
    return TypeScriptExtractor()


def _find_node(
    nodes: list[GraphNode], *, name: str | None = None, kind: NodeKind | None = None
) -> GraphNode | None:
    for n in nodes:
        if name is not None and n.name != name:
            continue
        if kind is not None and n.kind != kind:
            continue
        return n
    return None


def _find_edge(
    edges: list[GraphEdge],
    *,
    kind: EdgeKind | None = None,
    source_contains: str | None = None,
    target_contains: str | None = None,
) -> GraphEdge | None:
    for e in edges:
        if kind is not None and e.kind != kind:
            continue
        if source_contains is not None and source_contains not in e.source_fqn:
            continue
        if target_contains is not None and target_contains not in e.target_fqn:
            continue
        return e
    return None


def _find_edges(
    edges: list[GraphEdge],
    *,
    kind: EdgeKind | None = None,
    source_contains: str | None = None,
    target_contains: str | None = None,
) -> list[GraphEdge]:
    result = []
    for e in edges:
        if kind is not None and e.kind != kind:
            continue
        if source_contains is not None and source_contains not in e.source_fqn:
            continue
        if target_contains is not None and target_contains not in e.target_fqn:
            continue
        result.append(e)
    return result


# ---------------------------------------------------------------------------
# Test 1: Class with extends
# ---------------------------------------------------------------------------
class TestClassWithExtends:
    SOURCE = b"""\
class Animal {
    name: string;

    constructor(name: string) {
        this.name = name;
    }

    speak(): string {
        return this.name;
    }
}

class Dog extends Animal {
    breed: string;

    bark(): void {
        console.log("Woof!");
    }
}
"""

    def test_class_nodes_created(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/animals.ts", "/project")
        animal = _find_node(nodes, name="Animal", kind=NodeKind.CLASS)
        dog = _find_node(nodes, name="Dog", kind=NodeKind.CLASS)
        assert animal is not None
        assert dog is not None
        assert animal.language == "typescript"
        assert animal.path == "src/animals.ts"
        assert animal.fqn == "src/animals.Animal"
        assert dog.fqn == "src/animals.Dog"

    def test_inherits_edge(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/animals.ts", "/project")
        inherits = _find_edge(
            edges, kind=EdgeKind.INHERITS, source_contains="Dog", target_contains="Animal"
        )
        assert inherits is not None

    def test_methods_extracted(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/animals.ts", "/project")
        speak = _find_node(nodes, name="speak", kind=NodeKind.FUNCTION)
        bark = _find_node(nodes, name="bark", kind=NodeKind.FUNCTION)
        assert speak is not None
        assert bark is not None
        assert speak.fqn == "src/animals.Animal.speak"
        assert bark.fqn == "src/animals.Dog.bark"

    def test_contains_edges_for_methods(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/animals.ts", "/project")
        contains = _find_edge(
            edges, kind=EdgeKind.CONTAINS, source_contains="Animal", target_contains="speak"
        )
        assert contains is not None


# ---------------------------------------------------------------------------
# Test 2: Function declarations (named + arrow)
# ---------------------------------------------------------------------------
class TestFunctionDeclarations:
    SOURCE = b"""\
function greet(name: string): string {
    return `Hello, ${name}!`;
}

const add = (a: number, b: number): number => {
    return a + b;
};

export function multiply(x: number, y: number): number {
    return x * y;
}

export const divide = (x: number, y: number): number => x / y;
"""

    def test_named_function(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/utils.ts", "/project")
        greet = _find_node(nodes, name="greet", kind=NodeKind.FUNCTION)
        assert greet is not None
        assert greet.fqn == "src/utils.greet"

    def test_arrow_function(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/utils.ts", "/project")
        add = _find_node(nodes, name="add", kind=NodeKind.FUNCTION)
        assert add is not None
        assert add.fqn == "src/utils.add"

    def test_exported_function(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/utils.ts", "/project")
        multiply = _find_node(nodes, name="multiply", kind=NodeKind.FUNCTION)
        assert multiply is not None
        assert multiply.properties.get("exported") is True

    def test_exported_arrow_function(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/utils.ts", "/project")
        divide = _find_node(nodes, name="divide", kind=NodeKind.FUNCTION)
        assert divide is not None
        assert divide.properties.get("exported") is True


# ---------------------------------------------------------------------------
# Test 3: Imports (ES6 named, default, namespace, CommonJS)
# ---------------------------------------------------------------------------
class TestImports:
    SOURCE = b"""\
import { UserService, RoleService } from './services/user';
import DefaultExport from 'some-module';
import * as Utils from '../utils';
const lodash = require('lodash');

function doSomething() {}
"""

    def test_named_imports_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.ts", "/project")
        # Find the module node for the file
        mod = _find_node(nodes, name="app", kind=NodeKind.MODULE)
        assert mod is not None
        imports = mod.properties.get("imports", [])
        # Should have entries for all import statements
        named = [i for i in imports if i.get("kind") == "named"]
        assert len(named) >= 2  # UserService, RoleService

    def test_default_import_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.ts", "/project")
        mod = _find_node(nodes, name="app", kind=NodeKind.MODULE)
        imports = mod.properties.get("imports", [])
        default = [i for i in imports if i.get("kind") == "default"]
        assert len(default) >= 1
        assert default[0]["local_name"] == "DefaultExport"
        assert default[0]["module"] == "some-module"

    def test_namespace_import_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.ts", "/project")
        mod = _find_node(nodes, name="app", kind=NodeKind.MODULE)
        imports = mod.properties.get("imports", [])
        ns = [i for i in imports if i.get("kind") == "namespace"]
        assert len(ns) >= 1
        assert ns[0]["local_name"] == "Utils"

    def test_commonjs_require_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.ts", "/project")
        mod = _find_node(nodes, name="app", kind=NodeKind.MODULE)
        imports = mod.properties.get("imports", [])
        cjs = [i for i in imports if i.get("kind") == "commonjs"]
        assert len(cjs) >= 1
        assert cjs[0]["local_name"] == "lodash"
        assert cjs[0]["module"] == "lodash"


# ---------------------------------------------------------------------------
# Test 4: Method calls
# ---------------------------------------------------------------------------
class TestMethodCalls:
    SOURCE = b"""\
class OrderService {
    private repo: OrderRepository;

    constructor(repo: OrderRepository) {
        this.repo = repo;
    }

    async findOrder(id: string): Promise<Order> {
        const order = await this.repo.findById(id);
        console.log("Found order");
        return order;
    }

    async createOrder(data: CreateOrderDto): Promise<Order> {
        const validated = validate(data);
        return this.repo.save(validated);
    }
}
"""

    def test_this_method_call(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/order.ts", "/project")
        call = _find_edge(
            edges,
            kind=EdgeKind.CALLS,
            source_contains="findOrder",
            target_contains="findById",
        )
        assert call is not None
        assert call.confidence == Confidence.LOW  # unresolved

    def test_function_call(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/order.ts", "/project")
        call = _find_edge(
            edges,
            kind=EdgeKind.CALLS,
            source_contains="createOrder",
            target_contains="validate",
        )
        assert call is not None

    def test_multiple_calls_from_same_method(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/order.ts", "/project")
        calls_from_create = _find_edges(
            edges, kind=EdgeKind.CALLS, source_contains="createOrder"
        )
        # validate() and this.repo.save()
        assert len(calls_from_create) >= 2


# ---------------------------------------------------------------------------
# Test 5: Decorators (NestJS-style)
# ---------------------------------------------------------------------------
class TestDecorators:
    SOURCE = b"""\
@Controller('users')
@UseGuards(AuthGuard)
class UserController {
    @Get(':id')
    async getUser(@Param('id') id: string): Promise<User> {
        return this.service.findById(id);
    }

    @Post()
    @HttpCode(201)
    async createUser(@Body() dto: CreateUserDto): Promise<User> {
        return this.service.create(dto);
    }
}
"""

    def test_class_decorators_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user.controller.ts", "/project")
        ctrl = _find_node(nodes, name="UserController", kind=NodeKind.CLASS)
        assert ctrl is not None
        annotations = ctrl.properties.get("annotations", [])
        decorator_names = [a["name"] for a in annotations]
        assert "Controller" in decorator_names
        assert "UseGuards" in decorator_names

    def test_controller_decorator_args(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user.controller.ts", "/project")
        ctrl = _find_node(nodes, name="UserController", kind=NodeKind.CLASS)
        annotations = ctrl.properties.get("annotations", [])
        controller_ann = next(a for a in annotations if a["name"] == "Controller")
        assert controller_ann["arguments"] == ["users"]

    def test_method_decorators_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user.controller.ts", "/project")
        get_user = _find_node(nodes, name="getUser", kind=NodeKind.FUNCTION)
        assert get_user is not None
        annotations = get_user.properties.get("annotations", [])
        decorator_names = [a["name"] for a in annotations]
        assert "Get" in decorator_names

    def test_method_decorator_args(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user.controller.ts", "/project")
        get_user = _find_node(nodes, name="getUser", kind=NodeKind.FUNCTION)
        annotations = get_user.properties.get("annotations", [])
        get_ann = next(a for a in annotations if a["name"] == "Get")
        assert get_ann["arguments"] == [":id"]


# ---------------------------------------------------------------------------
# Test 6: JSX elements (React component references)
# ---------------------------------------------------------------------------
class TestJSXElements:
    SOURCE = b"""\
import React from 'react';
import { Header } from './Header';
import { Footer } from './Footer';
import { UserCard } from './UserCard';

export function App() {
    const users = [{ name: 'Alice' }];
    return (
        <div className="app">
            <Header title="My App" />
            <main>
                {users.map(u => (
                    <UserCard key={u.name} user={u} />
                ))}
            </main>
            <Footer />
        </div>
    );
}
"""

    def test_jsx_components_captured(self, extractor: TypeScriptExtractor):
        # Use .tsx extension to trigger TSX parser
        nodes, edges = extractor.extract(self.SOURCE, "src/App.tsx", "/project")
        app_fn = _find_node(nodes, name="App", kind=NodeKind.FUNCTION)
        assert app_fn is not None
        jsx_elements = app_fn.properties.get("jsx_elements", [])
        # Should capture PascalCase components, not HTML elements like div/main
        component_names = [j["name"] for j in jsx_elements]
        assert "Header" in component_names
        assert "Footer" in component_names
        assert "UserCard" in component_names
        assert "div" not in component_names
        assert "main" not in component_names

    def test_jsx_component_count(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/App.tsx", "/project")
        app_fn = _find_node(nodes, name="App", kind=NodeKind.FUNCTION)
        jsx_elements = app_fn.properties.get("jsx_elements", [])
        component_names = [j["name"] for j in jsx_elements]
        assert len(component_names) == 3


# ---------------------------------------------------------------------------
# Test 7: Interface declarations
# ---------------------------------------------------------------------------
class TestInterface:
    SOURCE = b"""\
export interface IUser {
    id: string;
    name: string;
    email: string;
    createdAt: Date;
}

interface IRepository<T> {
    findById(id: string): Promise<T>;
    save(entity: T): Promise<T>;
    delete(id: string): Promise<void>;
}
"""

    def test_interface_nodes_created(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/types.ts", "/project")
        iuser = _find_node(nodes, name="IUser", kind=NodeKind.INTERFACE)
        irepo = _find_node(nodes, name="IRepository", kind=NodeKind.INTERFACE)
        assert iuser is not None
        assert irepo is not None
        assert iuser.fqn == "src/types.IUser"
        assert irepo.fqn == "src/types.IRepository"

    def test_interface_exported(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/types.ts", "/project")
        iuser = _find_node(nodes, name="IUser", kind=NodeKind.INTERFACE)
        assert iuser.properties.get("exported") is True

    def test_interface_language(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/types.ts", "/project")
        iuser = _find_node(nodes, name="IUser", kind=NodeKind.INTERFACE)
        assert iuser.language == "typescript"


# ---------------------------------------------------------------------------
# Test 8: Export declarations
# ---------------------------------------------------------------------------
class TestExports:
    SOURCE = b"""\
export default class MainService {
    run(): void {}
}

export { helper, formatter } from './utils';

export const API_URL = 'http://localhost:3000';

function internalHelper() {}
"""

    def test_default_export_class(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/main.ts", "/project")
        main_svc = _find_node(nodes, name="MainService", kind=NodeKind.CLASS)
        assert main_svc is not None
        assert main_svc.properties.get("exported") is True
        assert main_svc.properties.get("export_kind") == "default"

    def test_non_exported_function(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/main.ts", "/project")
        helper = _find_node(nodes, name="internalHelper", kind=NodeKind.FUNCTION)
        assert helper is not None
        assert helper.properties.get("exported") is not True

    def test_exported_const(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/main.ts", "/project")
        # API_URL is a const, not a function or class, so not extracted as a node
        # But the module should track named exports
        mod = _find_node(nodes, name="main", kind=NodeKind.MODULE)
        exports = mod.properties.get("exports", [])
        export_names = [e["name"] for e in exports]
        assert "API_URL" in export_names


# ---------------------------------------------------------------------------
# Test 9: Full file integration test
# ---------------------------------------------------------------------------
class TestFullFile:
    SOURCE = b"""\
import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { User } from './user.entity';
import { CreateUserDto } from './dto/create-user.dto';

@Injectable()
export class UserService {
    constructor(
        @InjectRepository(User)
        private readonly userRepository: Repository<User>,
    ) {}

    async findAll(): Promise<User[]> {
        return this.userRepository.find();
    }

    async findOne(id: number): Promise<User | undefined> {
        return this.userRepository.findOneBy({ id });
    }

    async create(createUserDto: CreateUserDto): Promise<User> {
        const user = this.userRepository.create(createUserDto);
        return this.userRepository.save(user);
    }

    async remove(id: number): Promise<void> {
        await this.userRepository.delete(id);
    }
}
"""

    def test_module_node_created(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user/user.service.ts", "/project")
        mod = _find_node(nodes, name="user.service", kind=NodeKind.MODULE)
        assert mod is not None
        assert mod.fqn == "src/user/user.service"

    def test_class_node(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user/user.service.ts", "/project")
        cls = _find_node(nodes, name="UserService", kind=NodeKind.CLASS)
        assert cls is not None
        assert cls.fqn == "src/user/user.service.UserService"
        assert cls.properties.get("exported") is True
        annotations = cls.properties.get("annotations", [])
        assert any(a["name"] == "Injectable" for a in annotations)

    def test_method_nodes(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user/user.service.ts", "/project")
        methods = [n for n in nodes if n.kind == NodeKind.FUNCTION and "UserService" in n.fqn]
        method_names = {m.name for m in methods}
        assert "findAll" in method_names
        assert "findOne" in method_names
        assert "create" in method_names
        assert "remove" in method_names

    def test_contains_edges(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user/user.service.ts", "/project")
        contains = _find_edges(edges, kind=EdgeKind.CONTAINS, source_contains="UserService")
        # At least 4 methods contained
        assert len(contains) >= 4

    def test_calls_edges(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user/user.service.ts", "/project")
        calls = _find_edges(edges, kind=EdgeKind.CALLS)
        # find, findOneBy, create, save, delete
        assert len(calls) >= 5

    def test_imports_captured(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user/user.service.ts", "/project")
        mod = _find_node(nodes, name="user.service", kind=NodeKind.MODULE)
        imports = mod.properties.get("imports", [])
        modules = {i["module"] for i in imports}
        assert "@nestjs/common" in modules
        assert "@nestjs/typeorm" in modules
        assert "typeorm" in modules
        assert "./user.entity" in modules
        assert "./dto/create-user.dto" in modules

    def test_total_node_count(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/user/user.service.ts", "/project")
        # 1 module + 1 class + 4 methods = 6 minimum
        assert len(nodes) >= 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_typescript_extractor.py -v`
Expected: FAIL (ImportError — `app.stages.treesitter.extractors.typescript` doesn't exist)

---

## Task 3: Implement TypeScriptExtractor

**File:** `app/stages/treesitter/extractors/typescript.py`

- [ ] **Step 1: Implement the extractor**

```python
# app/stages/treesitter/extractors/typescript.py
"""TypeScript/JavaScript tree-sitter extractor.

Parses .ts, .tsx, .js, .jsx files and extracts structural information into
GraphNode and GraphEdge instances. This is Layer 1 (tree-sitter) of the
4-layer parsing strategy — it produces the structural skeleton that SCIP
and framework plugins refine.

Handles:
  - Imports (ES6 named/default/namespace, CommonJS require)
  - Class declarations (with extends/implements, decorators)
  - Interface declarations
  - Function declarations (named, arrow, exported)
  - Method declarations (inside classes)
  - Method/function calls (unresolved, LOW confidence)
  - Decorators with arguments
  - JSX element references (PascalCase only — React components)
  - Export tracking (default, named, re-exports)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node, Parser

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode

# Initialize both TypeScript and TSX languages
_TS_LANGUAGE = Language(tstypescript.language_typescript())
_TSX_LANGUAGE = Language(tstypescript.language_tsx())

# ---------------------------------------------------------------------------
# Tree-sitter S-expression queries
# ---------------------------------------------------------------------------

# --- Classes ---
_CLASS_QUERY = """
(class_declaration
  name: (type_identifier) @class_name
  (class_heritage
    (extends_clause
      value: (identifier) @extends_name)?
    (implements_clause
      (type_identifier) @implements_name)*)?
  body: (class_body) @body
) @class
"""

# --- Interfaces ---
_INTERFACE_QUERY = """
(interface_declaration
  name: (type_identifier) @iface_name
) @interface
"""

# --- Named function declarations ---
_FUNCTION_QUERY = """
(function_declaration
  name: (identifier) @func_name
  parameters: (formal_parameters) @params
  body: (statement_block) @body
) @function
"""

# --- Arrow functions assigned to const/let/var ---
_ARROW_FUNCTION_QUERY = """
(lexical_declaration
  (variable_declarator
    name: (identifier) @func_name
    value: (arrow_function
      parameters: (formal_parameters) @params) @arrow
  )
) @decl
"""

# --- Method definitions inside classes ---
_METHOD_QUERY = """
(method_definition
  name: (property_identifier) @method_name
  parameters: (formal_parameters) @params
  body: (statement_block) @body
) @method
"""

# --- Call expressions ---
_CALL_QUERY = """
(call_expression
  function: (_) @callee
  arguments: (arguments) @args
) @call
"""

# --- Import statements (ES6) ---
_IMPORT_QUERY = """
(import_statement
  (import_clause) @clause
  source: (string) @source
) @import
"""

# --- CommonJS require ---
_REQUIRE_QUERY = """
(lexical_declaration
  (variable_declarator
    name: (identifier) @var_name
    value: (call_expression
      function: (identifier) @func_name
      arguments: (arguments
        (string) @module_path)
    )
  )
) @require
"""

# --- Decorators ---
_DECORATOR_QUERY = """
(decorator
  (call_expression
    function: (identifier) @decorator_name
    arguments: (arguments) @decorator_args)
) @decorator_call
"""

_DECORATOR_NO_ARGS_QUERY = """
(decorator
  (identifier) @decorator_name
) @decorator_simple
"""

# --- JSX opening elements ---
_JSX_OPENING_QUERY = """
(jsx_opening_element
  name: (identifier) @jsx_name
) @jsx_open
"""

_JSX_SELF_CLOSING_QUERY = """
(jsx_self_closing_element
  name: (identifier) @jsx_name
) @jsx_self
"""

# --- Export statements ---
_EXPORT_QUERY = """
(export_statement) @export
"""


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
    # Remove extension
    path = file_path
    for ext in (".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs"):
        if path.endswith(ext):
            path = path[: -len(ext)]
            break
    # Normalize path separators
    path = path.replace(os.sep, "/")
    # Remove leading ./
    if path.startswith("./"):
        path = path[2:]
    # Remove /index suffix (index files represent parent directory)
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


def _find_descendant_by_type(node: Node, type_name: str) -> Node | None:
    """Find first descendant of a given type (DFS)."""
    for child in node.children:
        if child.type == type_name:
            return child
        result = _find_descendant_by_type(child, type_name)
        if result is not None:
            return result
    return None


def _find_descendants_by_type(node: Node, type_name: str) -> list[Node]:
    """Find all descendants of a given type (DFS)."""
    results: list[Node] = []
    for child in node.children:
        if child.type == type_name:
            results.append(child)
        results.extend(_find_descendants_by_type(child, type_name))
    return results


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
        # Choose language based on file extension
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
        imports = self._extract_imports(tree.root_node, lang)
        exports = self._extract_exports(tree.root_node, source)
        export_names = {e["name"] for e in exports if "name" in e}
        has_default_export = any(e.get("kind") == "default" for e in exports)

        # --- Module node ---
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

        # --- Classes ---
        class_fqns: dict[str, str] = {}  # class_name -> fqn (for method FQN building)
        self._extract_classes(
            tree.root_node,
            lang,
            module_path,
            file_path,
            language,
            export_names,
            has_default_export,
            source,
            nodes,
            edges,
            class_fqns,
            is_tsx,
        )

        # --- Interfaces ---
        self._extract_interfaces(
            tree.root_node,
            lang,
            module_path,
            file_path,
            language,
            export_names,
            nodes,
        )

        # --- Top-level functions ---
        self._extract_functions(
            tree.root_node,
            lang,
            module_path,
            file_path,
            language,
            export_names,
            nodes,
            edges,
            is_tsx,
        )

        # --- Top-level arrow functions ---
        self._extract_arrow_functions(
            tree.root_node,
            lang,
            module_path,
            file_path,
            language,
            export_names,
            nodes,
            edges,
            is_tsx,
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
    def _extract_imports(
        self, root: Node, lang: Language
    ) -> list[_ImportInfo]:
        """Extract all import declarations."""
        imports: list[_ImportInfo] = []

        # ES6 imports
        for node in root.children:
            if node.type == "import_statement":
                self._parse_es6_import(node, imports)

        # CommonJS require
        self._extract_commonjs_requires(root, imports)

        return imports

    def _parse_es6_import(
        self, node: Node, imports: list[_ImportInfo]
    ) -> None:
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
            if node.type != "lexical_declaration":
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
    def _extract_exports(
        self, root: Node, source: bytes
    ) -> list[dict[str, Any]]:
        """Extract export declarations and build an export manifest."""
        exports: list[dict[str, Any]] = []

        for node in root.children:
            if node.type == "export_statement":
                self._parse_export(node, exports)

        return exports

    def _parse_export(
        self, node: Node, exports: list[dict[str, Any]]
    ) -> None:
        """Parse a single export statement."""
        text = _node_text(node)
        is_default = "default" in text.split("{")[0].split("(")[0][:30]

        # export default class Foo / export class Foo
        class_decl = _find_child_by_type(node, "class_declaration")
        if class_decl:
            name_node = _find_child_by_type(class_decl, "type_identifier")
            if name_node:
                exports.append({
                    "name": _node_text(name_node),
                    "kind": "default" if is_default else "named",
                    "type": "class",
                })
            return

        # export default function foo / export function foo
        func_decl = _find_child_by_type(node, "function_declaration")
        if func_decl:
            name_node = _find_child_by_type(func_decl, "identifier")
            if name_node:
                exports.append({
                    "name": _node_text(name_node),
                    "kind": "default" if is_default else "named",
                    "type": "function",
                })
            return

        # export const foo = ...
        lex_decl = _find_child_by_type(node, "lexical_declaration")
        if lex_decl:
            for declarator in _find_children_by_type(lex_decl, "variable_declarator"):
                name_node = _find_child_by_type(declarator, "identifier")
                if name_node:
                    exports.append({
                        "name": _node_text(name_node),
                        "kind": "named",
                        "type": "const",
                    })
            return

        # export { foo, bar } or export { foo, bar } from './module'
        export_clause = _find_child_by_type(node, "export_clause")
        if export_clause:
            for spec in _find_children_by_type(export_clause, "export_specifier"):
                name_node = _find_child_by_type(spec, "identifier")
                if name_node:
                    exports.append({
                        "name": _node_text(name_node),
                        "kind": "named",
                        "type": "re-export",
                    })

    # -------------------------------------------------------------------
    # Class extraction
    # -------------------------------------------------------------------
    def _extract_classes(
        self,
        root: Node,
        lang: Language,
        module_path: str,
        file_path: str,
        language: str,
        export_names: set[str],
        has_default_export: bool,
        source: bytes,
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

            # Check if name is in export list (from separate export statement)
            if class_name in export_names:
                is_exported = True

            # Extract decorators
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
                    for ti in _find_children_by_type(implements_clause, "type_identifier"):
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
                    body_node, lang, fqn, file_path, language,
                    nodes, edges, is_tsx,
                )

    # -------------------------------------------------------------------
    # Method extraction (inside classes)
    # -------------------------------------------------------------------
    def _extract_methods(
        self,
        class_body: Node,
        lang: Language,
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

            # Skip constructor for node creation (but still extract calls from it)
            if method_name == "constructor":
                # Extract calls from constructor
                body = _find_child_by_type(child, "statement_block")
                if body:
                    self._extract_calls_from_body(
                        body, f"{class_fqn}.constructor", edges
                    )
                continue

            fqn = f"{class_fqn}.{method_name}"

            # Decorators on methods
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
        lang: Language,
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
        lang: Language,
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

            if node.type == "lexical_declaration":
                lex_node = node
            elif node.type == "export_statement":
                lex_node = _find_child_by_type(node, "lexical_declaration")
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
        lang: Language,
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

        # Find jsx_opening_element and jsx_self_closing_element
        for type_name in ("jsx_opening_element", "jsx_self_closing_element"):
            for jsx_node in _find_descendants_by_type(body, type_name):
                # The name could be an identifier or a member_expression
                name_node = _find_child_by_type(jsx_node, "identifier")
                if name_node is None:
                    continue
                name = _node_text(name_node)
                if _is_pascal_case(name) and name not in seen:
                    seen.add(name)
                    jsx_elements.append({
                        "name": name,
                        "line": jsx_node.start_point[0] + 1,
                    })

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

        In tree-sitter for TypeScript, decorators are siblings preceding
        the decorated node, or children of the node itself.
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

        # Also check preceding siblings (some tree-sitter grammars
        # put decorators as previous siblings)
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

    def _extract_decorator_args(
        self, call_node: Node
    ) -> list[str]:
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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_typescript_extractor.py -v`
Expected: PASS (all tests green)

- [ ] **Step 3: Run linting**

Run: `cd cast-clone-backend && uv run ruff check app/stages/treesitter/extractors/typescript.py`
Expected: No errors

- [ ] **Step 4: Fix any test failures**

If tests fail, debug by examining tree-sitter AST output. Use this snippet to print the AST for a source string:

```python
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser

lang = Language(tstypescript.language_typescript())
parser = Parser(lang)
tree = parser.parse(b"your source here")
print(tree.root_node.sexp())
```

Common issues:
- Node type names differ between TS and TSX grammars
- Decorator placement varies (child vs sibling)
- Arrow function bodies may not have `statement_block` (single expression)
- `class_heritage` structure differs from simpler grammars

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/ tests/unit/test_typescript_extractor.py && git commit -m "feat(treesitter): add TypeScript/JavaScript extractor with full test coverage"
```

---

## Task 4: Verify Edge Cases

- [ ] **Step 1: Verify TSX file parsing**

The extractor must use `language_tsx()` for `.tsx`/`.jsx` files (which include JSX grammar nodes) and `language_typescript()` for `.ts`/`.js` files. The `_detect_language` and `is_tsx` logic handles this. Confirm by running the JSX test:

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_typescript_extractor.py::TestJSXElements -v`
Expected: PASS

- [ ] **Step 2: Verify .js files work with TypeScript parser**

The TypeScript tree-sitter grammar is a superset of JavaScript — it handles plain JS files correctly. No separate JS parser is needed. If a `.js` file uses JSX syntax, the `.jsx` extension triggers TSX mode.

---

## Summary

### What This Extractor Produces

| Extraction | Node Kind | Edge Kind | Confidence | Notes |
|-----------|-----------|-----------|------------|-------|
| Module (file) | MODULE | — | — | One per file |
| Class | CLASS | — | — | With decorators, extends/implements |
| Interface | INTERFACE | — | — | With export status |
| Function (named) | FUNCTION | — | — | Top-level named functions |
| Function (arrow) | FUNCTION | — | — | `const foo = () => {}` |
| Method | FUNCTION | CONTAINS (from class) | HIGH | Inside classes |
| Inheritance | — | INHERITS | LOW | Unresolved until SCIP |
| Implements | — | IMPLEMENTS | LOW | Unresolved until SCIP |
| Calls | — | CALLS | LOW | Unresolved, target is bare name |
| Imports | stored on MODULE | — | — | For resolution by later stages |
| Exports | stored on MODULE | — | — | For resolution by later stages |
| Decorators | stored in properties | — | — | For framework plugins |
| JSX elements | stored in properties | — | — | For React plugin |

### What Gets Refined Later

- **SCIP (Stage 4)**: Upgrades CALLS edges from LOW to HIGH confidence with resolved FQNs
- **React plugin (Stage 5)**: Converts `jsx_elements` into RENDERS edges
- **NestJS plugin (Stage 5)**: Converts decorator annotations into INJECTS, HANDLES, EXPOSES edges
- **Express plugin (Stage 5)**: Converts route handler patterns into APIEndpoint nodes
- **Cross-tech linker (Stage 6)**: Matches HTTP client calls to API endpoints

### Commands

```bash
# Run all tests
cd cast-clone-backend && uv run pytest tests/unit/test_typescript_extractor.py -v

# Run a single test class
cd cast-clone-backend && uv run pytest tests/unit/test_typescript_extractor.py::TestClassWithExtends -v

# Run with coverage
cd cast-clone-backend && uv run pytest tests/unit/test_typescript_extractor.py --cov=app.stages.treesitter.extractors.typescript --cov-report=term-missing

# Debug AST for a source snippet
cd cast-clone-backend && uv run python -c "
import tree_sitter_typescript as ts
from tree_sitter import Language, Parser
lang = Language(ts.language_typescript())
p = Parser(lang)
tree = p.parse(b'class Foo extends Bar {}')
print(tree.root_node.sexp())
"

# Lint
cd cast-clone-backend && uv run ruff check app/stages/treesitter/extractors/typescript.py
cd cast-clone-backend && uv run ruff format --check app/stages/treesitter/extractors/typescript.py
```
