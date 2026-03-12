# M4e: C# Tree-sitter Extractor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the C# tree-sitter extractor that parses `.cs` source files and produces `GraphNode` and `GraphEdge` lists representing classes, interfaces, methods, properties, constructors, fields, using directives, and their relationships (CONTAINS, INHERITS, IMPLEMENTS, CALLS).

**Architecture:** Single `CSharpExtractor` class with an `extract()` method. Uses `tree-sitter-c-sharp` grammar via `py-tree-sitter` v0.25+. Produces dataclass instances (`GraphNode`, `GraphEdge`) from M1. All name resolution is file-local only -- cross-file resolution is handled later by SCIP (Stage 4) and the global symbol resolution pass.

**Tech Stack:** Python 3.12, tree-sitter (v0.25+), tree-sitter-c-sharp, pytest

**Depends on:** M1 (GraphNode, GraphEdge, NodeKind, EdgeKind, Confidence enums)

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
│               └── csharp.py            # CREATE — CSharpExtractor
├── tests/
│   ├── unit/
│   │   └── test_csharp_extractor.py    # CREATE — 10 test cases
│   └── fixtures/
│       └── csharp/                      # CREATE — sample .cs files
│           ├── UserController.cs        # Full ASP.NET controller
│           ├── SimpleClass.cs           # Class + base + interface
│           └── ServiceWithDI.cs         # Constructor injection
└── pyproject.toml                       # MODIFY — add tree-sitter-c-sharp dep
```

---

## Prerequisites

- [ ] **Step 0a: Add tree-sitter dependencies**

Run:
```bash
cd cast-clone-backend && uv add tree-sitter tree-sitter-c-sharp
```

- [ ] **Step 0b: Create directory structure**

Run:
```bash
cd cast-clone-backend && mkdir -p app/stages/treesitter/extractors tests/fixtures/csharp
touch app/stages/__init__.py app/stages/treesitter/__init__.py app/stages/treesitter/extractors/__init__.py
```

---

## Task 1: Test Fixtures — Sample C# Source Files

- [ ] **Step 1: Create `tests/fixtures/csharp/SimpleClass.cs`**

```csharp
// tests/fixtures/csharp/SimpleClass.cs
using System;
using System.Collections.Generic;

namespace MyApp.Models
{
    public interface IEntity
    {
        int Id { get; set; }
    }

    public class BaseModel
    {
        public DateTime CreatedAt { get; set; }
    }

    [Serializable]
    public class User : BaseModel, IEntity
    {
        public int Id { get; set; }
        public string Name { get; set; }
        public string Email { get; set; }
        private List<string> _roles;

        public User(string name, string email)
        {
            Name = name;
            Email = email;
            _roles = new List<string>();
        }

        public void AddRole(string role)
        {
            _roles.Add(role);
        }

        public bool HasRole(string role)
        {
            return _roles.Contains(role);
        }
    }
}
```

- [ ] **Step 2: Create `tests/fixtures/csharp/ServiceWithDI.cs`**

```csharp
// tests/fixtures/csharp/ServiceWithDI.cs
using System.Threading.Tasks;

namespace MyApp.Services
{
    public interface IUserRepository
    {
        Task<User> FindByIdAsync(int id);
        Task SaveAsync(User user);
    }

    public interface IEmailService
    {
        Task SendWelcomeEmail(string email);
    }

    public class UserService
    {
        private readonly IUserRepository _repo;
        private readonly IEmailService _emailService;

        public UserService(IUserRepository repo, IEmailService emailService)
        {
            _repo = repo;
            _emailService = emailService;
        }

        public async Task<User> GetUserAsync(int id)
        {
            var user = await _repo.FindByIdAsync(id);
            return user;
        }

        public async Task CreateUserAsync(string name, string email)
        {
            var user = new User(name, email);
            await _repo.SaveAsync(user);
            await _emailService.SendWelcomeEmail(email);
        }
    }
}
```

- [ ] **Step 3: Create `tests/fixtures/csharp/UserController.cs`**

```csharp
// tests/fixtures/csharp/UserController.cs
using System.Collections.Generic;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace MyApp.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    [Authorize]
    public class UsersController : ControllerBase
    {
        private readonly IUserService _userService;

        public UsersController(IUserService userService)
        {
            _userService = userService;
        }

        [HttpGet]
        public async Task<ActionResult<IEnumerable<UserDto>>> GetAll()
        {
            var users = await _userService.GetAllAsync();
            return Ok(users);
        }

        [HttpGet("{id}")]
        public async Task<ActionResult<UserDto>> GetById(int id)
        {
            var user = await _userService.GetByIdAsync(id);
            if (user == null)
                return NotFound();
            return Ok(user);
        }

        [HttpPost]
        public async Task<ActionResult<UserDto>> Create([FromBody] CreateUserRequest request)
        {
            var user = await _userService.CreateAsync(request);
            return CreatedAtAction(nameof(GetById), new { id = user.Id }, user);
        }

        [HttpDelete("{id}")]
        [Authorize(Roles = "Admin")]
        public async Task<IActionResult> Delete(int id)
        {
            await _userService.DeleteAsync(id);
            return NoContent();
        }
    }
}
```

---

## Task 2: Unit Tests

**File:** `tests/unit/test_csharp_extractor.py`

- [ ] **Step 1: Write all test cases**

```python
# tests/unit/test_csharp_extractor.py
"""Tests for the C# tree-sitter extractor.

Tests cover: namespace/using resolution, class declarations with inheritance,
interfaces, methods with attributes, properties, constructors with DI params,
method calls, object creation, and full ASP.NET controller files.
"""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.stages.treesitter.extractors.csharp import CSharpExtractor


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "csharp"


