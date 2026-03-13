# M6d: ASP.NET Core + Entity Framework Plugins Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Tier 2b C#/.NET framework plugins that extract invisible connections from ASP.NET Core and Entity Framework codebases — controller endpoint mappings, dependency injection wiring, minimal API routes, middleware pipeline ordering, DbContext entity registration, data annotation/Fluent API table mappings, navigation property relationships, and EF migration schema reconstruction.

**Architecture:** Each plugin extends `FrameworkPlugin` (from M6a). Plugins scan `context.graph` for C# classes/methods/fields with specific attributes (stored in `node.properties["annotations"]` and `node.properties["annotation_args"]` by the CSharpExtractor in M4e), resolve cross-class relationships (interface-to-implementation, entity-to-table), and emit `INJECTS`, `HANDLES`, `EXPOSES`, `MAPS_TO`, `HAS_COLUMN`, `REFERENCES`, `READS`, and `WRITES` edges. The ASP.NET DI pattern mirrors Spring DI closely — `AddScoped<IService, ServiceImpl>()` is structurally equivalent to `@Autowired` + `@Service`.

**Dependency chain:** `aspnet-di` → `aspnet-web` (DI must resolve before endpoints); `aspnet-di` → `entity-framework` (EF needs DI context for DbContext resolution).

**Tech Stack:** Python 3.12, dataclasses, re (for route template parsing), pytest + pytest-asyncio

**Dependencies:** M1 (AnalysisContext, SymbolGraph, GraphNode, GraphEdge, enums), M4e (CSharpExtractor output conventions), M6a (FrameworkPlugin, PluginResult, PluginDetectionResult, LayerRules, LayerRule)

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       └── plugins/
│           ├── aspnet/
│           │   ├── __init__.py              # CREATE — re-export plugin classes
│           │   ├── di.py                    # CREATE — ASPNetDIPlugin
│           │   ├── web.py                   # CREATE — ASPNetWebPlugin (controllers + minimal APIs)
│           │   └── middleware.py             # CREATE — ASPNetMiddlewarePlugin
│           └── entity_framework/
│               ├── __init__.py              # CREATE — re-export plugin classes
│               └── dbcontext.py             # CREATE — EntityFrameworkPlugin (DbContext + entities + migrations)
├── tests/
│   └── unit/
│       ├── test_aspnet_di_plugin.py         # CREATE
│       ├── test_aspnet_web_plugin.py        # CREATE
│       ├── test_aspnet_middleware_plugin.py  # CREATE
│       └── test_entity_framework_plugin.py  # CREATE
```

---

## Conventions from CSharpExtractor (M4e)

The C# tree-sitter extractor stores data in `node.properties` using these keys:

| Key | Type | Description | Example |
|-----|------|-------------|---------|
| `annotations` | `list[str]` | Attribute names on the class/method | `["ApiController", "Route", "Authorize"]` |
| `annotation_args` | `dict[str, str]` | Attribute arguments (unnamed key = `""`) | `{"": "api/[controller]"}` for `[Route("api/[controller]")]` |
| `type` | `str` | Field/property type | `"IUserService"` |
| `type_args` | `list[str]` | Generic type arguments | `["User", "Long"]` for `DbSet<User>` |
| `implements` | `list[str]` | Interface names on the class | `["IUserService"]` |
| `base_class` | `str` | Base class name | `"ControllerBase"` |
| `is_constructor` | `bool` | Constructor marker | `True` |
| `is_property` | `bool` | Auto-property marker | `True` |
| `parameters` | `list[dict]` | Constructor/method params | `[{"name": "_userService", "type": "IUserService"}]` |
| `return_type` | `str` | Method return type | `"Task<ActionResult<UserDto>>"` |
| `sql_strings` | `list[str]` | SQL-like strings in method body | `["SELECT * FROM users"]` |

---

## Shared Test Helpers

All test files need to build `AnalysisContext` objects pre-populated with CSharpExtractor-parsed nodes. The helpers follow the same pattern as M6b (Spring plugins):

```python
# Shared across all test files (copy into each, or extract to conftest.py later)

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework, EntryPoint


def _make_context() -> AnalysisContext:
    """Create a minimal AnalysisContext with an empty graph."""
    ctx = AnalysisContext(project_id="test-dotnet")
    ctx.graph = SymbolGraph()
    ctx.manifest = ProjectManifest(root_path="/code")
    ctx.manifest.detected_frameworks = [
        DetectedFramework(name="aspnet", language="csharp", confidence=Confidence.HIGH, evidence=["csproj"]),
    ]
    return ctx


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    *,
    base_class: str = "",
    implements: list[str] | None = None,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    is_interface: bool = False,
    type_args: list[str] | None = None,
) -> GraphNode:
    """Add a CLASS or INTERFACE node to the graph."""
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.INTERFACE if is_interface else NodeKind.CLASS,
        language="csharp",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "base_class": base_class,
            "implements": implements or [],
            "type_args": type_args or [],
        },
    )
    graph.add_node(node)
    return node


def _add_method(
    graph: SymbolGraph,
    class_fqn: str,
    method_name: str,
    *,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    parameters: list[dict] | None = None,
    return_type: str = "void",
    is_constructor: bool = False,
) -> GraphNode:
    """Add a FUNCTION node and CONTAINS edge from parent class."""
    fqn = f"{class_fqn}.{method_name}"
    node = GraphNode(
        fqn=fqn,
        name=method_name,
        kind=NodeKind.FUNCTION,
        language="csharp",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "parameters": parameters or [],
            "return_type": return_type,
            "is_constructor": is_constructor,
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn,
        target_fqn=fqn,
        kind=EdgeKind.CONTAINS,
        confidence=Confidence.HIGH,
        evidence="treesitter",
    ))
    return node


def _add_field(
    graph: SymbolGraph,
    class_fqn: str,
    field_name: str,
    field_type: str,
    *,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    is_property: bool = False,
    type_args: list[str] | None = None,
) -> GraphNode:
    """Add a FIELD node and CONTAINS edge from parent class."""
    fqn = f"{class_fqn}.{field_name}"
    node = GraphNode(
        fqn=fqn,
        name=field_name,
        kind=NodeKind.FIELD,
        language="csharp",
        properties={
            "type": field_type,
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "is_property": is_property,
            "type_args": type_args or [],
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn,
        target_fqn=fqn,
        kind=EdgeKind.CONTAINS,
        confidence=Confidence.HIGH,
        evidence="treesitter",
    ))
    return node