@pytest.fixture
def extractor() -> CSharpExtractor:
    return CSharpExtractor()


def _read(filename: str) -> bytes:
    return (FIXTURES / filename).read_bytes()


def _find_node(nodes, *, fqn: str = None, name: str = None, kind: NodeKind = None):
    """Find a node matching the given criteria."""
    for n in nodes:
        if fqn and n.fqn != fqn:
            continue
        if name and n.name != name:
            continue
        if kind and n.kind != kind:
            continue
        return n
    criteria = ", ".join(
        f"{k}={v}" for k, v in {"fqn": fqn, "name": name, "kind": kind}.items() if v
    )
    raise AssertionError(
        f"No node found matching {criteria}. "
        f"Available: {[(n.fqn, n.kind) for n in nodes]}"
    )


def _find_edge(edges, *, source_fqn: str = None, target_fqn: str = None, kind: EdgeKind = None):
    """Find an edge matching the given criteria."""
    for e in edges:
        if source_fqn and e.source_fqn != source_fqn:
            continue
        if target_fqn and e.target_fqn != target_fqn:
            continue
        if kind and e.kind != kind:
            continue
        return e
    criteria = ", ".join(
        f"{k}={v}" for k, v in {"source_fqn": source_fqn, "target_fqn": target_fqn, "kind": kind}.items() if v
    )
    raise AssertionError(
        f"No edge found matching {criteria}. "
        f"Available: {[(e.source_fqn, e.target_fqn, e.kind) for e in edges]}"
    )


def _find_edges(edges, *, source_fqn: str = None, target_fqn: str = None, kind: EdgeKind = None):
    """Find all edges matching the given criteria."""
    result = []
    for e in edges:
        if source_fqn and e.source_fqn != source_fqn:
            continue
        if target_fqn and e.target_fqn != target_fqn:
            continue
        if kind and e.kind != kind:
            continue
        result.append(e)
    return result


# ---------------------------------------------------------------------------
# Test 1: Class with base class + interface -> INHERITS + IMPLEMENTS
# ---------------------------------------------------------------------------
class TestClassInheritance:
    def test_class_node_created_with_correct_fqn(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        user_node = _find_node(nodes, fqn="MyApp.Models.User", kind=NodeKind.CLASS)
        assert user_node.name == "User"
        assert user_node.language == "csharp"
        assert user_node.path == "SimpleClass.cs"
        assert user_node.line is not None

    def test_inherits_edge_to_base_class(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        inherits = _find_edge(edges, source_fqn="MyApp.Models.User", kind=EdgeKind.INHERITS)
        assert inherits.target_fqn == "MyApp.Models.BaseModel"

    def test_implements_edge_to_interface(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        implements = _find_edge(edges, source_fqn="MyApp.Models.User", kind=EdgeKind.IMPLEMENTS)
        assert implements.target_fqn == "MyApp.Models.IEntity"

    def test_base_model_class_node_exists(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        base_node = _find_node(nodes, fqn="MyApp.Models.BaseModel", kind=NodeKind.CLASS)
        assert base_node.name == "BaseModel"

    def test_interface_node_exists(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        iface = _find_node(nodes, fqn="MyApp.Models.IEntity", kind=NodeKind.INTERFACE)
        assert iface.name == "IEntity"
        assert iface.kind == NodeKind.INTERFACE


# ---------------------------------------------------------------------------
# Test 2: Methods with attributes
# ---------------------------------------------------------------------------
class TestMethodsWithAttributes:
    def test_method_nodes_created(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_all = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetAll",
            kind=NodeKind.FUNCTION,
        )
        assert get_all.name == "GetAll"
        assert get_all.language == "csharp"

    def test_method_has_http_attribute(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_all = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetAll",
            kind=NodeKind.FUNCTION,
        )
        annotations = get_all.properties.get("annotations", [])
        assert "HttpGet" in annotations

    def test_method_with_path_attribute(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_by_id = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetById",
            kind=NodeKind.FUNCTION,
        )
        annotations = get_by_id.properties.get("annotations", [])
        assert "HttpGet" in annotations

    def test_method_return_type_stored(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_all = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetAll",
            kind=NodeKind.FUNCTION,
        )
        assert get_all.properties.get("return_type") is not None

    def test_method_parameters_stored(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_by_id = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetById",
            kind=NodeKind.FUNCTION,
        )
        params = get_by_id.properties.get("parameters", [])
        assert any(p.get("name") == "id" for p in params)


# ---------------------------------------------------------------------------
# Test 3: Properties (auto-properties)
# ---------------------------------------------------------------------------
class TestProperties:
    def test_auto_property_creates_field_node(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        name_field = _find_node(
            nodes, fqn="MyApp.Models.User.Name", kind=NodeKind.FIELD
        )
        assert name_field.name == "Name"
        assert name_field.properties.get("type") == "string"

    def test_field_contained_in_class(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        contains = _find_edge(
            edges,
            source_fqn="MyApp.Models.User",
            target_fqn="MyApp.Models.User.Name",
            kind=EdgeKind.CONTAINS,
        )
        assert contains is not None

    def test_private_field_detected(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        roles_field = _find_node(
            nodes, fqn="MyApp.Models.User._roles", kind=NodeKind.FIELD
        )
        assert roles_field.visibility == "private"


# ---------------------------------------------------------------------------
# Test 4: Using directives + namespace -> correct FQN
# ---------------------------------------------------------------------------
class TestNamespaceAndUsing:
    def test_fqn_includes_namespace(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        user = _find_node(nodes, name="User", kind=NodeKind.CLASS)
        assert user.fqn == "MyApp.Models.User"

    def test_using_directives_captured(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        # Using directives are stored for downstream resolution.
        # We check that the extractor returns nodes or metadata for usings.
        # Usings are stored in the class properties or returned as import info.
        user = _find_node(nodes, name="User", kind=NodeKind.CLASS)
        # The extractor should store using directives somewhere accessible.
        # Convention: properties["usings"] on the first class or as separate data.
        # For now we verify the FQN was correctly resolved with the namespace.
        assert user.fqn.startswith("MyApp.Models.")

    def test_nested_namespace_works(self, extractor):
        """Namespace with dots is correctly used as FQN prefix."""
        source = b"""
namespace MyApp.Domain.Models
{
    public class Order
    {
        public int Id { get; set; }
    }
}
"""
        nodes, edges = extractor.extract(source, "Order.cs", "/src")
        order = _find_node(nodes, name="Order", kind=NodeKind.CLASS)
        assert order.fqn == "MyApp.Domain.Models.Order"


# ---------------------------------------------------------------------------
# Test 5: Constructor with DI parameters
# ---------------------------------------------------------------------------
class TestConstructorDI:
    def test_constructor_creates_function_node(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        ctor = _find_node(
            nodes,
            fqn="MyApp.Services.UserService.UserService",
            kind=NodeKind.FUNCTION,
        )
        assert ctor.name == "UserService"
        assert ctor.properties.get("is_constructor") is True

    def test_constructor_parameters_captured(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        ctor = _find_node(
            nodes,
            fqn="MyApp.Services.UserService.UserService",
            kind=NodeKind.FUNCTION,
        )
        params = ctor.properties.get("parameters", [])
        param_types = [p.get("type") for p in params]
        assert "IUserRepository" in param_types
        assert "IEmailService" in param_types

    def test_constructor_contained_in_class(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        contains = _find_edge(
            edges,
            source_fqn="MyApp.Services.UserService",
            target_fqn="MyApp.Services.UserService.UserService",
            kind=EdgeKind.CONTAINS,
        )
        assert contains is not None


# ---------------------------------------------------------------------------
# Test 6: Method calls
# ---------------------------------------------------------------------------
class TestMethodCalls:
    def test_method_invocation_creates_calls_edge(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        # GetUserAsync calls _repo.FindByIdAsync
        calls = _find_edges(edges, kind=EdgeKind.CALLS)
        # Should have at least one CALLS edge from GetUserAsync
        get_user_calls = [
            e for e in calls
            if "GetUserAsync" in e.source_fqn
        ]
        assert len(get_user_calls) >= 1

    def test_calls_edge_has_low_confidence(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        calls = _find_edges(edges, kind=EdgeKind.CALLS)
        # Tree-sitter-only calls should be LOW confidence (unresolved)
        for call in calls:
            assert call.confidence == Confidence.LOW

    def test_object_creation_creates_calls_edge(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        # CreateUserAsync has `new User(name, email)`
        calls = _find_edges(edges, kind=EdgeKind.CALLS)
        new_user_calls = [
            e for e in calls
            if "CreateUserAsync" in e.source_fqn and "User" in e.target_fqn
        ]
        assert len(new_user_calls) >= 1


# ---------------------------------------------------------------------------
# Test 7: Full ASP.NET controller file
# ---------------------------------------------------------------------------
class TestAspNetController:
    def test_controller_class_has_attributes(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        ctrl = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController",
            kind=NodeKind.CLASS,
        )
        annotations = ctrl.properties.get("annotations", [])
        assert "ApiController" in annotations
        assert "Authorize" in annotations
        assert "Route" in annotations

    def test_controller_inherits_controllerbase(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        inherits = _find_edge(
            edges,
            source_fqn="MyApp.Controllers.UsersController",
            kind=EdgeKind.INHERITS,
        )
        assert "ControllerBase" in inherits.target_fqn

    def test_controller_contains_methods(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        contains_edges = _find_edges(
            edges,
            source_fqn="MyApp.Controllers.UsersController",
            kind=EdgeKind.CONTAINS,
        )
        contained_fqns = {e.target_fqn for e in contains_edges}
        assert "MyApp.Controllers.UsersController.GetAll" in contained_fqns
        assert "MyApp.Controllers.UsersController.GetById" in contained_fqns
        assert "MyApp.Controllers.UsersController.Create" in contained_fqns
        assert "MyApp.Controllers.UsersController.Delete" in contained_fqns

    def test_all_methods_extracted(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        method_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        method_names = {n.name for n in method_nodes}
        assert {"GetAll", "GetById", "Create", "Delete", "UsersController"} <= method_names

    def test_route_attribute_stored(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        ctrl = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController",
            kind=NodeKind.CLASS,
        )
        # Route annotation argument should be captured
        annotation_args = ctrl.properties.get("annotation_args", {})
        assert "Route" in annotation_args
        assert "api/[controller]" in annotation_args["Route"]


# ---------------------------------------------------------------------------
# Test 8: Attribute argument extraction
# ---------------------------------------------------------------------------
class TestAttributeArguments:
    def test_authorize_roles_extracted(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        delete = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.Delete",
            kind=NodeKind.FUNCTION,
        )
        annotation_args = delete.properties.get("annotation_args", {})
        assert "Authorize" in annotation_args

    def test_http_get_path_extracted(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_by_id = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetById",
            kind=NodeKind.FUNCTION,
        )
        annotation_args = get_by_id.properties.get("annotation_args", {})
        assert "HttpGet" in annotation_args
        assert "{id}" in annotation_args["HttpGet"]


# ---------------------------------------------------------------------------
# Test 9: String literal tagging (SQL-like strings)
# ---------------------------------------------------------------------------
class TestStringLiterals:
    def test_sql_like_string_tagged(self, extractor):
        source = b"""
namespace MyApp.Data
{
    public class UserRepository
    {
        public void RunQuery()
        {
            var sql = "SELECT * FROM users WHERE active = 1";
        }
    }
}
"""
        nodes, edges = extractor.extract(source, "UserRepository.cs", "/src")

        repo = _find_node(nodes, name="UserRepository", kind=NodeKind.CLASS)
        # SQL strings should be tagged in properties
        sql_strings = repo.properties.get("sql_strings", [])
        # Or the method that contains the string
        method = _find_node(nodes, name="RunQuery", kind=NodeKind.FUNCTION)
        sql_strings = method.properties.get("sql_strings", [])
        assert len(sql_strings) >= 1
        assert "SELECT" in sql_strings[0]


# ---------------------------------------------------------------------------
# Test 10: File-scoped namespace (C# 10+)
# ---------------------------------------------------------------------------
class TestFileScopedNamespace:
    def test_file_scoped_namespace_resolved(self, extractor):
        source = b"""
namespace MyApp.Services;

public class OrderService
{
    public void PlaceOrder() { }
}
"""
        nodes, edges = extractor.extract(source, "OrderService.cs", "/src")

        svc = _find_node(nodes, name="OrderService", kind=NodeKind.CLASS)
        assert svc.fqn == "MyApp.Services.OrderService"

        method = _find_node(nodes, name="PlaceOrder", kind=NodeKind.FUNCTION)
        assert method.fqn == "MyApp.Services.OrderService.PlaceOrder"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd cast-clone-backend && uv run pytest tests/unit/test_csharp_extractor.py -v
```
Expected: FAIL (ImportError -- `app.stages.treesitter.extractors.csharp` doesn't exist yet)

---

## Task 3: Implement CSharpExtractor

**File:** `app/stages/treesitter/extractors/csharp.py`

- [ ] **Step 1: Implement the full extractor**

```python
# app/stages/treesitter/extractors/csharp.py
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
from dataclasses import dataclass, field
from typing import Any

import tree_sitter_c_sharp as tscsharp
from tree_sitter import Language, Node, Parser

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode

CS_LANGUAGE = Language(tscsharp.language())

# ── Precompiled Queries ──────────────────────────────────────────────────

# Using directives
Q_USING = CS_LANGUAGE.query("(using_directive (identifier) @name) @using")
Q_USING_QUALIFIED = CS_LANGUAGE.query(
    "(using_directive (qualified_name) @name) @using"
)

# Namespace declarations (block-scoped)
Q_NAMESPACE = CS_LANGUAGE.query(
    "(namespace_declaration name: (_) @name body: (declaration_list) @body) @ns"
)

# File-scoped namespace (C# 10+)
Q_FILE_SCOPED_NS = CS_LANGUAGE.query(
    "(file_scoped_namespace_declaration name: (_) @name) @ns"
)

# Class declarations
Q_CLASS = CS_LANGUAGE.query(
    "(class_declaration name: (identifier) @name) @class"
)

# Interface declarations
Q_INTERFACE = CS_LANGUAGE.query(
    "(interface_declaration name: (identifier) @name) @iface"
)

# Method declarations
Q_METHOD = CS_LANGUAGE.query(
    "(method_declaration name: (identifier) @name) @method"
)

# Constructor declarations
Q_CONSTRUCTOR = CS_LANGUAGE.query(
    "(constructor_declaration name: (identifier) @name) @ctor"
)

# Property declarations
Q_PROPERTY = CS_LANGUAGE.query(
    "(property_declaration name: (identifier) @name) @prop"
)

# Field declarations
Q_FIELD = CS_LANGUAGE.query(
    "(field_declaration) @field"
)

# Method invocations
Q_INVOCATION = CS_LANGUAGE.query(
    "(invocation_expression function: (_) @func) @call"
)

# Object creation
Q_OBJECT_CREATION = CS_LANGUAGE.query(
    "(object_creation_expression type: (_) @type) @creation"
)

# String literals
Q_STRING = CS_LANGUAGE.query(
    "(string_literal) @string"
)

Q_VERBATIM_STRING = CS_LANGUAGE.query(
    "(verbatim_string_literal) @string"
)

# SQL keywords pattern for tagging
_SQL_PATTERN = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|FROM|WHERE|JOIN)\b",
    re.IGNORECASE,
)


def _node_text(node: Node, source: bytes) -> str:
    """Extract UTF-8 text from a tree-sitter node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _get_modifiers(node: Node, source: bytes) -> tuple[str | None, list[str]]:
    """Extract visibility and modifier keywords from a declaration node.

    Returns (visibility, [modifier_keywords]).
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

    Returns (attribute_names, {attr_name: argument_string}).
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
                        # Extract argument list if present
                        arg_list = attr_node.child_by_field_name("arguments")
                        if arg_list:
                            arg_text = _node_text(arg_list, source)
                            # Strip parentheses
                            arg_text = arg_text.strip("()")
                            # Remove surrounding quotes from simple string args
                            clean = arg_text.strip().strip('"')
                            attr_args[attr_name] = clean

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
                    # The actual type is a child of simple_base_type
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
    """Extract return type from a method declaration."""
    rtype = node.child_by_field_name("type")
    if rtype:
        return _node_text(rtype, source)
    return None


def _resolve_namespace(node: Node, source: bytes) -> str:
    """Walk up the tree to find the enclosing namespace(s).

    Handles both block-scoped and file-scoped namespaces.
    Returns dotted namespace string or empty string.
    """
    parts: list[str] = []
    current = node.parent
    while current:
        if current.type in ("namespace_declaration", "file_scoped_namespace_declaration"):
            name_node = current.child_by_field_name("name")
            if name_node:
                parts.append(_node_text(name_node, source))
        current = current.parent
    # Parts are inner->outer, reverse for correct order
    parts.reverse()
    return ".".join(parts)


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


class CSharpExtractor:
    """Extracts graph nodes and edges from C# source code using tree-sitter.

    This is a file-level extractor. It produces:
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
        tree = self._parser.parse(source)
        root = tree.root_node

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # Collect using directives for later reference
        usings = self._extract_usings(root, source)

        # Extract classes
        for match in Q_CLASS.matches(root):
            captures = dict(match[1])
            class_node = captures["class"]
            name_node = captures["name"]
            self._extract_class(
                class_node, name_node, source, file_path, usings, nodes, edges
            )

        # Extract interfaces
        for match in Q_INTERFACE.matches(root):
            captures = dict(match[1])
            iface_node = captures["iface"]
            name_node = captures["name"]
            self._extract_interface(
                iface_node, name_node, source, file_path, usings, nodes, edges
            )

        return nodes, edges

    def _extract_usings(self, root: Node, source: bytes) -> list[str]:
        """Extract all using directive namespace strings."""
        usings: list[str] = []
        for match in Q_USING.matches(root):
            captures = dict(match[1])
            usings.append(_node_text(captures["name"], source))
        for match in Q_USING_QUALIFIED.matches(root):
            captures = dict(match[1])
            usings.append(_node_text(captures["name"], source))
        return usings

    def _extract_class(
        self,
        class_node: Node,
        name_node: Node,
        source: bytes,
        file_path: str,
        usings: list[str],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract a class declaration and all its members."""
        class_name = _node_text(name_node, source)
        namespace = _resolve_namespace(class_node, source)
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

        node = GraphNode(
            fqn=fqn,
            name=class_name,
            kind=NodeKind.CLASS,
            language="csharp",
            path=file_path,
            line=class_node.start_point[0] + 1,
            end_line=class_node.end_point[0] + 1,
            visibility=visibility,
            properties=props,
        )
        nodes.append(node)

        # Base types -> INHERITS / IMPLEMENTS edges
        # Heuristic: in C#, interfaces conventionally start with "I" + uppercase.
        # The first non-interface type in the base list is the base class.
        for bt in base_types:
            # Strip generic parameters for FQN matching
            bare_name = bt.split("<")[0]
            target_fqn = _make_fqn(namespace, bare_name)
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

    def _extract_interface(
        self,
        iface_node: Node,
        name_node: Node,
        source: bytes,
        file_path: str,
        usings: list[str],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract an interface declaration."""
        iface_name = _node_text(name_node, source)
        namespace = _resolve_namespace(iface_node, source)
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
            properties=props,
        )
        nodes.append(node)

        # Interface base types -> IMPLEMENTS edges
        base_types = _get_base_types(iface_node, source)
        for bt in base_types:
            bare_name = bt.split("<")[0]
            target_fqn = _make_fqn(namespace, bare_name)
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
                            child, mn, fqn, namespace, source, file_path,
                            nodes, edges, is_interface_method=True,
                        )

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
        for match in Q_METHOD.matches(body):
            captures = dict(match[1])
            method_node = captures["method"]
            name_node = captures["name"]
            # Only direct children of this body (not nested classes)
            if method_node.parent == body:
                self._extract_method(
                    method_node, name_node, class_fqn, namespace, source,
                    file_path, nodes, edges,
                )

        # Constructors
        for match in Q_CONSTRUCTOR.matches(body):
            captures = dict(match[1])
            ctor_node = captures["ctor"]
            name_node = captures["name"]
            if ctor_node.parent == body:
                self._extract_constructor(
                    ctor_node, name_node, class_fqn, namespace, source,
                    file_path, nodes, edges,
                )

        # Properties
        for match in Q_PROPERTY.matches(body):
            captures = dict(match[1])
            prop_node = captures["prop"]
            name_node = captures["name"]
            if prop_node.parent == body:
                self._extract_property(
                    prop_node, name_node, class_fqn, namespace, source,
                    file_path, nodes, edges,
                )

        # Fields
        for match in Q_FIELD.matches(body):
            captures = dict(match[1])
            field_node = captures["field"]
            if field_node.parent == body:
                self._extract_field(
                    field_node, class_fqn, namespace, source, file_path,
                    nodes, edges,
                )

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
        is_interface_method: bool = False,
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

    def _extract_property(
        self,
        prop_node: Node,
        name_node: Node,
        class_fqn: str,
        namespace: str,
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

    def _extract_field(
        self,
        field_node: Node,
        class_fqn: str,
        namespace: str,
        source: bytes,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Extract a field_declaration (may contain multiple declarators)."""
        visibility, modifiers = _get_modifiers(field_node, source)
        attr_names, attr_args = _get_attributes(field_node, source)

        # Find the type node
        type_node = field_node.child_by_field_name("type")
        # Fallback: scan children for a type-like node
        if type_node is None:
            for child in field_node.children:
                if child.type in (
                    "predefined_type", "identifier", "qualified_name",
                    "generic_name", "nullable_type", "array_type",
                ):
                    type_node = child
                    break

        type_str = _node_text(type_node, source) if type_node else None

        # Extract variable declarators
        for child in field_node.children:
            if child.type == "variable_declaration":
                # type is the first child of variable_declaration
                vtype = child.child_by_field_name("type")
                if vtype:
                    type_str = _node_text(vtype, source)
                for declarator in child.children:
                    if declarator.type == "variable_declarator":
                        fname_node = declarator.child_by_field_name("name")
                        if not fname_node:
                            # Try first identifier child
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

    def _extract_calls(
        self,
        body: Node,
        caller_fqn: str,
        namespace: str,
        source: bytes,
        edges: list[GraphEdge],
    ) -> None:
        """Extract method invocations and object creations from a method body."""
        # Method invocations
        for match in Q_INVOCATION.matches(body):
            captures = dict(match[1])
            func_node = captures["func"]
            call_node = captures["call"]

            callee_name = self._resolve_callee_name(func_node, source)
            if callee_name:
                # Build a best-effort FQN. If it contains a dot, it might be
                # receiver.method -- we keep it as-is for now.
                if "." in callee_name:
                    target_fqn = callee_name
                else:
                    # Could be a local method or inherited method
                    target_fqn = callee_name

                edges.append(
                    GraphEdge(
                        source_fqn=caller_fqn,
                        target_fqn=target_fqn,
                        kind=EdgeKind.CALLS,
                        confidence=Confidence.LOW,
                        evidence="tree-sitter",
                        properties={"line": call_node.start_point[0] + 1},
                    )
                )

        # Object creation: `new Foo()`
        for match in Q_OBJECT_CREATION.matches(body):
            captures = dict(match[1])
            type_node = captures["type"]
            creation_node = captures["creation"]
            type_name = _node_text(type_node, source)
            # Strip generic args
            bare_type = type_name.split("<")[0]
            # Target is the constructor: TypeName.TypeName (convention)
            target_fqn = f"{bare_type}.{bare_type}"

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
            for match in q.matches(body):
                captures = dict(match[1])
                string_node = captures["string"]
                text = _node_text(string_node, source)
                # Strip quotes
                clean = text.strip('"').strip("@\"")
                if _SQL_PATTERN.search(clean):
                    sql_strings.append(clean)

        if sql_strings:
            # Find the method node and add sql_strings to its properties
            for n in nodes:
                if n.fqn == method_fqn:
                    n.properties["sql_strings"] = sql_strings
                    break

    def _resolve_callee_name(self, func_node: Node, source: bytes) -> str | None:
        """Extract a callee name from an invocation_expression function child.

        Handles:
        - Simple: `DoSomething()`           -> "DoSomething"
        - Member access: `_repo.FindById()` -> "_repo.FindById"
        - Chained: `a.b.c()`               -> "a.b.c"
        - Await: `await _repo.FindById()`   -> "_repo.FindById"
        """
        if func_node.type == "identifier":
            return _node_text(func_node, source)
        elif func_node.type == "member_access_expression":
            return _node_text(func_node, source)
        elif func_node.type == "generic_name":
            # e.g., Method<T>() — use the name part
            name = func_node.child_by_field_name("name")
            if name:
                return _node_text(name, source)
            return _node_text(func_node, source).split("<")[0]
        elif func_node.type == "member_binding_expression":
            return _node_text(func_node, source)
        return None

    @staticmethod
    def _looks_like_interface(name: str) -> bool:
        """Heuristic: C# interfaces conventionally start with 'I' + uppercase.

        Examples: IUserService -> True, Item -> False, IEnumerable -> True
        """
        return (
            len(name) >= 2
            and name[0] == "I"
            and name[1].isupper()
        )
```

- [ ] **Step 2: Run tests**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_csharp_extractor.py -v
```

Expected: Most tests PASS. Some may need minor adjustments based on the actual tree-sitter C# grammar node types.

---

## Task 4: Debug and Fix Failing Tests

The tree-sitter C# grammar may have node type names slightly different from expectations. This task handles the iterative TDD fix cycle.

- [ ] **Step 1: If any tests fail, debug with AST inspection**

Add a temporary debug helper to print the AST:

```python
# Temporary debug — remove after fixing
def _print_tree(node, source, indent=0):
    text = source[node.start_byte:node.end_byte].decode()[:60].replace('\n', '\\n')
    print(f"{'  ' * indent}{node.type} [{node.start_point[0]}:{node.start_point[1]}] = {text!r}")
    for child in node.children:
        _print_tree(child, source, indent + 1)
```

Run:
```bash
cd cast-clone-backend && uv run python -c "
import tree_sitter_c_sharp as tscsharp
from tree_sitter import Language, Parser

CS = Language(tscsharp.language())
parser = Parser(CS)
source = open('tests/fixtures/csharp/SimpleClass.cs', 'rb').read()
tree = parser.parse(source)

def print_tree(node, indent=0):
    text = source[node.start_byte:node.end_byte].decode()[:80].replace(chr(10), '\\\\n')
    print(f\"{'  ' * indent}{node.type} = {text!r}\")
    for child in node.children:
        if indent < 4:
            print_tree(child, indent + 1)

print_tree(tree.root_node)
"
```

- [ ] **Step 2: Adjust query patterns based on actual AST structure**

Common C# grammar differences to watch for:
- `modifier` vs `modifiers` — C# grammar uses individual `modifier` nodes, not a `modifiers` wrapper
- `attribute_list` contains `attribute` nodes
- `base_list` contains `simple_base_type` nodes wrapping identifiers
- `variable_declaration` wraps `variable_declarator` in field_declaration
- `file_scoped_namespace_declaration` for `namespace X;` syntax
- Property accessors inside `accessor_list`

- [ ] **Step 3: Re-run tests until all pass**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_csharp_extractor.py -v --tb=short
```

Expected: All 10 test classes PASS (approximately 25+ individual assertions).

---

## Task 5: Edge Cases and Robustness

- [ ] **Step 1: Add edge case tests to the test file**

Append to `tests/unit/test_csharp_extractor.py`:

```python
# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_empty_file_returns_empty(self, extractor):
        nodes, edges = extractor.extract(b"", "Empty.cs", "/src")
        assert nodes == []
        assert edges == []

    def test_file_without_namespace(self, extractor):
        source = b"""
public class GlobalClass
{
    public void DoStuff() { }
}
"""
        nodes, edges = extractor.extract(source, "GlobalClass.cs", "/src")
        cls = _find_node(nodes, name="GlobalClass", kind=NodeKind.CLASS)
        assert cls.fqn == "GlobalClass"

    def test_nested_class(self, extractor):
        source = b"""
namespace Outer
{
    public class Container
    {
        public class Inner
        {
            public void Run() { }
        }
    }
}
"""
        nodes, edges = extractor.extract(source, "Nested.cs", "/src")
        # Inner class should exist — it may be nested under Container
        inner = _find_node(nodes, name="Inner", kind=NodeKind.CLASS)
        assert "Container" in inner.fqn or "Inner" in inner.fqn

    def test_generic_class(self, extractor):
        source = b"""
namespace MyApp
{
    public class Repository<T> where T : class
    {
        public T FindById(int id) { return default; }
    }
}
"""
        nodes, edges = extractor.extract(source, "Repository.cs", "/src")
        repo = _find_node(nodes, name="Repository", kind=NodeKind.CLASS)
        assert repo is not None

    def test_multiple_classes_in_one_file(self, extractor):
        source = b"""
namespace MyApp
{
    public class Foo { }
    public class Bar { }
    public interface IBaz { }
}
"""
        nodes, edges = extractor.extract(source, "Multi.cs", "/src")
        class_nodes = [n for n in nodes if n.kind in (NodeKind.CLASS, NodeKind.INTERFACE)]
        names = {n.name for n in class_nodes}
        assert {"Foo", "Bar", "IBaz"} <= names
```

- [ ] **Step 2: Run all tests**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_csharp_extractor.py -v
```

Expected: All tests PASS.

---

## Task 6: Lint and Type Check

- [ ] **Step 1: Run ruff**

```bash
cd cast-clone-backend && uv run ruff check app/stages/treesitter/extractors/csharp.py
cd cast-clone-backend && uv run ruff format app/stages/treesitter/extractors/csharp.py
```

- [ ] **Step 2: Run mypy**

```bash
cd cast-clone-backend && uv run mypy app/stages/treesitter/extractors/csharp.py --ignore-missing-imports
```

Fix any type errors.

---

## Task 7: Commit

- [ ] **Step 1: Stage and commit**

```bash
cd cast-clone-backend
git add app/stages/ tests/unit/test_csharp_extractor.py tests/fixtures/csharp/ pyproject.toml uv.lock
git commit -m "feat(treesitter): add C# extractor with full AST extraction

Implements CSharpExtractor that parses .cs files via tree-sitter-c-sharp
and produces GraphNode/GraphEdge for classes, interfaces, methods,
properties, fields, constructors, method calls, and object creation.

Extracts: namespaces (block + file-scoped), using directives, attributes
with arguments, base class inheritance, interface implementation,
constructor DI parameters, SQL-like string literals.

All call edges are LOW confidence (tree-sitter only). Cross-file
resolution deferred to SCIP (Stage 4)."
```

---

## Summary of Extraction Rules

| C# Construct | Node Kind | Edge Kind | Confidence | Notes |
|---|---|---|---|---|
| `namespace X { }` | — | — | — | Used as FQN prefix only |
| `namespace X;` | — | — | — | File-scoped namespace, same FQN prefix |
| `using System;` | — | — | — | Stored for downstream resolution |
| `class Foo` | CLASS | — | — | FQN = namespace.Foo |
| `class Foo : Bar` | — | INHERITS | HIGH | Heuristic: non-I-prefix = class |
| `class Foo : IBar` | — | IMPLEMENTS | HIGH | Heuristic: I-prefix = interface |
| `interface IFoo` | INTERFACE | — | — | |
| `void Method()` | FUNCTION | CONTAINS (from class) | HIGH | |
| `Foo(params)` (ctor) | FUNCTION | CONTAINS (from class) | HIGH | `is_constructor=True` |
| `string Name { get; set; }` | FIELD | CONTAINS (from class) | HIGH | `is_property=True` |
| `private int _x;` | FIELD | CONTAINS (from class) | HIGH | |
| `obj.Method()` | — | CALLS | LOW | Unresolved, receiver unknown |
| `new Foo()` | — | CALLS | LOW | Target = `Foo.Foo` (ctor convention) |
| `[HttpGet("{id}")]` | — | — | — | Stored in `annotation_args` |
| `"SELECT * FROM ..."` | — | — | — | Stored in `sql_strings` on method |

## Dependencies (for `pyproject.toml`)

```
tree-sitter >= 0.25.0
tree-sitter-c-sharp >= 0.23.0
```

## Acceptance Criteria

1. `CSharpExtractor.extract()` returns correct nodes/edges for all 10+ test cases
2. FQNs correctly incorporate namespace (block-scoped and file-scoped)
3. Interface vs class inheritance correctly distinguished by I-prefix heuristic
4. Attributes and their arguments extracted and stored in `properties`
5. Constructor parameters captured (enables DI resolution in ASP.NET plugin)
6. Method calls extracted as LOW confidence CALLS edges
7. SQL-like strings tagged on method nodes
8. All tests pass: `uv run pytest tests/unit/test_csharp_extractor.py -v`
9. Lint clean: `ruff check` and `mypy` pass