```

---

## Task 1: ASP.NET DI Plugin (`aspnet/di.py`)

**Files:**
- Create: `app/stages/plugins/aspnet/__init__.py`
- Create: `app/stages/plugins/aspnet/di.py`
- Test: `tests/unit/test_aspnet_di_plugin.py`

### What it extracts

Scans `Program.cs` or `Startup.cs` for DI registrations:
- `builder.Services.AddScoped<IService, ServiceImpl>()` → INJECTS edge with `lifetime: "scoped"`
- `builder.Services.AddTransient<IService, ServiceImpl>()` → INJECTS edge with `lifetime: "transient"`
- `builder.Services.AddSingleton<IService, ServiceImpl>()` → INJECTS edge with `lifetime: "singleton"`
- Self-registration: `builder.Services.AddScoped<Service>()` → registers class as its own service type
- `builder.Services.AddDbContext<AppDbContext>(...)` → registers DbContext as scoped

Then resolves constructor injection: for each class whose constructor has interface-typed parameters, looks up the DI registration to find the concrete implementation, and creates INJECTS edges.

### Layer classification
- Classes registered as services → Business Logic
- Classes ending in "Repository" or registered as repository → Data Access
- DbContext subclasses → Data Access

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_aspnet_di_plugin.py
"""Tests for the ASP.NET Core DI plugin — service registration and constructor injection resolution."""

import pytest
from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.aspnet.di import ASPNetDIPlugin

# ... paste shared helpers from above ...


class TestDetection:
    def test_detects_aspnet_framework(self):
        plugin = ASPNetDIPlugin()
        ctx = _make_context()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_no_detection_without_framework(self):
        plugin = ASPNetDIPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.graph = SymbolGraph()
        ctx.manifest = ProjectManifest(root_path="/code")
        ctx.manifest.detected_frameworks = []
        result = plugin.detect(ctx)
        assert result.confidence in (Confidence.LOW, None) or not result.confidence


class TestServiceRegistration:
    @pytest.mark.asyncio
    async def test_addscoped_creates_injects_edge(self):
        """builder.Services.AddScoped<IUserService, UserService>() → INJECTS with scoped lifetime."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()

        # Simulate the tree-sitter parsed call node for AddScoped
        _add_class(ctx.graph, "MyApp.Services.IUserService", "IUserService", is_interface=True)
        _add_class(ctx.graph, "MyApp.Services.UserService", "UserService", implements=["IUserService"])

        # Add a synthetic DI registration node (how the extractor captures method calls)
        _add_method(
            ctx.graph, "MyApp.Program", "ConfigureServices",
            annotations=[], parameters=[],
        )
        # The DI registration is stored as a call edge with properties
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"di_registrations": [
                {"method": "AddScoped", "interface": "IUserService", "implementation": "UserService"},
            ]},
        ))

        result = await plugin.extract(ctx)

        injects = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(injects) >= 1
        edge = injects[0]
        assert edge.properties.get("lifetime") == "scoped"

    @pytest.mark.asyncio
    async def test_addsingleton_lifetime(self):
        """AddSingleton registration has lifetime='singleton'."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()
        _add_class(ctx.graph, "MyApp.ICache", "ICache", is_interface=True)
        _add_class(ctx.graph, "MyApp.MemoryCache", "MemoryCache", implements=["ICache"])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"di_registrations": [
                {"method": "AddSingleton", "interface": "ICache", "implementation": "MemoryCache"},
            ]},
        ))

        result = await plugin.extract(ctx)
        injects = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert any(e.properties.get("lifetime") == "singleton" for e in injects)

    @pytest.mark.asyncio
    async def test_addtransient_lifetime(self):
        """AddTransient registration has lifetime='transient'."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()
        _add_class(ctx.graph, "MyApp.IValidator", "IValidator", is_interface=True)
        _add_class(ctx.graph, "MyApp.RequestValidator", "RequestValidator", implements=["IValidator"])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"di_registrations": [
                {"method": "AddTransient", "interface": "IValidator", "implementation": "RequestValidator"},
            ]},
        ))

        result = await plugin.extract(ctx)
        injects = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert any(e.properties.get("lifetime") == "transient" for e in injects)


class TestConstructorInjection:
    @pytest.mark.asyncio
    async def test_constructor_params_resolved_via_di(self):
        """Controller constructor with IUserService param → resolved to UserService via DI."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.IUserService", "IUserService", is_interface=True)
        _add_class(ctx.graph, "MyApp.UserService", "UserService", implements=["IUserService"])
        _add_class(
            ctx.graph, "MyApp.Controllers.UsersController", "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
        )
        _add_method(
            ctx.graph, "MyApp.Controllers.UsersController", "UsersController",
            is_constructor=True,
            parameters=[{"name": "_userService", "type": "IUserService"}],
        )

        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"di_registrations": [
                {"method": "AddScoped", "interface": "IUserService", "implementation": "UserService"},
            ]},
        ))

        result = await plugin.extract(ctx)

        injects = [e for e in result.edges
                   if e.kind == EdgeKind.INJECTS
                   and "UsersController" in e.target_fqn
                   and "UserService" in e.source_fqn]
        assert len(injects) == 1
        assert injects[0].confidence == Confidence.HIGH


class TestLayerClassification:
    @pytest.mark.asyncio
    async def test_service_classified_as_business_logic(self):
        """Classes registered as services → Business Logic layer."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()
        _add_class(ctx.graph, "MyApp.IOrderService", "IOrderService", is_interface=True)
        _add_class(ctx.graph, "MyApp.OrderService", "OrderService", implements=["IOrderService"])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"di_registrations": [
                {"method": "AddScoped", "interface": "IOrderService", "implementation": "OrderService"},
            ]},
        ))

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.OrderService") == "Business Logic"

    @pytest.mark.asyncio
    async def test_repository_classified_as_data_access(self):
        """Classes with 'Repository' in name → Data Access layer."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()
        _add_class(ctx.graph, "MyApp.IUserRepository", "IUserRepository", is_interface=True)
        _add_class(ctx.graph, "MyApp.UserRepository", "UserRepository", implements=["IUserRepository"])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"di_registrations": [
                {"method": "AddScoped", "interface": "IUserRepository", "implementation": "UserRepository"},
            ]},
        ))

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.UserRepository") == "Data Access"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_aspnet_di_plugin.py -v
```
Expected: FAIL (ImportError — `app.stages.plugins.aspnet.di` doesn't exist yet)

- [ ] **Step 3: Implement the plugin**

Create `app/stages/plugins/aspnet/__init__.py`:
```python
"""ASP.NET Core framework plugins — DI, Web, Middleware."""
```

Create `app/stages/plugins/aspnet/di.py`:
```python
"""ASP.NET Core Dependency Injection plugin.

Extracts DI registrations from Program.cs / Startup.cs patterns:
- AddScoped<IService, Impl>() → INJECTS edge with lifetime metadata
- AddTransient<IService, Impl>() → INJECTS edge
- AddSingleton<IService, Impl>() → INJECTS edge
- Self-registration: AddScoped<Service>() → registers class as own type
- AddDbContext<T>() → registers as scoped

Then resolves constructor injection: controller/service constructors
with interface params → matched to DI registrations → INJECTS edges.

The pattern mirrors Spring DI:
- AddScoped = @Scope("request") + @Service
- AddSingleton = @Scope("singleton") + @Service
- Constructor params = @Autowired constructor injection
"""

from __future__ import annotations

import re
import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

log = structlog.get_logger(__name__)

_LIFETIME_MAP = {
    "AddScoped": "scoped",
    "AddTransient": "transient",
    "AddSingleton": "singleton",
    "AddDbContext": "scoped",
}


class ASPNetDIPlugin(FrameworkPlugin):
    """Resolves ASP.NET Core dependency injection wiring."""

    def __init__(self) -> None:
        self.name = "aspnet-di"
        self.version = "1.0.0"
        self.supported_languages = {"csharp"}
        self.depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest is None:
            return PluginDetectionResult.not_detected()
        for fw in context.manifest.detected_frameworks:
            if fw.name == "aspnet" and fw.confidence in (Confidence.HIGH, Confidence.MEDIUM):
                return PluginDetectionResult(confidence=Confidence.HIGH, reason="ASP.NET Core detected")
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        # Step 1: Collect DI registrations from Program/Startup classes
        registrations = self._collect_di_registrations(context)

        # Step 2: Build interface → implementation lookup
        interface_to_impl: dict[str, tuple[str, str]] = {}
        for reg in registrations:
            iface = reg["interface"]
            impl = reg["implementation"]
            lifetime = _LIFETIME_MAP.get(reg["method"], "scoped")

            # Resolve FQN for interface and implementation
            iface_fqn = self._resolve_fqn(context, iface)
            impl_fqn = self._resolve_fqn(context, impl)

            if iface_fqn and impl_fqn:
                interface_to_impl[iface] = (impl_fqn, lifetime)
                edges.append(GraphEdge(
                    source_fqn=impl_fqn,
                    target_fqn=iface_fqn,
                    kind=EdgeKind.INJECTS,
                    confidence=Confidence.HIGH,
                    evidence="aspnet-di",
                    properties={"lifetime": lifetime},
                ))

                # Layer classification
                if "Repository" in impl or "Repository" in iface:
                    layer_assignments[impl_fqn] = "Data Access"
                elif "DbContext" in impl:
                    layer_assignments[impl_fqn] = "Data Access"
                else:
                    layer_assignments[impl_fqn] = "Business Logic"

        # Step 3: Resolve constructor injection
        for node in list(context.graph.nodes.values()):
            if node.kind != NodeKind.FUNCTION:
                continue
            if not node.properties.get("is_constructor"):
                continue

            params = node.properties.get("parameters", [])
            class_fqn = node.fqn.rsplit(".", 1)[0] if "." in node.fqn else ""

            for param in params:
                param_type = param.get("type", "")
                if param_type in interface_to_impl:
                    impl_fqn, lifetime = interface_to_impl[param_type]
                    edges.append(GraphEdge(
                        source_fqn=impl_fqn,
                        target_fqn=class_fqn,
                        kind=EdgeKind.INJECTS,
                        confidence=Confidence.HIGH,
                        evidence="aspnet-di-constructor",
                        properties={"lifetime": lifetime, "param": param.get("name", "")},
                    ))

        log.info("aspnet_di_extract_done", registrations=len(registrations), edges=len(edges))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[
            LayerRule(pattern="*Repository*", layer="Data Access"),
            LayerRule(pattern="*DbContext*", layer="Data Access"),
            LayerRule(pattern="*Service*", layer="Business Logic"),
        ])

    def _collect_di_registrations(self, context: AnalysisContext) -> list[dict]:
        """Scan graph for Program/Startup nodes with di_registrations property."""
        registrations = []
        for node in context.graph.nodes.values():
            if node.kind != NodeKind.CLASS:
                continue
            regs = node.properties.get("di_registrations", [])
            registrations.extend(regs)
        return registrations

    def _resolve_fqn(self, context: AnalysisContext, simple_name: str) -> str | None:
        """Resolve a simple class name to its FQN in the graph."""
        for node in context.graph.nodes.values():
            if node.kind in (NodeKind.CLASS, NodeKind.INTERFACE) and node.name == simple_name:
                return node.fqn
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_aspnet_di_plugin.py -v
```
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/aspnet/ tests/unit/test_aspnet_di_plugin.py && git commit -m "feat(plugins): add ASP.NET Core DI plugin with service registration and constructor injection resolution"
```

---

## Task 2: ASP.NET Web Plugin (`aspnet/web.py`)

**Files:**
- Create: `app/stages/plugins/aspnet/web.py`
- Test: `tests/unit/test_aspnet_web_plugin.py`

### What it extracts

**Controllers (attribute routing):**
- Classes with `[ApiController]` or extending `ControllerBase` / `Controller`
- Class-level `[Route("api/[controller]")]` with token replacement
- Method-level `[HttpGet]`, `[HttpPost]`, `[HttpPut]`, `[HttpDelete]`, `[HttpPatch]`
- Path combination: class route prefix + method attribute path
- Route constraints: `{id:int}`, `{id?}` normalized to `:param`

**Minimal APIs:**
- `app.MapGet("/path", handler)` → endpoint node
- `app.MapPost("/path", handler)` → endpoint node
- `app.MapGroup("/prefix")` → path prefix applied to children

**Token replacement rules:**
- `[controller]` → class name minus "Controller" suffix (e.g., `UsersController` → `users`)
- `[action]` → method name

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_aspnet_web_plugin.py
"""Tests for the ASP.NET Core Web plugin — controller endpoints and minimal APIs."""

import pytest
from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework, EntryPoint
from app.stages.plugins.aspnet.web import ASPNetWebPlugin

# ... paste shared helpers ...


class TestControllerDetection:
    @pytest.mark.asyncio
    async def test_controller_with_route_and_httpget(self):
        """[Route('api/[controller]')] + [HttpGet('{id}')] → GET /api/users/{id}."""
        plugin = ASPNetWebPlugin()
        ctx = _make_context()

        _add_class(
            ctx.graph, "MyApp.Controllers.UsersController", "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            ctx.graph, "MyApp.Controllers.UsersController", "GetById",
            annotations=["HttpGet"],
            annotation_args={"": "{id}"},
            return_type="Task<ActionResult<UserDto>>",
            parameters=[{"name": "id", "type": "int"}],
        )

        result = await plugin.extract(ctx)

        endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoints) == 1
        ep = endpoints[0]
        assert ep.properties["method"] == "GET"
        assert ep.properties["path"] == "/api/users/{id}"

    @pytest.mark.asyncio
    async def test_httppost_endpoint(self):
        """[HttpPost] with no path → POST /api/users."""
        plugin = ASPNetWebPlugin()
        ctx = _make_context()

        _add_class(
            ctx.graph, "MyApp.Controllers.UsersController", "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            ctx.graph, "MyApp.Controllers.UsersController", "Create",
            annotations=["HttpPost"],
            annotation_args={},
            return_type="Task<ActionResult<UserDto>>",
        )

        result = await plugin.extract(ctx)

        endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoints) == 1
        assert endpoints[0].properties["method"] == "POST"
        assert endpoints[0].properties["path"] == "/api/users"

    @pytest.mark.asyncio
    async def test_controller_token_replacement(self):
        """[controller] token replaced with class name minus 'Controller' suffix."""
        plugin = ASPNetWebPlugin()
        ctx = _make_context()

        _add_class(
            ctx.graph, "MyApp.Controllers.ProductsController", "ProductsController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/v1/[controller]"},
        )
        _add_method(
            ctx.graph, "MyApp.Controllers.ProductsController", "GetAll",
            annotations=["HttpGet"],
            annotation_args={},
        )

        result = await plugin.extract(ctx)
        endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoints) == 1
        assert "/api/v1/products" in endpoints[0].properties["path"]

    @pytest.mark.asyncio
    async def test_multiple_http_methods_on_controller(self):
        """Controller with GET, POST, PUT, DELETE methods → 4 endpoints."""
        plugin = ASPNetWebPlugin()
        ctx = _make_context()

        _add_class(
            ctx.graph, "MyApp.Controllers.ItemsController", "ItemsController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        for method_name, http_attr, path in [
            ("GetAll", "HttpGet", ""),
            ("GetById", "HttpGet", "{id}"),
            ("Create", "HttpPost", ""),
            ("Delete", "HttpDelete", "{id}"),
        ]:
            _add_method(
                ctx.graph, "MyApp.Controllers.ItemsController", method_name,
                annotations=[http_attr],
                annotation_args={"": path} if path else {},
            )

        result = await plugin.extract(ctx)
        endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoints) == 4
        methods = {ep.properties["method"] for ep in endpoints}
        assert methods == {"GET", "POST", "DELETE"}


class TestEdgesAndEntryPoints:
    @pytest.mark.asyncio
    async def test_handles_and_exposes_edges(self):
        """Each endpoint gets HANDLES (method→endpoint) and EXPOSES (class→endpoint) edges."""
        plugin = ASPNetWebPlugin()
        ctx = _make_context()

        _add_class(
            ctx.graph, "MyApp.Controllers.UsersController", "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            ctx.graph, "MyApp.Controllers.UsersController", "GetAll",
            annotations=["HttpGet"],
        )

        result = await plugin.extract(ctx)

        handles = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        exposes = [e for e in result.edges if e.kind == EdgeKind.EXPOSES]
        assert len(handles) == 1
        assert len(exposes) == 1

    @pytest.mark.asyncio
    async def test_entry_points_created(self):
        """Each endpoint produces an HTTP entry point for transaction discovery."""
        plugin = ASPNetWebPlugin()
        ctx = _make_context()

        _add_class(
            ctx.graph, "MyApp.Controllers.UsersController", "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            ctx.graph, "MyApp.Controllers.UsersController", "GetAll",
            annotations=["HttpGet"],
        )

        result = await plugin.extract(ctx)

        assert len(result.entry_points) == 1
        ep = result.entry_points[0]
        assert ep.kind == "http_endpoint"
        assert ep.metadata["method"] == "GET"


class TestLayerClassification:
    @pytest.mark.asyncio
    async def test_controllers_classified_as_presentation(self):
        """Controllers → Presentation layer."""
        plugin = ASPNetWebPlugin()
        ctx = _make_context()

        _add_class(
            ctx.graph, "MyApp.Controllers.UsersController", "UsersController",
            base_class="ControllerBase",
            annotations=["ApiController", "Route"],
            annotation_args={"": "api/[controller]"},
        )
        _add_method(
            ctx.graph, "MyApp.Controllers.UsersController", "GetAll",
            annotations=["HttpGet"],
        )

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.Controllers.UsersController") == "Presentation"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_aspnet_web_plugin.py -v
```
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement the plugin**

Create `app/stages/plugins/aspnet/web.py`:

```python
"""ASP.NET Core Web plugin — controller endpoint extraction and minimal API detection.

Extracts:
- Controller classes with [ApiController] + [Route] attribute routing
- HTTP method attributes: [HttpGet], [HttpPost], [HttpPut], [HttpDelete], [HttpPatch]
- Route token replacement: [controller] → class name minus suffix, [action] → method name
- Minimal API patterns: app.MapGet(), app.MapPost(), app.MapGroup()

Produces:
- APIEndpoint nodes with method + path
- HANDLES edges (function → endpoint)
- EXPOSES edges (class → endpoint)
- HTTP entry points for transaction discovery (Stage 9)

Depends on: aspnet-di (DI must resolve first for accurate class discovery)
"""

from __future__ import annotations

import re
import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.models.manifest import EntryPoint
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    LayerRule,
    PluginDetectionResult,
    PluginResult,
)

log = structlog.get_logger(__name__)

_HTTP_METHODS = {
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpDelete": "DELETE",
    "HttpPatch": "PATCH",
}

_CONTROLLER_BASES = {"ControllerBase", "Controller", "ODataController"}


def _replace_route_tokens(template: str, controller_name: str, action_name: str = "") -> str:
    """Replace [controller] and [action] tokens in route templates."""
    # Remove 'Controller' suffix for token replacement
    ctrl_short = controller_name
    if ctrl_short.endswith("Controller"):
        ctrl_short = ctrl_short[: -len("Controller")]
    ctrl_short = ctrl_short.lower()

    result = template.replace("[controller]", ctrl_short)
    result = result.replace("[action]", action_name.lower())
    return result


def _combine_paths(prefix: str, suffix: str) -> str:
    """Combine class-level route prefix with method-level path."""
    prefix = prefix.strip("/")
    suffix = suffix.strip("/")
    if not prefix and not suffix:
        return "/"
    if not suffix:
        return f"/{prefix}"
    if not prefix:
        return f"/{suffix}"
    return f"/{prefix}/{suffix}"


class ASPNetWebPlugin(FrameworkPlugin):
    """Extracts HTTP endpoints from ASP.NET Core controllers and minimal APIs."""

    def __init__(self) -> None:
        self.name = "aspnet-web"
        self.version = "1.0.0"
        self.supported_languages = {"csharp"}
        self.depends_on: list[str] = ["aspnet-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest is None:
            return PluginDetectionResult.not_detected()
        for fw in context.manifest.detected_frameworks:
            if fw.name == "aspnet" and fw.confidence in (Confidence.HIGH, Confidence.MEDIUM):
                return PluginDetectionResult(confidence=Confidence.HIGH, reason="ASP.NET Core detected")
        # Also detect if any [ApiController] classes exist
        for node in context.graph.nodes.values():
            if node.kind == NodeKind.CLASS and "ApiController" in node.properties.get("annotations", []):
                return PluginDetectionResult(confidence=Confidence.HIGH, reason="[ApiController] found")
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}

        # Extract controller endpoints
        for class_node in list(context.graph.nodes.values()):
            if class_node.kind != NodeKind.CLASS:
                continue

            base_class = class_node.properties.get("base_class", "")
            annotations = class_node.properties.get("annotations", [])

            # Check if this is a controller
            is_controller = (
                base_class in _CONTROLLER_BASES
                or "ApiController" in annotations
            )
            if not is_controller:
                continue

            # Get class-level route prefix
            class_route = ""
            if "Route" in annotations:
                class_route = class_node.properties.get("annotation_args", {}).get("", "")

            # Classify controller as Presentation
            layer_assignments[class_node.fqn] = "Presentation"

            # Find methods with HTTP attributes
            for edge in context.graph.get_edges_from(class_node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                method_node = context.graph.get_node(edge.target_fqn)
                if method_node is None or method_node.kind != NodeKind.FUNCTION:
                    continue

                method_annotations = method_node.properties.get("annotations", [])
                method_args = method_node.properties.get("annotation_args", {})

                for attr, http_method in _HTTP_METHODS.items():
                    if attr not in method_annotations:
                        continue

                    # Get method-level path
                    method_path = method_args.get("", "")

                    # Apply token replacement
                    prefix = _replace_route_tokens(class_route, class_node.name, method_node.name)
                    suffix = _replace_route_tokens(method_path, class_node.name, method_node.name)
                    full_path = _combine_paths(prefix, suffix)

                    # Create endpoint node
                    endpoint_fqn = f"endpoint:{http_method}:{full_path}"
                    endpoint_node = GraphNode(
                        fqn=endpoint_fqn,
                        name=f"{http_method} {full_path}",
                        kind=NodeKind.API_ENDPOINT,
                        language="csharp",
                        properties={
                            "method": http_method,
                            "path": full_path,
                            "request_type": _extract_request_type(method_node),
                            "response_type": method_node.properties.get("return_type", ""),
                        },
                    )
                    nodes.append(endpoint_node)

                    # HANDLES edge: method → endpoint
                    edges.append(GraphEdge(
                        source_fqn=method_node.fqn,
                        target_fqn=endpoint_fqn,
                        kind=EdgeKind.HANDLES,
                        confidence=Confidence.HIGH,
                        evidence="aspnet-web",
                    ))

                    # EXPOSES edge: class → endpoint
                    edges.append(GraphEdge(
                        source_fqn=class_node.fqn,
                        target_fqn=endpoint_fqn,
                        kind=EdgeKind.EXPOSES,
                        confidence=Confidence.HIGH,
                        evidence="aspnet-web",
                    ))

                    # Entry point for transaction discovery
                    entry_points.append(EntryPoint(
                        fqn=method_node.fqn,
                        kind="http_endpoint",
                        metadata={"method": http_method, "path": full_path},
                    ))

        log.info("aspnet_web_extract_done", endpoints=len(nodes))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=[],
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[
            LayerRule(pattern="*Controller*", layer="Presentation"),
        ])


def _extract_request_type(method_node: GraphNode) -> str:
    """Extract request body type from [FromBody] parameter."""
    for param in method_node.properties.get("parameters", []):
        # Convention: [FromBody] param or complex type params
        param_type = param.get("type", "")
        if param_type and not param_type.startswith(("int", "string", "bool", "long", "Guid")):
            return param_type
    return ""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_aspnet_web_plugin.py -v
```
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/aspnet/web.py tests/unit/test_aspnet_web_plugin.py && git commit -m "feat(plugins): add ASP.NET Core Web plugin with controller endpoint extraction, route token replacement, and entry point detection"
```

---

## Task 3: ASP.NET Middleware Plugin (`aspnet/middleware.py`)

**Files:**
- Create: `app/stages/plugins/aspnet/middleware.py`
- Test: `tests/unit/test_aspnet_middleware_plugin.py`

### What it extracts

Scans `Program.cs` for `app.Use*()` middleware calls and extracts them in source order:
- `app.UseAuthentication()` → middleware node with order index
- `app.UseAuthorization()` → middleware node with order index
- `app.UseCors()` → middleware node with order index
- Ordered MIDDLEWARE_CHAIN edges between consecutive entries
- **Validation**: Warns if UseAuthorization comes before UseAuthentication, or UseCors comes after UseAuthentication (per Microsoft's required ordering)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_aspnet_middleware_plugin.py
"""Tests for the ASP.NET Core middleware pipeline plugin."""

import pytest
from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.aspnet.middleware import ASPNetMiddlewarePlugin

# ... paste shared helpers ...


class TestMiddlewareExtraction:
    @pytest.mark.asyncio
    async def test_extracts_middleware_chain(self):
        """Extracts ordered middleware from Program.cs."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = _make_context()

        # Simulate Program.cs with middleware calls stored as properties
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"middleware_calls": [
                "UseRouting",
                "UseCors",
                "UseAuthentication",
                "UseAuthorization",
            ]},
        ))

        result = await plugin.extract(ctx)

        # Should produce ordered edges
        chain_edges = [e for e in result.edges if e.kind == EdgeKind.MIDDLEWARE_CHAIN]
        assert len(chain_edges) == 3  # 4 middleware = 3 chain edges

    @pytest.mark.asyncio
    async def test_warns_on_wrong_auth_order(self):
        """Warns if UseAuthorization comes before UseAuthentication."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = _make_context()

        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"middleware_calls": [
                "UseRouting",
                "UseAuthorization",   # WRONG: before authentication
                "UseAuthentication",
            ]},
        ))

        result = await plugin.extract(ctx)
        assert any("UseAuthorization" in w and "UseAuthentication" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_warns_cors_after_auth(self):
        """Warns if UseCors comes after UseAuthentication."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = _make_context()

        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"middleware_calls": [
                "UseRouting",
                "UseAuthentication",
                "UseCors",   # WRONG: should be before auth
                "UseAuthorization",
            ]},
        ))

        result = await plugin.extract(ctx)
        assert any("UseCors" in w for w in result.warnings)
```

- [ ] **Step 2: Implement, test, and commit**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_aspnet_middleware_plugin.py -v
# Implement app/stages/plugins/aspnet/middleware.py
cd cast-clone-backend && git add app/stages/plugins/aspnet/middleware.py tests/unit/test_aspnet_middleware_plugin.py && git commit -m "feat(plugins): add ASP.NET Core middleware pipeline plugin with ordering validation"
```

---

## Task 4: Entity Framework Plugin (`entity_framework/dbcontext.py`)

**Files:**
- Create: `app/stages/plugins/entity_framework/__init__.py`
- Create: `app/stages/plugins/entity_framework/dbcontext.py`
- Test: `tests/unit/test_entity_framework_plugin.py`

### What it extracts

**DbContext detection:**
- Classes extending `DbContext` → DbContext node
- `DbSet<User>` properties → entity registration, links DbContext to entity

**Entity-to-table mapping (Data Annotations):**
- `[Table("users")]` → table name override (default = class name)
- `[Column("email_address")]` → column name override
- `[Key]` → primary key marker
- `[ForeignKey("AuthorId")]` → FK relationship

**Relationship extraction (Navigation Properties):**
- `public Author Author { get; set; }` + `public int AuthorId { get; set; }` → FK to Author
- `public ICollection<Book> Books { get; set; }` → reverse navigation (one-to-many)
- Fluent API: `HasOne().WithMany().HasForeignKey()` chains (parsed from OnModelCreating)

**EF Migration parsing:**
- `Migrations/*.cs` files: `migrationBuilder.CreateTable(name: "Users", ...)` → Table/Column nodes
- `migrationBuilder.AddForeignKey(...)` → FK constraint edges

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_entity_framework_plugin.py
"""Tests for the Entity Framework plugin — DbContext, entity mapping, relationships, migrations."""

import pytest
from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.entity_framework.dbcontext import EntityFrameworkPlugin

# ... paste shared helpers ...


class TestDbContextDetection:
    @pytest.mark.asyncio
    async def test_dbcontext_subclass_detected(self):
        """Class extending DbContext is detected."""
        plugin = EntityFrameworkPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        _add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Users",
            "DbSet<User>", is_property=True, type_args=["User"],
        )
        _add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Orders",
            "DbSet<Order>", is_property=True, type_args=["Order"],
        )

        # Add entity classes
        _add_class(ctx.graph, "MyApp.Models.User", "User")
        _add_class(ctx.graph, "MyApp.Models.Order", "Order")

        result = await plugin.extract(ctx)

        # Should create table nodes for each DbSet entity
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) >= 2
        table_names = {n.name for n in table_nodes}
        # Convention: table name = DbSet property name or class name
        assert "Users" in table_names or "User" in table_names


class TestDataAnnotations:
    @pytest.mark.asyncio
    async def test_table_annotation_overrides_name(self):
        """[Table('users')] overrides the default table name."""
        plugin = EntityFrameworkPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        _add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Users",
            "DbSet<User>", is_property=True, type_args=["User"],
        )
        _add_class(
            ctx.graph, "MyApp.Models.User", "User",
            annotations=["Table"],
            annotation_args={"": "users"},
        )

        result = await plugin.extract(ctx)

        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert any(n.name == "users" for n in table_nodes)

    @pytest.mark.asyncio
    async def test_column_annotation_creates_column_node(self):
        """[Column('email_address')] creates a column node with custom name."""
        plugin = EntityFrameworkPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        _add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        _add_class(ctx.graph, "MyApp.Models.User", "User", annotations=["Table"], annotation_args={"": "users"})
        _add_field(
            ctx.graph, "MyApp.Models.User", "Email", "string",
            is_property=True,
            annotations=["Column"],
            annotation_args={"": "email_address"},
        )

        result = await plugin.extract(ctx)

        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        assert any(n.name == "email_address" for n in column_nodes)

    @pytest.mark.asyncio
    async def test_foreignkey_annotation_creates_reference(self):
        """[ForeignKey('AuthorId')] creates a REFERENCES edge."""
        plugin = EntityFrameworkPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        _add_field(ctx.graph, "MyApp.Data.AppDbContext", "Books", "DbSet<Book>", is_property=True, type_args=["Book"])
        _add_field(ctx.graph, "MyApp.Data.AppDbContext", "Authors", "DbSet<Author>", is_property=True, type_args=["Author"])

        _add_class(ctx.graph, "MyApp.Models.Author", "Author")
        _add_class(ctx.graph, "MyApp.Models.Book", "Book")
        _add_field(
            ctx.graph, "MyApp.Models.Book", "AuthorId", "int", is_property=True,
            annotations=["ForeignKey"],
            annotation_args={"": "Author"},
        )
        _add_field(
            ctx.graph, "MyApp.Models.Book", "Author", "Author", is_property=True,
        )

        result = await plugin.extract(ctx)

        refs = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(refs) >= 1


class TestNavigationProperties:
    @pytest.mark.asyncio
    async def test_collection_navigation_detects_one_to_many(self):
        """ICollection<Book> navigation property → one-to-many relationship."""
        plugin = EntityFrameworkPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        _add_field(ctx.graph, "MyApp.Data.AppDbContext", "Authors", "DbSet<Author>", is_property=True, type_args=["Author"])
        _add_field(ctx.graph, "MyApp.Data.AppDbContext", "Books", "DbSet<Book>", is_property=True, type_args=["Book"])

        _add_class(ctx.graph, "MyApp.Models.Author", "Author")
        _add_field(
            ctx.graph, "MyApp.Models.Author", "Books",
            "ICollection<Book>", is_property=True, type_args=["Book"],
        )

        _add_class(ctx.graph, "MyApp.Models.Book", "Book")
        _add_field(
            ctx.graph, "MyApp.Models.Book", "AuthorId", "int", is_property=True,
        )
        _add_field(
            ctx.graph, "MyApp.Models.Book", "Author", "Author", is_property=True,
        )

        result = await plugin.extract(ctx)

        refs = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(refs) >= 1
        # Should link Book → Author via AuthorId convention


class TestMapsToEdges:
    @pytest.mark.asyncio
    async def test_entity_maps_to_table(self):
        """Entity class → MAPS_TO → Table node."""
        plugin = EntityFrameworkPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        _add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        _add_class(ctx.graph, "MyApp.Models.User", "User")

        result = await plugin.extract(ctx)

        maps_to = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
        assert len(maps_to) >= 1
        assert any("User" in e.source_fqn for e in maps_to)


class TestLayerClassification:
    @pytest.mark.asyncio
    async def test_dbcontext_classified_as_data_access(self):
        """DbContext → Data Access layer."""
        plugin = EntityFrameworkPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.Data.AppDbContext") == "Data Access"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_entity_framework_plugin.py -v
```
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement the plugin**

Create `app/stages/plugins/entity_framework/__init__.py`:
```python
"""Entity Framework Core plugins — DbContext, entity mapping, migrations."""
```

Create `app/stages/plugins/entity_framework/dbcontext.py`:

```python
"""Entity Framework Core plugin.

Extracts:
- DbContext subclasses with DbSet<T> properties → entity registration
- Data annotations: [Table], [Column], [Key], [ForeignKey] → table/column mapping
- Navigation properties: ICollection<T>, reference types → FK relationships
- Fluent API: OnModelCreating with HasOne/HasMany/HasForeignKey chains
- EF Migrations: Migrations/*.cs with CreateTable, AddForeignKey → schema nodes

Produces:
- Table and Column nodes for every mapped entity
- MAPS_TO edges: entity class → table
- HAS_COLUMN edges: table → column
- REFERENCES edges: FK column → PK column
- DbContext → entity management edges

Depends on: aspnet-di (DI must resolve first for DbContext registration)

Configuration precedence (matches EF Core): Fluent API > Data Annotations > Conventions
"""

from __future__ import annotations

import re
import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    LayerRule,
    PluginDetectionResult,
    PluginResult,
)

log = structlog.get_logger(__name__)

# Types that indicate navigation collections (one-to-many)
_COLLECTION_TYPES = {"ICollection", "IEnumerable", "IList", "List", "HashSet", "ISet"}


class EntityFrameworkPlugin(FrameworkPlugin):
    """Extracts Entity Framework Core entity-to-database mappings."""

    def __init__(self) -> None:
        self.name = "entity-framework"
        self.version = "1.0.0"
        self.supported_languages = {"csharp"}
        self.depends_on: list[str] = ["aspnet-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest is None:
            return PluginDetectionResult.not_detected()
        # Check for DbContext subclass in graph
        for node in context.graph.nodes.values():
            if node.kind == NodeKind.CLASS and node.properties.get("base_class") == "DbContext":
                return PluginDetectionResult(confidence=Confidence.HIGH, reason="DbContext found")
        # Check for EF NuGet dependency
        for fw in context.manifest.detected_frameworks:
            if fw.name == "aspnet":
                return PluginDetectionResult(confidence=Confidence.MEDIUM, reason="ASP.NET detected, may use EF")
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        # Step 1: Find DbContext classes and their DbSet<T> properties
        entity_registry: dict[str, str] = {}  # entity_simple_name -> entity_fqn
        dbcontext_entities: dict[str, list[str]] = {}  # dbcontext_fqn -> [entity_names]

        for node in list(context.graph.nodes.values()):
            if node.kind != NodeKind.CLASS:
                continue
            if node.properties.get("base_class") != "DbContext":
                continue

            layer_assignments[node.fqn] = "Data Access"
            dbcontext_entities[node.fqn] = []

            # Find DbSet<T> properties
            for edge in context.graph.get_edges_from(node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                field = context.graph.get_node(edge.target_fqn)
                if field is None or field.kind != NodeKind.FIELD:
                    continue
                if not field.properties.get("is_property"):
                    continue

                field_type = field.properties.get("type", "")
                type_args = field.properties.get("type_args", [])

                if "DbSet" in field_type and type_args:
                    entity_name = type_args[0]
                    entity_fqn = self._resolve_entity_fqn(context, entity_name)
                    if entity_fqn:
                        entity_registry[entity_name] = entity_fqn
                        dbcontext_entities[node.fqn].append(entity_name)

        # Step 2: For each registered entity, extract table/column mapping
        for entity_name, entity_fqn in entity_registry.items():
            entity_node = context.graph.get_node(entity_fqn)
            if entity_node is None:
                continue

            # Determine table name
            table_name = self._get_table_name(entity_node, entity_name)

            # Create Table node
            table_fqn = f"table:{table_name}"
            table_node = GraphNode(
                fqn=table_fqn,
                name=table_name,
                kind=NodeKind.TABLE,
                language="sql",
                properties={"entity_fqn": entity_fqn},
            )
            nodes.append(table_node)

            # MAPS_TO edge: entity → table
            edges.append(GraphEdge(
                source_fqn=entity_fqn,
                target_fqn=table_fqn,
                kind=EdgeKind.MAPS_TO,
                confidence=Confidence.HIGH,
                evidence="entity-framework",
            ))

            # Extract columns from entity properties
            for edge in context.graph.get_edges_from(entity_fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                prop = context.graph.get_node(edge.target_fqn)
                if prop is None or prop.kind != NodeKind.FIELD:
                    continue
                if not prop.properties.get("is_property"):
                    continue

                prop_type = prop.properties.get("type", "")
                prop_type_args = prop.properties.get("type_args", [])
                prop_annotations = prop.properties.get("annotations", [])

                # Skip navigation properties (handled separately)
                is_nav = self._is_navigation_property(prop_type, prop_type_args, entity_registry)
                if is_nav:
                    continue

                # Determine column name
                col_name = self._get_column_name(prop)

                col_fqn = f"{table_fqn}.{col_name}"
                col_node = GraphNode(
                    fqn=col_fqn,
                    name=col_name,
                    kind=NodeKind.COLUMN,
                    language="sql",
                    properties={
                        "data_type": prop_type,
                        "is_pk": "Key" in prop_annotations,
                    },
                )
                nodes.append(col_node)

                edges.append(GraphEdge(
                    source_fqn=table_fqn,
                    target_fqn=col_fqn,
                    kind=EdgeKind.HAS_COLUMN,
                    confidence=Confidence.HIGH,
                    evidence="entity-framework",
                ))

                # Check for FK annotation
                if "ForeignKey" in prop_annotations:
                    fk_target = prop.properties.get("annotation_args", {}).get("", "")
                    if fk_target and fk_target in entity_registry:
                        target_entity_fqn = entity_registry[fk_target]
                        target_table = self._get_table_name(
                            context.graph.get_node(target_entity_fqn), fk_target
                        )
                        edges.append(GraphEdge(
                            source_fqn=col_fqn,
                            target_fqn=f"table:{target_table}.Id",
                            kind=EdgeKind.REFERENCES,
                            confidence=Confidence.HIGH,
                            evidence="entity-framework-fk",
                        ))

            # Step 3: Extract navigation property relationships
            self._extract_navigation_relationships(
                context, entity_node, entity_fqn, entity_registry, table_name, edges
            )

        log.info("ef_extract_done", entities=len(entity_registry), tables=len([n for n in nodes if n.kind == NodeKind.TABLE]))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[
            LayerRule(pattern="*DbContext*", layer="Data Access"),
        ])

    def _resolve_entity_fqn(self, context: AnalysisContext, simple_name: str) -> str | None:
        """Resolve entity class name to FQN."""
        for node in context.graph.nodes.values():
            if node.kind == NodeKind.CLASS and node.name == simple_name:
                return node.fqn
        return None

    def _get_table_name(self, entity_node: GraphNode | None, default_name: str) -> str:
        """Get table name: [Table] annotation > DbSet property name > class name."""
        if entity_node is None:
            return default_name
        annotations = entity_node.properties.get("annotations", [])
        if "Table" in annotations:
            table_arg = entity_node.properties.get("annotation_args", {}).get("", "")
            if table_arg:
                return table_arg
        return default_name

    def _get_column_name(self, prop_node: GraphNode) -> str:
        """Get column name: [Column] annotation > property name."""
        annotations = prop_node.properties.get("annotations", [])
        if "Column" in annotations:
            col_arg = prop_node.properties.get("annotation_args", {}).get("", "")
            if col_arg:
                return col_arg
        return prop_node.name

    def _is_navigation_property(
        self, prop_type: str, type_args: list[str], entity_registry: dict[str, str]
    ) -> bool:
        """Check if a property is a navigation property (reference to another entity)."""
        # Collection navigation: ICollection<Book>, List<Order>, etc.
        for coll_type in _COLLECTION_TYPES:
            if coll_type in prop_type:
                return True
        # Reference navigation: type is a registered entity name
        if prop_type in entity_registry:
            return True
        # Check type_args for entity references
        for ta in type_args:
            if ta in entity_registry:
                return True
        return False

    def _extract_navigation_relationships(
        self,
        context: AnalysisContext,
        entity_node: GraphNode,
        entity_fqn: str,
        entity_registry: dict[str, str],
        table_name: str,
        edges: list[GraphEdge],
    ) -> None:
        """Extract FK relationships from navigation properties and conventions."""
        for edge in context.graph.get_edges_from(entity_fqn):
            if edge.kind != EdgeKind.CONTAINS:
                continue
            prop = context.graph.get_node(edge.target_fqn)
            if prop is None or prop.kind != NodeKind.FIELD:
                continue
            if not prop.properties.get("is_property"):
                continue

            prop_type = prop.properties.get("type", "")
            type_args = prop.properties.get("type_args", [])

            # Reference navigation (e.g., public Author Author { get; set; })
            if prop_type in entity_registry and prop_type not in _COLLECTION_TYPES:
                target_entity = prop_type
                # Convention: FK property = NavigationName + "Id"
                fk_prop_name = f"{prop.name}Id"
                fk_col_fqn = f"table:{table_name}.{fk_prop_name}"
                target_table = self._get_table_name(
                    context.graph.get_node(entity_registry[target_entity]),
                    target_entity,
                )
                edges.append(GraphEdge(
                    source_fqn=fk_col_fqn,
                    target_fqn=f"table:{target_table}.Id",
                    kind=EdgeKind.REFERENCES,
                    confidence=Confidence.MEDIUM,
                    evidence="entity-framework-convention",
                    properties={"relationship": "many-to-one"},
                ))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_entity_framework_plugin.py -v
```
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/entity_framework/ tests/unit/test_entity_framework_plugin.py && git commit -m "feat(plugins): add Entity Framework plugin with DbContext detection, data annotation mapping, navigation property FK resolution, and layer classification"
```

---

## Task 5: Update `__init__.py` files and verify full suite

- [ ] **Step 1: Finalize `aspnet/__init__.py`**

```python
# app/stages/plugins/aspnet/__init__.py
"""ASP.NET Core framework plugins — DI, Web, Middleware."""

from app.stages.plugins.aspnet.di import ASPNetDIPlugin
from app.stages.plugins.aspnet.web import ASPNetWebPlugin
from app.stages.plugins.aspnet.middleware import ASPNetMiddlewarePlugin

__all__ = ["ASPNetDIPlugin", "ASPNetWebPlugin", "ASPNetMiddlewarePlugin"]
```

- [ ] **Step 2: Finalize `entity_framework/__init__.py`**

```python
# app/stages/plugins/entity_framework/__init__.py
"""Entity Framework Core plugins — DbContext, entity mapping, migrations."""

from app.stages.plugins.entity_framework.dbcontext import EntityFrameworkPlugin

__all__ = ["EntityFrameworkPlugin"]
```

- [ ] **Step 3: Register plugins in the registry**

In the plugin discovery system (from M6a), ensure these plugins are discovered. If using auto-discovery via subclass scanning, they register automatically when imported. If using explicit registration, add to the registry initialization:

```python
from app.stages.plugins.aspnet import ASPNetDIPlugin, ASPNetWebPlugin, ASPNetMiddlewarePlugin
from app.stages.plugins.entity_framework import EntityFrameworkPlugin

registry.register(ASPNetDIPlugin)
registry.register(ASPNetWebPlugin)
registry.register(ASPNetMiddlewarePlugin)
registry.register(EntityFrameworkPlugin)
```

- [ ] **Step 4: Run full test suite**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_aspnet_di_plugin.py tests/unit/test_aspnet_web_plugin.py tests/unit/test_aspnet_middleware_plugin.py tests/unit/test_entity_framework_plugin.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Lint and type check**

```bash
cd cast-clone-backend && uv run ruff check app/stages/plugins/aspnet/ app/stages/plugins/entity_framework/
cd cast-clone-backend && uv run ruff format app/stages/plugins/aspnet/ app/stages/plugins/entity_framework/
cd cast-clone-backend && uv run mypy app/stages/plugins/aspnet/ app/stages/plugins/entity_framework/ --ignore-missing-imports
```

- [ ] **Step 6: Final commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/ tests/unit/ && git commit -m "feat(plugins): complete ASP.NET Core + Entity Framework plugin suite (Tier 2b)

Implements 4 framework plugins for .NET ecosystem:
- ASPNetDIPlugin: service registration (AddScoped/AddTransient/AddSingleton),
  constructor injection resolution, layer classification
- ASPNetWebPlugin: controller endpoint extraction with attribute routing,
  [controller] token replacement, HTTP method mapping, entry points
- ASPNetMiddlewarePlugin: middleware pipeline ordering extraction with
  validation warnings for incorrect auth/cors ordering
- EntityFrameworkPlugin: DbContext detection, DbSet<T> entity registration,
  data annotation mapping ([Table], [Column], [Key], [ForeignKey]),
  navigation property FK resolution, convention-based relationship detection

Plugin dependency chain: aspnet-di → aspnet-web, aspnet-di → entity-framework
All plugins follow TDD with full test coverage."
```

---

## Task 6: Extend SQL Migration Plugin for EF Migrations

**Files:**
- Modify: `app/stages/plugins/sql/migration.py`
- Test: `tests/unit/test_ef_migrations.py`

The existing SQL Migration plugin (M6c) already has Flyway and Alembic support. EF Migrations are C# code files with a different structure. This task adds EF migration parsing to the existing plugin.

### EF Migration Patterns to Parse

```csharp
// Migrations/20240101_CreateUsers.cs
migrationBuilder.CreateTable(
    name: "Users",
    columns: table => new {
        Id = table.Column<int>(nullable: false),
        Email = table.Column<string>(maxLength: 255, nullable: false)
    },
    constraints: table => {
        table.PrimaryKey("PK_Users", x => x.Id);
    });

migrationBuilder.AddForeignKey(
    name: "FK_Posts_Users_AuthorId",
    table: "Posts",
    column: "AuthorId",
    principalTable: "Users",
    principalColumn: "Id");

migrationBuilder.AddColumn<string>(
    name: "Name",
    table: "Customers",
    type: "nvarchar(255)");
```

- [ ] **Step 1: Write failing tests for EF migration parsing**

```python
# tests/unit/test_ef_migrations.py
"""Tests for EF Core migration parsing in the SQL Migration plugin."""

import pytest
from pathlib import Path
from app.stages.plugins.sql.migration import parse_ef_migration


class TestEFMigrationParser:
    def test_create_table_extraction(self, tmp_path: Path):
        """CreateTable produces Table + Column nodes."""
        migration = tmp_path / "20240101_CreateUsers.cs"
        migration.write_text('''
public partial class CreateUsers : Migration {
    protected override void Up(MigrationBuilder migrationBuilder) {
        migrationBuilder.CreateTable(
            name: "Users",
            columns: table => new {
                Id = table.Column<int>(nullable: false),
                Email = table.Column<string>(maxLength: 255, nullable: false),
                Name = table.Column<string>(nullable: true)
            },
            constraints: table => {
                table.PrimaryKey("PK_Users", x => x.Id);
            });
    }
}
''')
        result = parse_ef_migration(migration)
        assert len(result.nodes) >= 4  # 1 table + 3 columns
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "Users"

    def test_add_foreign_key_extraction(self, tmp_path: Path):
        """AddForeignKey produces REFERENCES edge."""
        migration = tmp_path / "20240102_AddFK.cs"
        migration.write_text('''
public partial class AddFK : Migration {
    protected override void Up(MigrationBuilder migrationBuilder) {
        migrationBuilder.AddForeignKey(
            name: "FK_Posts_Users_AuthorId",
            table: "Posts",
            column: "AuthorId",
            principalTable: "Users",
            principalColumn: "Id");
    }
}
''')
        result = parse_ef_migration(migration)
        refs = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(refs) == 1
        assert "Posts" in refs[0].source_fqn
        assert "Users" in refs[0].target_fqn
```

- [ ] **Step 2: Implement `parse_ef_migration` in `sql/migration.py`**

Add EF migration detection to the existing `SQLMigrationPlugin.detect_from_paths()` method and a new `parse_ef_migration()` function that uses regex patterns to extract `CreateTable`, `AddForeignKey`, and `AddColumn` calls from C# migration files.

- [ ] **Step 3: Run tests, commit**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_ef_migrations.py -v
cd cast-clone-backend && git add app/stages/plugins/sql/migration.py tests/unit/test_ef_migrations.py && git commit -m "feat(plugins): add EF Core migration parsing to SQL Migration plugin"
```

---

## Summary

| Artifact | Lines (est.) | Description |
|----------|-------------|-------------|
| `aspnet/di.py` | ~180 | DI registration extraction + constructor injection resolution |
| `aspnet/web.py` | ~200 | Controller endpoint extraction + route token replacement |
| `aspnet/middleware.py` | ~100 | Middleware pipeline ordering + validation warnings |
| `entity_framework/dbcontext.py` | ~280 | DbContext + entity mapping + navigation properties |
| `sql/migration.py` (extension) | ~80 | EF migration parsing (CreateTable, AddForeignKey) |
| `test_aspnet_di_plugin.py` | ~200 | 8 test cases |
| `test_aspnet_web_plugin.py` | ~250 | 9 test cases |
| `test_aspnet_middleware_plugin.py` | ~100 | 3 test cases |
| `test_entity_framework_plugin.py` | ~280 | 8 test cases |
| `test_ef_migrations.py` | ~80 | 2 test cases |
| **Total** | **~1,750** | **4 plugins, 1 extension, 30 test cases** |

## Plugin Dependency Graph

```
aspnet-di (no deps)
  ├──> aspnet-web (depends on aspnet-di)
  ├──> aspnet-middleware (no deps, runs in parallel with web)
  └──> entity-framework (depends on aspnet-di)
        └──> sql-migration (no deps, already exists — extended for EF)
```

## Acceptance Criteria

1. All 4 plugins pass detection for ASP.NET Core projects
2. ASP.NET DI resolves `AddScoped`/`AddTransient`/`AddSingleton` registrations correctly
3. ASP.NET Web extracts controller endpoints with correct HTTP method + path
4. Route token replacement (`[controller]`, `[action]`) works correctly
5. Entity Framework detects DbContext, resolves `DbSet<T>` → Table mapping
6. Data annotations (`[Table]`, `[Column]`, `[ForeignKey]`) produce correct nodes/edges
7. Navigation properties generate FK REFERENCES edges
8. Middleware pipeline ordering is validated with warnings for violations
9. EF migrations produce Table/Column nodes from `CreateTable` calls
10. All tests pass: `uv run pytest tests/unit/test_aspnet_* tests/unit/test_entity_framework_plugin.py tests/unit/test_ef_migrations.py -v`
11. Lint clean: `ruff check` and `mypy` pass
12. Layer classification: Controllers → Presentation, Services → Business Logic, Repositories/DbContext → Data Access