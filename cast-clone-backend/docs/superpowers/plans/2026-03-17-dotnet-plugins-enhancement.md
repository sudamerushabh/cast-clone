# .NET Plugin Suite Enhancement & Expansion — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance 4 existing .NET plugins, add 2 new plugins (SignalR, gRPC), and consolidate all under `dotnet/` folder.

**Architecture:** All 6 plugins extend the `FrameworkPlugin` ABC. They read properties from graph nodes (populated by tree-sitter extractor in Stage 3) and produce new nodes/edges/layer assignments. The DI plugin is the foundation — all others depend on it. Tests use helper functions that manually construct graph nodes with the expected properties, so plugin development is independent of tree-sitter extractor changes.

**Tech Stack:** Python 3.12+, pytest + pytest-asyncio, dataclasses, structlog

**Spec:** `cast-clone-backend/docs/superpowers/specs/2026-03-17-dotnet-plugins-enhancement-design.md`

---

## File Map

### Files to Create

| File | Responsibility |
|------|---------------|
| `app/stages/plugins/dotnet/__init__.py` | Re-export all 6 plugin classes |
| `app/stages/plugins/dotnet/di.py` | ASP.NET DI plugin (moved + enhanced) |
| `app/stages/plugins/dotnet/web.py` | ASP.NET Web plugin (moved + enhanced) |
| `app/stages/plugins/dotnet/middleware.py` | ASP.NET Middleware plugin (moved + enhanced) |
| `app/stages/plugins/dotnet/entity_framework.py` | EF Core plugin (moved + enhanced) |
| `app/stages/plugins/dotnet/signalr.py` | SignalR plugin (NEW) |
| `app/stages/plugins/dotnet/grpc.py` | gRPC plugin (NEW) |
| `tests/unit/test_dotnet_di_plugin.py` | DI plugin tests (renamed + new tests) |
| `tests/unit/test_dotnet_web_plugin.py` | Web plugin tests (renamed + new tests) |
| `tests/unit/test_dotnet_middleware_plugin.py` | Middleware plugin tests (renamed + new tests) |
| `tests/unit/test_dotnet_entity_framework_plugin.py` | EF plugin tests (renamed + new tests) |
| `tests/unit/test_dotnet_signalr_plugin.py` | SignalR plugin tests (NEW) |
| `tests/unit/test_dotnet_grpc_plugin.py` | gRPC plugin tests (NEW) |

### Files to Modify

| File | Changes |
|------|---------|
| `app/models/context.py` | Add `dotnet_di_map` field to `AnalysisContext` |
| `app/stages/plugins/__init__.py` | Update imports from `dotnet/`, register new plugins |
| `tests/unit/helpers.py` | Add `is_override` to `add_method`, add `add_hub_class`, `add_grpc_service` |

### Files to Delete

| File | Reason |
|------|--------|
| `app/stages/plugins/aspnet/__init__.py` | Replaced by `dotnet/__init__.py` |
| `app/stages/plugins/aspnet/di.py` | Moved to `dotnet/di.py` |
| `app/stages/plugins/aspnet/web.py` | Moved to `dotnet/web.py` |
| `app/stages/plugins/aspnet/middleware.py` | Moved to `dotnet/middleware.py` |
| `app/stages/plugins/entity_framework/__init__.py` | Replaced by `dotnet/__init__.py` |
| `app/stages/plugins/entity_framework/dbcontext.py` | Moved to `dotnet/entity_framework.py` |
| `tests/unit/test_aspnet_di_plugin.py` | Renamed to `test_dotnet_di_plugin.py` |
| `tests/unit/test_aspnet_web_plugin.py` | Renamed to `test_dotnet_web_plugin.py` |
| `tests/unit/test_aspnet_middleware_plugin.py` | Renamed to `test_dotnet_middleware_plugin.py` |
| `tests/unit/test_entity_framework_plugin.py` | Renamed to `test_dotnet_entity_framework_plugin.py` |

---

## Task 1: Folder Consolidation

Move all .NET plugin files from `aspnet/` and `entity_framework/` into `dotnet/`. Update all imports. Verify all existing tests pass unchanged.

**Files:**
- Create: `app/stages/plugins/dotnet/__init__.py`
- Create: `app/stages/plugins/dotnet/di.py` (copy from `aspnet/di.py`)
- Create: `app/stages/plugins/dotnet/web.py` (copy from `aspnet/web.py`)
- Create: `app/stages/plugins/dotnet/middleware.py` (copy from `aspnet/middleware.py`)
- Create: `app/stages/plugins/dotnet/entity_framework.py` (copy from `entity_framework/dbcontext.py`)
- Modify: `app/stages/plugins/__init__.py`
- Delete: `app/stages/plugins/aspnet/` (entire directory)
- Delete: `app/stages/plugins/entity_framework/` (entire directory)
- Test: `tests/unit/test_dotnet_di_plugin.py` (renamed)
- Test: `tests/unit/test_dotnet_web_plugin.py` (renamed)
- Test: `tests/unit/test_dotnet_middleware_plugin.py` (renamed)
- Test: `tests/unit/test_dotnet_entity_framework_plugin.py` (renamed)

- [ ] **Step 1: Create `dotnet/` directory and copy plugin files**

```bash
mkdir -p cast-clone-backend/app/stages/plugins/dotnet
cp cast-clone-backend/app/stages/plugins/aspnet/di.py cast-clone-backend/app/stages/plugins/dotnet/di.py
cp cast-clone-backend/app/stages/plugins/aspnet/web.py cast-clone-backend/app/stages/plugins/dotnet/web.py
cp cast-clone-backend/app/stages/plugins/aspnet/middleware.py cast-clone-backend/app/stages/plugins/dotnet/middleware.py
cp cast-clone-backend/app/stages/plugins/entity_framework/dbcontext.py cast-clone-backend/app/stages/plugins/dotnet/entity_framework.py
```

- [ ] **Step 2: Create `dotnet/__init__.py`**

```python
"""ASP.NET Core / .NET framework plugins — DI, Web, Middleware, Entity Framework, SignalR, gRPC."""

from app.stages.plugins.dotnet.di import ASPNetDIPlugin
from app.stages.plugins.dotnet.entity_framework import EntityFrameworkPlugin
from app.stages.plugins.dotnet.middleware import ASPNetMiddlewarePlugin
from app.stages.plugins.dotnet.web import ASPNetWebPlugin

__all__ = [
    "ASPNetDIPlugin",
    "ASPNetWebPlugin",
    "ASPNetMiddlewarePlugin",
    "EntityFrameworkPlugin",
]
```

Note: `SignalRPlugin` and `GRPCPlugin` will be added to `__init__.py` when they are created in Tasks 8 and 9.

- [ ] **Step 3: Update `plugins/__init__.py` imports**

Replace all `aspnet.*` and `entity_framework.*` imports with `dotnet.*` imports:

```python
# OLD:
from app.stages.plugins.aspnet.di import ASPNetDIPlugin
from app.stages.plugins.aspnet.middleware import ASPNetMiddlewarePlugin
from app.stages.plugins.aspnet.web import ASPNetWebPlugin
from app.stages.plugins.entity_framework.dbcontext import EntityFrameworkPlugin

# NEW:
from app.stages.plugins.dotnet.di import ASPNetDIPlugin
from app.stages.plugins.dotnet.entity_framework import EntityFrameworkPlugin
from app.stages.plugins.dotnet.middleware import ASPNetMiddlewarePlugin
from app.stages.plugins.dotnet.web import ASPNetWebPlugin
```

Registry registrations remain unchanged — same class names.

- [ ] **Step 4: Rename test files and update their imports**

```bash
cd cast-clone-backend
cp tests/unit/test_aspnet_di_plugin.py tests/unit/test_dotnet_di_plugin.py
cp tests/unit/test_aspnet_web_plugin.py tests/unit/test_dotnet_web_plugin.py
cp tests/unit/test_aspnet_middleware_plugin.py tests/unit/test_dotnet_middleware_plugin.py
cp tests/unit/test_entity_framework_plugin.py tests/unit/test_dotnet_entity_framework_plugin.py
```

In each renamed test file, update the plugin import path:

- `test_dotnet_di_plugin.py`: `from app.stages.plugins.dotnet.di import ASPNetDIPlugin`
- `test_dotnet_web_plugin.py`: `from app.stages.plugins.dotnet.web import ASPNetWebPlugin`
- `test_dotnet_middleware_plugin.py`: `from app.stages.plugins.dotnet.middleware import ASPNetMiddlewarePlugin`
- `test_dotnet_entity_framework_plugin.py`: `from app.stages.plugins.dotnet.entity_framework import EntityFrameworkPlugin`

- [ ] **Step 5: Run all renamed tests to verify they pass**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_di_plugin.py tests/unit/test_dotnet_web_plugin.py tests/unit/test_dotnet_middleware_plugin.py tests/unit/test_dotnet_entity_framework_plugin.py -v
```

Expected: All existing tests pass with new import paths.

- [ ] **Step 6: Delete old directories and test files**

```bash
cd cast-clone-backend
rm -rf app/stages/plugins/aspnet/ app/stages/plugins/entity_framework/
rm tests/unit/test_aspnet_di_plugin.py tests/unit/test_aspnet_web_plugin.py tests/unit/test_aspnet_middleware_plugin.py tests/unit/test_entity_framework_plugin.py
```

- [ ] **Step 7: Run full test suite to verify nothing is broken**

```bash
cd cast-clone-backend
uv run pytest tests/unit/ -v
```

Expected: All tests pass. No import errors.

- [ ] **Step 8: Commit**

```bash
git add -A cast-clone-backend/app/stages/plugins/dotnet/ cast-clone-backend/app/stages/plugins/__init__.py cast-clone-backend/tests/unit/test_dotnet_*.py
git add -A cast-clone-backend/app/stages/plugins/aspnet/ cast-clone-backend/app/stages/plugins/entity_framework/ cast-clone-backend/tests/unit/test_aspnet_*.py cast-clone-backend/tests/unit/test_entity_framework_plugin.py
git commit -m "refactor: consolidate .NET plugins under dotnet/ folder"
```

---

## Task 2: AnalysisContext + Test Helpers Update

Add the `dotnet_di_map` field to `AnalysisContext` and enhance test helpers with `is_override` support and new helper functions.

**Note:** This is a pure infrastructure task — no failing-test-first cycle. The new field and helpers are verified through downstream tasks (Task 3 tests `dotnet_di_map`, Task 8 tests `add_hub_class`, Task 9 tests `add_grpc_service`). Step 4 runs existing tests to verify backward compatibility.

**Files:**
- Modify: `app/models/context.py:21-62`
- Modify: `tests/unit/helpers.py:59-134`

- [ ] **Step 1: Add `dotnet_di_map` field to `AnalysisContext`**

In `app/models/context.py`, add after the `layer_assignments` field (line 46):

```python
    # Stage 5 DI map: shared between .NET plugins (interface_name -> impl_fqn)
    dotnet_di_map: dict[str, str] = field(default_factory=dict)
```

- [ ] **Step 2: Add `is_override` kwarg to `add_method` helper**

In `tests/unit/helpers.py`, update the `add_method` function signature and body:

```python
def add_method(
    graph: SymbolGraph,
    class_fqn: str,
    method_name: str,
    *,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    parameters: list[dict] | None = None,
    return_type: str = "void",
    is_constructor: bool = False,
    is_override: bool = False,
) -> GraphNode:
    """Add a FUNCTION node to the graph and a CONTAINS edge from its parent class."""
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
            "is_override": is_override,
        },
    )
    graph.add_node(node)
    graph.add_edge(
        GraphEdge(
            source_fqn=class_fqn,
            target_fqn=fqn,
            kind=EdgeKind.CONTAINS,
            confidence=Confidence.HIGH,
            evidence="treesitter",
        )
    )
    return node
```

- [ ] **Step 3: Add `add_hub_class` helper**

Append to `tests/unit/helpers.py`:

```python
def add_hub_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    *,
    hub_type_arg: str | None = None,
    methods: list[str] | None = None,
    client_events: list[str] | None = None,
) -> GraphNode:
    """Add a SignalR Hub class node with optional methods and client events.

    Args:
        hub_type_arg: Generic type arg for strongly-typed hubs (e.g., "INotificationClient").
        methods: List of hub method names to add (excluding lifecycle methods).
        client_events: Shared list of client event names. For test convenience, this is
            assigned to ALL hub methods (not per-method). The plugin itself discovers events
            from either method-level client_events OR strongly-typed hub interface methods.
    """
    base_class = f"Hub<{hub_type_arg}>" if hub_type_arg else "Hub"
    node = add_class(graph, fqn, name, base_class=base_class)

    for method_name in (methods or []):
        method_node = add_method(graph, fqn, method_name, return_type="Task")
        if client_events:
            method_node.properties["client_events"] = list(client_events)

    return node


def add_grpc_service(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    *,
    base_class: str,
    override_methods: list[dict] | None = None,
) -> GraphNode:
    """Add a gRPC service class node with override methods.

    Args:
        base_class: The protobuf-generated base class (e.g., "Greeter.GreeterBase").
        override_methods: List of dicts with keys: name, request_type, response_type.
    """
    node = add_class(graph, fqn, name, base_class=base_class)

    for method_info in (override_methods or []):
        add_method(
            graph,
            fqn,
            method_info["name"],
            is_override=True,
            parameters=[{"name": "request", "type": method_info.get("request_type", "object")}],
            return_type=method_info.get("response_type", "Task<object>"),
        )

    return node
```

- [ ] **Step 4: Run existing tests to verify nothing broke**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_di_plugin.py tests/unit/test_dotnet_web_plugin.py -v
```

Expected: All existing tests still pass (no signature changes affect existing callers since `is_override` defaults to `False`).

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/models/context.py cast-clone-backend/tests/unit/helpers.py
git commit -m "feat: add dotnet_di_map to AnalysisContext, enhance test helpers"
```

---

## Task 3: DI Plugin Enhancements

Add keyed services, open generic registrations, AddDbContext wiring, shared DI map, and FromKeyedServices constructor resolution.

**Files:**
- Modify: `app/stages/plugins/dotnet/di.py`
- Test: `tests/unit/test_dotnet_di_plugin.py`

- [ ] **Step 1: Write failing test for AddDbContext wiring**

Append to `tests/unit/test_dotnet_di_plugin.py`:

```python
class TestAddDbContextWiring:
    @pytest.mark.asyncio
    async def test_adddbcontext_creates_self_registration(self):
        """AddDbContext<AppDbContext> creates a self-registration INJECTS edge."""
        plugin = ASPNetDIPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddDbContext", "interface": "AppDbContext", "implementation": ""},
        ])
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")

        # Controller that takes AppDbContext in constructor
        add_class(ctx.graph, "MyApp.UserService", "UserService")
        add_method(
            ctx.graph, "MyApp.UserService", ".ctor",
            is_constructor=True,
            parameters=[{"name": "db", "type": "AppDbContext"}],
        )

        result = await plugin.extract(ctx)
        ctor_edges = [e for e in result.edges if e.properties.get("injection_type") == "constructor"]
        assert any(
            e.source_fqn == "MyApp.UserService" and e.target_fqn == "MyApp.Data.AppDbContext"
            for e in ctor_edges
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_di_plugin.py::TestAddDbContextWiring -v
```

Expected: FAIL — AddDbContext with empty implementation doesn't create a self-registration.

- [ ] **Step 3: Implement AddDbContext self-registration in `_collect_registrations`**

In `app/stages/plugins/dotnet/di.py`, the existing `if not impl_name: impl_name = interface_name` already handles the self-registration case for `AddDbContext` (empty implementation → uses interface name as impl name). No code change needed for registration itself. However, verify that `AddDbContext` entries in `di_registrations` with empty `implementation` are correctly picked up by the existing logic. If the test from Step 1 passes without changes, this step is a no-op — the existing self-registration logic already covers it.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_di_plugin.py::TestAddDbContextWiring -v
```

Expected: PASS

- [ ] **Step 5: Write failing test for keyed services**

Append to `tests/unit/test_dotnet_di_plugin.py`:

```python
class TestKeyedServices:
    @pytest.mark.asyncio
    async def test_keyed_registration_includes_key_in_edge(self):
        """AddKeyedScoped<I, T>('mykey') stores the key in INJECTS edge properties."""
        plugin = ASPNetDIPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddKeyedScoped", "interface": "ICache", "implementation": "RedisCache", "key": "redis"},
        ])
        add_class(ctx.graph, "MyApp.ICache", "ICache", is_interface=True)
        add_class(ctx.graph, "MyApp.RedisCache", "RedisCache", implements=["ICache"])

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) >= 1
        keyed_edge = [e for e in inject_edges if e.properties.get("key") == "redis"]
        assert len(keyed_edge) == 1

    @pytest.mark.asyncio
    async def test_keyed_constructor_resolution_via_from_keyed_services(self):
        """Constructor param with FromKeyedServices resolves to keyed registration."""
        plugin = ASPNetDIPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddKeyedScoped", "interface": "ICache", "implementation": "RedisCache", "key": "redis"},
            {"method": "AddKeyedScoped", "interface": "ICache", "implementation": "MemCache", "key": "memory"},
        ])
        add_class(ctx.graph, "MyApp.ICache", "ICache", is_interface=True)
        add_class(ctx.graph, "MyApp.RedisCache", "RedisCache", implements=["ICache"])
        add_class(ctx.graph, "MyApp.MemCache", "MemCache", implements=["ICache"])

        add_class(ctx.graph, "MyApp.MyService", "MyService")
        add_method(
            ctx.graph, "MyApp.MyService", ".ctor",
            is_constructor=True,
            parameters=[{
                "name": "cache", "type": "ICache",
                "annotations": ["FromKeyedServices"],
                "annotation_args": {"FromKeyedServices": "redis"},
            }],
        )

        result = await plugin.extract(ctx)
        ctor_edges = [e for e in result.edges if e.properties.get("injection_type") == "constructor"]
        assert any(e.target_fqn == "MyApp.RedisCache" for e in ctor_edges)
        assert not any(e.target_fqn == "MyApp.MemCache" for e in ctor_edges)
```

- [ ] **Step 6: Implement keyed services support**

In `app/stages/plugins/dotnet/di.py`:

1. Add `key: str | None = None` field to `_DIRegistration` dataclass.
2. Add `"AddKeyedScoped": "scoped", "AddKeyedTransient": "transient", "AddKeyedSingleton": "singleton"` to `_LIFETIME_MAP`.
3. In `_collect_registrations`, read `reg.key = reg_dict.get("key")`.
4. In the INJECTS edge creation (Phase 2), add `props["key"] = reg.key` when key is present.
5. In `_resolve_constructor_injection`, update param resolution:
   - Check if param has `FromKeyedServices` in its annotations
   - If so, extract the key from `param.get("annotation_args", {}).get("FromKeyedServices")`
   - Build a keyed lookup: `(interface_name, key) -> impl_fqn`
   - Match keyed params against keyed lookup; non-keyed params use existing type-only lookup

- [ ] **Step 7: Run keyed services tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_di_plugin.py::TestKeyedServices -v
```

Expected: PASS

- [ ] **Step 8: Write failing test for open generics**

Append to `tests/unit/test_dotnet_di_plugin.py`:

```python
class TestOpenGenerics:
    @pytest.mark.asyncio
    async def test_open_generic_resolves_closed_type(self):
        """AddScoped(typeof(IRepo<>), typeof(Repo<>)) resolves IRepo<User> -> Repo<User>."""
        plugin = ASPNetDIPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddScoped", "interface": "IRepo<>", "implementation": "Repo<>", "is_open_generic": True},
        ])
        add_class(ctx.graph, "MyApp.IRepo", "IRepo", is_interface=True)
        add_class(ctx.graph, "MyApp.Repo", "Repo")

        add_class(ctx.graph, "MyApp.UserService", "UserService")
        add_method(
            ctx.graph, "MyApp.UserService", ".ctor",
            is_constructor=True,
            parameters=[{"name": "repo", "type": "IRepo<User>"}],
        )

        result = await plugin.extract(ctx)
        ctor_edges = [e for e in result.edges if e.properties.get("injection_type") == "constructor"]
        assert len(ctor_edges) >= 1
        assert ctor_edges[0].target_fqn == "MyApp.Repo"
        assert ctor_edges[0].confidence == Confidence.MEDIUM
```

- [ ] **Step 9: Implement open generic resolution**

In `app/stages/plugins/dotnet/di.py`:

1. In `_collect_registrations`, detect open generics: when `reg_dict.get("is_open_generic")` is True or interface name ends with `<>`, store in a separate list on the plugin instance `self._open_generics`.
2. In `_resolve_constructor_injection`, after the normal `di_lookup.get(param_type)` fails, check if `param_type` contains `<` (it's a closed generic like `IRepo<User>`). If so, extract the base type (`IRepo`), look for a matching open generic registration, and resolve to the implementation's base FQN with `Confidence.MEDIUM`.

- [ ] **Step 10: Run open generic test**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_di_plugin.py::TestOpenGenerics -v
```

Expected: PASS

- [ ] **Step 11: Write failing test for shared DI map**

```python
class TestSharedDIMap:
    @pytest.mark.asyncio
    async def test_di_map_stored_on_context(self):
        """After extraction, context.dotnet_di_map contains interface->impl mappings."""
        plugin = ASPNetDIPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddScoped", "interface": "IUserService", "implementation": "UserService"},
        ])
        add_class(ctx.graph, "MyApp.IUserService", "IUserService", is_interface=True)
        add_class(ctx.graph, "MyApp.UserService", "UserService")

        await plugin.extract(ctx)
        assert ctx.dotnet_di_map.get("IUserService") == "MyApp.UserService"
```

- [ ] **Step 12: Implement shared DI map**

In `extract()`, after building `di_lookup` in `_resolve_constructor_injection`, set `context.dotnet_di_map = di_lookup`. Move the lookup construction earlier so it's accessible, or return it from the method.

- [ ] **Step 13: Run all DI tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_di_plugin.py -v
```

Expected: All tests pass (old + new).

- [ ] **Step 14: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/dotnet/di.py cast-clone-backend/tests/unit/test_dotnet_di_plugin.py
git commit -m "feat(dotnet): enhance DI plugin with keyed services, open generics, shared DI map"
```

---

## Task 4: Web Plugin Enhancements

Add `[FromBody]` DTO linking, HttpOptions/Head verbs, extension method endpoints, and `[Route]` override.

**Files:**
- Modify: `app/stages/plugins/dotnet/web.py`
- Test: `tests/unit/test_dotnet_web_plugin.py`

- [ ] **Step 1: Write failing test for HttpOptions/HttpHead**

Append to `tests/unit/test_dotnet_web_plugin.py`:

```python
class TestAdditionalHttpVerbs:
    @pytest.mark.asyncio
    async def test_http_options_and_head(self) -> None:
        """HttpOptions and HttpHead attributes produce OPTIONS and HEAD endpoints."""
        ctx = make_dotnet_context()
        class_fqn = "MyApp.Controllers.UsersController"
        add_class(ctx.graph, class_fqn, "UsersController", base_class="ControllerBase",
                  annotations=["ApiController", "Route"], annotation_args={"": "api/[controller]"})
        add_method(ctx.graph, class_fqn, "Options", annotations=["HttpOptions"])
        add_method(ctx.graph, class_fqn, "Head", annotations=["HttpHead"])

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)
        methods = {n.properties["method"] for n in result.nodes}
        assert "OPTIONS" in methods
        assert "HEAD" in methods
```

- [ ] **Step 2: Implement HttpOptions/HttpHead**

In `app/stages/plugins/dotnet/web.py`, add to `_HTTP_METHODS` and `_MAP_METHODS`:

```python
_HTTP_METHODS["HttpOptions"] = "OPTIONS"
_HTTP_METHODS["HttpHead"] = "HEAD"
_MAP_METHODS["MapOptions"] = "OPTIONS"
_MAP_METHODS["MapHead"] = "HEAD"
```

- [ ] **Step 3: Run test**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_web_plugin.py::TestAdditionalHttpVerbs -v
```

Expected: PASS

- [ ] **Step 4: Write failing test for `[FromBody]` DTO linking**

```python
class TestDTOLinking:
    @pytest.mark.asyncio
    async def test_frombody_creates_depends_on_edge(self) -> None:
        """[FromBody] parameter on a controller method creates DEPENDS_ON edge to DTO class."""
        ctx = make_dotnet_context()
        class_fqn = "MyApp.Controllers.UsersController"
        add_class(ctx.graph, class_fqn, "UsersController", base_class="ControllerBase",
                  annotations=["ApiController", "Route"], annotation_args={"": "api/[controller]"})
        add_method(ctx.graph, class_fqn, "Create", annotations=["HttpPost"],
                   parameters=[{
                       "name": "dto", "type": "CreateUserDto",
                       "annotations": ["FromBody"],
                   }])
        add_class(ctx.graph, "MyApp.Dtos.CreateUserDto", "CreateUserDto")

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)

        depends_edges = [e for e in result.edges if e.kind == EdgeKind.DEPENDS_ON]
        assert len(depends_edges) == 1
        assert depends_edges[0].target_fqn == "MyApp.Dtos.CreateUserDto"
        assert depends_edges[0].properties.get("binding") == "body"
```

- [ ] **Step 5: Implement DTO linking**

In `app/stages/plugins/dotnet/web.py`, in the method scanning loop, after creating the endpoint node and edges, add:

```python
# DTO linking for [FromBody], [FromQuery], [FromRoute]
_BINDING_ATTRS = {"FromBody": "body", "FromQuery": "query", "FromRoute": "route"}

params = method_node.properties.get("parameters", [])
for param in params:
    if not isinstance(param, dict):
        continue
    param_annotations = param.get("annotations", [])
    for attr_name, binding_type in _BINDING_ATTRS.items():
        if attr_name in param_annotations:
            param_type = param.get("type", "")
            dto_fqn = name_to_fqn.get(param_type)
            if dto_fqn:
                edges.append(GraphEdge(
                    source_fqn=endpoint_fqn,
                    target_fqn=dto_fqn,
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=Confidence.HIGH,
                    evidence="aspnet-web",
                    properties={"binding": binding_type},
                ))
```

Build the `name_to_fqn` index at the top of `extract()` (same pattern as the DI plugin).

- [ ] **Step 6: Run DTO linking test**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_web_plugin.py::TestDTOLinking -v
```

Expected: PASS

- [ ] **Step 7: Write failing test for extension method endpoints**

```python
class TestExtensionEndpoints:
    @pytest.mark.asyncio
    async def test_extension_method_endpoints_extracted(self) -> None:
        """Extension method endpoints (1-hop) are extracted via extension_endpoints property."""
        ctx = make_dotnet_context()
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.UserEndpoints", name="UserEndpoints", kind=NodeKind.CLASS, language="csharp",
            properties={"extension_endpoints": [
                {"method": "MapGet", "path": "/api/users", "handler_fqn": "MyApp.Handlers.GetUsers"},
                {"method": "MapPost", "path": "/api/users", "handler_fqn": "MyApp.Handlers.CreateUser"},
            ]},
        ))

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)
        endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoints) == 2
        methods = {n.properties["method"] for n in endpoints}
        assert methods == {"GET", "POST"}
```

- [ ] **Step 8: Implement extension method endpoint extraction**

In `_extract_minimal_apis`, the existing loop already iterates over ALL class nodes. Inside that loop (which processes `minimal_api_endpoints` and `minimal_api_groups`), add a third block for `extension_endpoints`. This means extension endpoints are discovered on any class node in the graph, not just the Program class — which is correct because extension methods live in separate static classes:

```python
# Extension method endpoints (1-hop) — lives on extension method classes, not Program
extension_eps = class_node.properties.get("extension_endpoints", [])
for ep_data in extension_eps:
    self._create_minimal_endpoint(graph, ep_data, "", nodes, edges, entry_points)
```

- [ ] **Step 9: Write failing test for `[Route]` override**

```python
class TestRouteOverride:
    @pytest.mark.asyncio
    async def test_absolute_route_overrides_class_prefix(self) -> None:
        """Method-level [Route('/custom/path')] overrides class prefix entirely."""
        ctx = make_dotnet_context()
        class_fqn = "MyApp.Controllers.UsersController"
        add_class(ctx.graph, class_fqn, "UsersController", base_class="ControllerBase",
                  annotations=["ApiController", "Route"], annotation_args={"": "api/[controller]"})
        add_method(ctx.graph, class_fqn, "Health", annotations=["HttpGet", "Route"],
                   annotation_args={"": "", "Route": "/health"})

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)
        assert result.node_count == 1
        assert result.nodes[0].properties["path"] == "/health"

    @pytest.mark.asyncio
    async def test_relative_route_replaces_method_segment(self) -> None:
        """Method-level [Route('custom')] replaces verb path but keeps class prefix."""
        ctx = make_dotnet_context()
        class_fqn = "MyApp.Controllers.UsersController"
        add_class(ctx.graph, class_fqn, "UsersController", base_class="ControllerBase",
                  annotations=["ApiController", "Route"], annotation_args={"": "api/[controller]"})
        add_method(ctx.graph, class_fqn, "Custom", annotations=["HttpGet", "Route"],
                   annotation_args={"": "", "Route": "custom"})

        plugin = ASPNetWebPlugin()
        result = await plugin.extract(ctx)
        assert result.node_count == 1
        assert result.nodes[0].properties["path"] == "/api/users/custom"
```

- [ ] **Step 10: Implement `[Route]` override logic**

In the method scanning loop in `extract()`, after determining `method_path` from the HTTP verb attribute, add:

```python
# [Route] on method overrides the verb path
if "Route" in method_annotations:
    route_path = method_annotation_args.get("Route", "")
    if route_path:
        if route_path.startswith("/") or route_path.startswith("~/"):
            # Absolute route — overrides everything
            full_path = route_path.lstrip("~")
            full_path = _ROUTE_PARAM_RE.sub(r":\1", full_path)
            # Skip normal path combination
        else:
            # Relative route — replaces method-level segment
            method_path = route_path
```

Restructure the path combination to be conditional on whether an absolute route was found.

- [ ] **Step 11: Run all web plugin tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_web_plugin.py -v
```

Expected: All tests pass.

- [ ] **Step 12: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/dotnet/web.py cast-clone-backend/tests/unit/test_dotnet_web_plugin.py
git commit -m "feat(dotnet): enhance Web plugin with DTO linking, extra verbs, extension endpoints, Route override"
```

---

## Task 5: Middleware Plugin Enhancements

Fix `depends_on`, add custom middleware class resolution, terminal middleware, technology nodes, and layer classification.

**Files:**
- Modify: `app/stages/plugins/dotnet/middleware.py`
- Test: `tests/unit/test_dotnet_middleware_plugin.py`

- [ ] **Step 1: Fix `depends_on` and add layer classification**

In `app/stages/plugins/dotnet/middleware.py`:
- Change `depends_on: list[str] = []` to `depends_on: list[str] = ["aspnet-di"]`
- Add `get_layer_classification()` method:

```python
    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[
            LayerRule(pattern="Middleware", layer="Cross-Cutting"),
        ])
```

Add the necessary imports: `LayerRule, LayerRules` from `app.stages.plugins.base`.

- [ ] **Step 2: Write failing test for custom middleware class resolution**

Append to `tests/unit/test_dotnet_middleware_plugin.py`:

```python
from tests.unit.helpers import add_class, add_method


class TestCustomMiddlewareResolution:
    @pytest.mark.asyncio
    async def test_use_middleware_resolves_to_class(self):
        """UseMiddleware<RequestLoggingMiddleware> creates HANDLES edge to the middleware class."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(ctx.graph, "MyApp.Program", "Program",
                           middleware_calls=["UseRouting", "UseMiddleware<RequestLoggingMiddleware>", "UseAuthorization"])

        # The custom middleware class with InvokeAsync method
        add_class(ctx.graph, "MyApp.RequestLoggingMiddleware", "RequestLoggingMiddleware")
        add_method(ctx.graph, "MyApp.RequestLoggingMiddleware", "InvokeAsync", return_type="Task")

        result = await plugin.extract(ctx)

        handles_edges = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        assert len(handles_edges) >= 1
        assert any(e.source_fqn == "MyApp.RequestLoggingMiddleware" for e in handles_edges)

    @pytest.mark.asyncio
    async def test_custom_middleware_classified_as_cross_cutting(self):
        """Custom middleware classes resolved via UseMiddleware<T> get Cross-Cutting layer."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(ctx.graph, "MyApp.Program", "Program",
                           middleware_calls=["UseMiddleware<TenantMiddleware>"])
        add_class(ctx.graph, "MyApp.TenantMiddleware", "TenantMiddleware")
        add_method(ctx.graph, "MyApp.TenantMiddleware", "Invoke", return_type="Task")

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.TenantMiddleware") == "Cross-Cutting"
```

- [ ] **Step 3: Implement custom middleware class resolution**

In `extract()`, the existing code already builds a `mw_fqns: list[str]` list of middleware component FQNs (one per middleware call). After that loop, add the resolution logic:

```python
import re

_USE_MIDDLEWARE_RE = re.compile(r"^UseMiddleware<(\w+)>$")

# mw_fqns is already built above: mw_fqns[i] corresponds to middleware_calls[i]
# Resolve UseMiddleware<T> to actual middleware classes
for i, mw_name in enumerate(middleware_calls):
    match = _USE_MIDDLEWARE_RE.match(mw_name)
    if not match:
        continue
    type_name = match.group(1)

    # Find the class node in the graph
    for graph_node in graph.nodes.values():
        if graph_node.name == type_name and graph_node.kind == NodeKind.CLASS:
            # Verify it has Invoke or InvokeAsync method
            has_invoke = False
            for edge in graph.get_edges_from(graph_node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                child = graph.get_node(edge.target_fqn)
                if child and child.kind == NodeKind.FUNCTION and child.name in ("Invoke", "InvokeAsync"):
                    has_invoke = True
                    break

            if has_invoke:
                edges.append(GraphEdge(
                    source_fqn=graph_node.fqn,
                    target_fqn=mw_fqns[i],
                    kind=EdgeKind.HANDLES,
                    confidence=Confidence.HIGH,
                    evidence="aspnet-middleware",
                ))
                layer_assignments[graph_node.fqn] = "Cross-Cutting"
            break
```

Add `layer_assignments: dict[str, str] = {}` at the top of `extract()` and include it in the returned `PluginResult`.

- [ ] **Step 4: Run custom middleware tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_middleware_plugin.py::TestCustomMiddlewareResolution -v
```

Expected: PASS

- [ ] **Step 5: Write failing test for technology nodes**

```python
class TestTechnologyNodes:
    @pytest.mark.asyncio
    async def test_known_middleware_creates_technology_node(self):
        """UseAuthentication creates a technology COMPONENT node."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(ctx.graph, "MyApp.Program", "Program",
                           middleware_calls=["UseAuthentication", "UseAuthorization", "UseCors"])

        result = await plugin.extract(ctx)

        tech_nodes = [n for n in result.nodes if n.properties.get("technology")]
        assert len(tech_nodes) == 3
        tech_names = {n.properties["name"] for n in tech_nodes}
        assert "Authentication" in tech_names
        assert "Authorization" in tech_names
        assert "CORS" in tech_names
```

- [ ] **Step 6: Implement technology node creation**

Add at module level:

```python
_TECHNOLOGY_MAP: dict[str, str] = {
    "UseAuthentication": "Authentication",
    "UseAuthorization": "Authorization",
    "UseCors": "CORS",
    "UseRateLimiter": "Rate Limiting",
    "UseResponseCaching": "Response Caching",
    "UseHttpsRedirection": "HTTPS Redirection",
    "UseStaticFiles": "Static Files",
    "UseHsts": "HSTS",
}
```

In `extract()`, after creating middleware component nodes:

```python
for mw_name in middleware_calls:
    tech_name = _TECHNOLOGY_MAP.get(mw_name)
    if tech_name:
        tech_fqn = f"technology:aspnet:{tech_name.lower().replace(' ', '-')}"
        nodes.append(GraphNode(
            fqn=tech_fqn,
            name=tech_name,
            kind=NodeKind.COMPONENT,
            language="csharp",
            properties={"technology": True, "name": tech_name, "framework": "aspnet"},
        ))
```

- [ ] **Step 7: Write failing test for terminal middleware**

```python
class TestTerminalMiddleware:
    @pytest.mark.asyncio
    async def test_map_controllers_is_terminal(self):
        """MapControllers() is stored as a terminal middleware component."""
        plugin = ASPNetMiddlewarePlugin()
        ctx = make_dotnet_context()

        _add_program_class(ctx.graph, "MyApp.Program", "Program",
                           middleware_calls=["UseRouting", "MapControllers"])

        result = await plugin.extract(ctx)

        map_ctrl = [n for n in result.nodes if n.name == "MapControllers"]
        assert len(map_ctrl) == 1
        assert map_ctrl[0].properties.get("terminal") is True
```

- [ ] **Step 8: Implement terminal middleware detection**

When creating middleware component nodes, check if name starts with `Map`:

```python
_TERMINAL_MIDDLEWARE = frozenset({"MapControllers", "MapRazorPages"})
_TERMINAL_GENERIC_RE = re.compile(r"^(MapHub|MapGrpcService)<(\w+)>$")

# In the node creation loop:
is_terminal = mw_name in _TERMINAL_MIDDLEWARE
generic_match = _TERMINAL_GENERIC_RE.match(mw_name)
if generic_match:
    is_terminal = True
    mw_props["generic_type"] = generic_match.group(2)
if is_terminal:
    mw_props["terminal"] = True
```

- [ ] **Step 9: Run all middleware tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_middleware_plugin.py -v
```

Expected: All tests pass.

- [ ] **Step 10: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/dotnet/middleware.py cast-clone-backend/tests/unit/test_dotnet_middleware_plugin.py
git commit -m "feat(dotnet): enhance Middleware plugin with class resolution, tech nodes, terminal detection"
```

---

## Task 6: Entity Framework Plugin Enhancements (Part 1 — Annotations)

Convention PK, `[NotMapped]`, `[Required]`/`[MaxLength]`, `[InverseProperty]`.

**Files:**
- Modify: `app/stages/plugins/dotnet/entity_framework.py`
- Test: `tests/unit/test_dotnet_entity_framework_plugin.py`

- [ ] **Step 1: Write failing test for convention-based PK**

Append to `tests/unit/test_dotnet_entity_framework_plugin.py`:

```python
class TestConventionPK:
    @pytest.mark.asyncio
    async def test_id_property_inferred_as_pk(self):
        """Property named 'Id' is inferred as PK even without [Key] annotation."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True)
        add_field(ctx.graph, "MyApp.Models.User", "Name", "string", is_property=True)

        result = await plugin.extract(ctx)
        col_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        id_col = [n for n in col_nodes if n.name == "Id"]
        assert len(id_col) == 1
        assert id_col[0].properties.get("is_primary_key") is True

    @pytest.mark.asyncio
    async def test_classname_id_inferred_as_pk(self):
        """Property named '{ClassName}Id' (e.g., 'UserId') is inferred as PK."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "UserId", "int", is_property=True)

        result = await plugin.extract(ctx)
        col_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        pk_col = [n for n in col_nodes if n.name == "UserId"]
        assert len(pk_col) == 1
        assert pk_col[0].properties.get("is_primary_key") is True
```

- [ ] **Step 2: Implement convention PK in `_find_pk_column`**

In `app/stages/plugins/dotnet/entity_framework.py`, update `_find_pk_column`:

```python
    def _find_pk_column(self, entity: _EntityInfo) -> str | None:
        """Find the primary key column name for an entity."""
        # 1. Explicit [Key] annotation
        for field_info in entity.fields:
            if field_info.is_key:
                if "Column" in field_info.annotations:
                    col_override = field_info.annotation_args.get("", "")
                    if col_override:
                        return col_override
                return field_info.name

        # 2. Convention: "Id" or "{ClassName}Id"
        for field_info in entity.fields:
            if field_info.name == "Id" or field_info.name == f"{entity.name}Id":
                return field_info.name

        return None
```

Also update field processing in Step 3 to mark convention PKs as `is_primary_key`:

```python
is_pk = field_info.is_key
if not is_pk:
    is_pk = field_info.name == "Id" or field_info.name == f"{entity.name}Id"
```

Use `is_pk` instead of `field_info.is_key` when setting `is_primary_key` on column nodes.

- [ ] **Step 3: Run convention PK tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_entity_framework_plugin.py::TestConventionPK -v
```

Expected: PASS

- [ ] **Step 4: Write failing test for `[NotMapped]`**

```python
class TestNotMapped:
    @pytest.mark.asyncio
    async def test_notmapped_property_skipped(self):
        """[NotMapped] properties do not generate column nodes."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True, annotations=["Key"])
        add_field(ctx.graph, "MyApp.Models.User", "Name", "string", is_property=True)
        add_field(ctx.graph, "MyApp.Models.User", "FullName", "string", is_property=True, annotations=["NotMapped"])

        result = await plugin.extract(ctx)
        col_names = {n.name for n in result.nodes if n.kind == NodeKind.COLUMN}
        assert "Id" in col_names
        assert "Name" in col_names
        assert "FullName" not in col_names
```

- [ ] **Step 5: Implement `[NotMapped]`**

In the field processing loop (Step 3 in `extract()`), add before the navigation checks:

```python
if "NotMapped" in field_info.annotations:
    continue
```

- [ ] **Step 6: Write failing test for `[Required]`/`[MaxLength]`**

```python
class TestColumnMetadata:
    @pytest.mark.asyncio
    async def test_required_sets_nullable_false(self):
        """[Required] annotation sets is_nullable: false on column node."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True, annotations=["Key"])
        add_field(ctx.graph, "MyApp.Models.User", "Email", "string", is_property=True, annotations=["Required", "MaxLength"],
                  annotation_args={"MaxLength": "100"})

        result = await plugin.extract(ctx)
        email_col = [n for n in result.nodes if n.kind == NodeKind.COLUMN and n.name == "Email"]
        assert len(email_col) == 1
        assert email_col[0].properties.get("is_nullable") is False
        assert email_col[0].properties.get("max_length") == "100"
```

- [ ] **Step 7: Implement `[Required]`/`[MaxLength]` metadata**

When creating column nodes, add to properties:

```python
"is_nullable": "Required" not in field_info.annotations,
"max_length": field_info.annotation_args.get("MaxLength"),
```

- [ ] **Step 8: Write failing test for `[InverseProperty]`**

```python
class TestInverseProperty:
    @pytest.mark.asyncio
    async def test_inverse_property_disambiguates_navigation(self):
        """[InverseProperty] disambiguates when entity has multiple navs to same target."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Posts", "DbSet<Post>", is_property=True, type_args=["Post"])

        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True, annotations=["Key"])
        add_field(ctx.graph, "MyApp.Models.User", "AuthoredPosts", "ICollection<Post>", is_property=True,
                  type_args=["Post"], annotations=["InverseProperty"], annotation_args={"InverseProperty": "Author"})
        add_field(ctx.graph, "MyApp.Models.User", "EditedPosts", "ICollection<Post>", is_property=True,
                  type_args=["Post"], annotations=["InverseProperty"], annotation_args={"InverseProperty": "Editor"})

        add_class(ctx.graph, "MyApp.Models.Post", "Post")
        add_field(ctx.graph, "MyApp.Models.Post", "Id", "int", is_property=True, annotations=["Key"])
        add_field(ctx.graph, "MyApp.Models.Post", "AuthorId", "int", is_property=True)
        add_field(ctx.graph, "MyApp.Models.Post", "Author", "User", is_property=True)
        add_field(ctx.graph, "MyApp.Models.Post", "EditorId", "int", is_property=True)
        add_field(ctx.graph, "MyApp.Models.Post", "Editor", "User", is_property=True)

        result = await plugin.extract(ctx)

        # Should not emit "no FK found" warnings since InverseProperty disambiguates
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        # AuthorId -> User.Id, EditorId -> User.Id
        assert len(ref_edges) >= 2
```

- [ ] **Step 9: Implement `[InverseProperty]` logic**

In `_infer_fk_from_navigation`, check if the collection nav field has an `[InverseProperty]` annotation. If so, use the specified property name to find the matching reference navigation on the target entity. From the reference nav, derive the FK name as `{NavPropertyName}Id`.

- [ ] **Step 10: Run all annotation tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_entity_framework_plugin.py -v
```

Expected: All tests pass.

- [ ] **Step 11: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/dotnet/entity_framework.py cast-clone-backend/tests/unit/test_dotnet_entity_framework_plugin.py
git commit -m "feat(dotnet): enhance EF plugin with convention PK, NotMapped, Required/MaxLength, InverseProperty"
```

---

## Task 7: Entity Framework Plugin Enhancements (Part 2 — Advanced)

`IEntityTypeConfiguration<T>`, many-to-many, composite keys, migration parsing.

**Files:**
- Modify: `app/stages/plugins/dotnet/entity_framework.py`
- Test: `tests/unit/test_dotnet_entity_framework_plugin.py`

- [ ] **Step 1: Write failing test for `IEntityTypeConfiguration<T>`**

```python
class TestEntityTypeConfiguration:
    @pytest.mark.asyncio
    async def test_ientitytypeconfiguration_fluent_api_applied(self):
        """IEntityTypeConfiguration<T> classes have their fluent_configurations applied."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True, annotations=["Key"])

        # Config class implementing IEntityTypeConfiguration<User>
        config_node = add_class(ctx.graph, "MyApp.Config.UserConfiguration", "UserConfiguration",
                                implements=["IEntityTypeConfiguration<User>"])
        config_node.properties["fluent_configurations"] = [
            {"entity": "User", "table": "app_users"},
        ]

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert any(n.name == "app_users" for n in table_nodes)
        assert result.layer_assignments.get("MyApp.Config.UserConfiguration") == "Data Access"
```

- [ ] **Step 2: Implement `IEntityTypeConfiguration<T>` support**

In `extract()`, after Step 2b (apply fluent from DbContext), add:

```python
# Step 2c: Apply IEntityTypeConfiguration<T> classes
for node in graph.nodes.values():
    if node.kind != NodeKind.CLASS:
        continue
    implements = node.properties.get("implements", [])
    for impl in implements:
        if impl.startswith("IEntityTypeConfiguration<") and impl.endswith(">"):
            entity_name = impl[len("IEntityTypeConfiguration<"):-1]
            fluent_configs = node.properties.get("fluent_configurations", [])
            if fluent_configs:
                self._apply_fluent_configurations(
                    db_contexts, entities, name_to_fqn, edges, warnings, graph,
                    extra_configs=fluent_configs,
                )
            layer_assignments[node.fqn] = "Data Access"
```

Modify `_apply_fluent_configurations` to accept an optional `extra_configs` parameter (list of config dicts to process in addition to those on DbContext nodes).

- [ ] **Step 3: Run test**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_entity_framework_plugin.py::TestEntityTypeConfiguration -v
```

Expected: PASS

- [ ] **Step 4: Write failing test for many-to-many**

```python
class TestManyToMany:
    @pytest.mark.asyncio
    async def test_many_to_many_with_using_entity(self):
        """HasMany().WithMany().UsingEntity() creates a join table with FK references."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Students", "DbSet<Student>", is_property=True, type_args=["Student"])
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Courses", "DbSet<Course>", is_property=True, type_args=["Course"])

        add_class(ctx.graph, "MyApp.Models.Student", "Student")
        add_field(ctx.graph, "MyApp.Models.Student", "Id", "int", is_property=True, annotations=["Key"])

        add_class(ctx.graph, "MyApp.Models.Course", "Course")
        add_field(ctx.graph, "MyApp.Models.Course", "Id", "int", is_property=True, annotations=["Key"])

        ctx.graph.get_node("MyApp.Data.AppDbContext").properties["fluent_configurations"] = [
            {"entity": "Student", "has_many": "Courses", "with_many": "Students", "using_entity": "StudentCourses"},
        ]

        result = await plugin.extract(ctx)

        table_names = {n.name for n in result.nodes if n.kind == NodeKind.TABLE}
        assert "StudentCourses" in table_names

        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES and "StudentCourses" in e.source_fqn]
        assert len(ref_edges) == 2
```

- [ ] **Step 5: Implement many-to-many**

Add a `new_nodes: list[GraphNode]` parameter to `_apply_fluent_configurations` so it can create join table nodes. Update the call site in `extract()` to pass `nodes` list. Then detect `has_many` + `with_many` entries:

```python
if "has_many" in config and "with_many" in config:
    target_entity_name = config["has_many"]
    join_table_name = config.get("using_entity", f"{entity_name}{target_entity_name}")
    target_entity = entities.get(target_entity_name)
    if entity_info and target_entity:
        join_fqn = f"table:{join_table_name}"
        new_nodes.append(GraphNode(
            fqn=join_fqn,
            name=join_table_name,
            kind=NodeKind.TABLE,
            properties={"orm": "entity-framework", "is_join_table": True},
        ))
        # FK from join table to source entity PK
        source_pk = self._find_pk_column(entity_info)
        target_pk = self._find_pk_column(target_entity)
        if source_pk:
            fk1_fqn = f"{join_fqn}.{entity_name}Id"
            edges.append(GraphEdge(
                source_fqn=fk1_fqn,
                target_fqn=f"table:{entity_info.table_name}.{source_pk}",
                kind=EdgeKind.REFERENCES,
                confidence=Confidence.HIGH,
                evidence="entity-framework:fluent-api",
            ))
        if target_pk:
            fk2_fqn = f"{join_fqn}.{target_entity_name}Id"
            edges.append(GraphEdge(
                source_fqn=fk2_fqn,
                target_fqn=f"table:{target_entity.table_name}.{target_pk}",
                kind=EdgeKind.REFERENCES,
                confidence=Confidence.HIGH,
                evidence="entity-framework:fluent-api",
            ))
```

- [ ] **Step 6: Write failing test for composite keys**

```python
class TestCompositeKeys:
    @pytest.mark.asyncio
    async def test_composite_key_marks_multiple_columns_as_pk(self):
        """HasKey(x => new { x.A, x.B }) marks both columns as PK."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Enrollments", "DbSet<Enrollment>", is_property=True, type_args=["Enrollment"])
        add_class(ctx.graph, "MyApp.Models.Enrollment", "Enrollment")
        add_field(ctx.graph, "MyApp.Models.Enrollment", "StudentId", "int", is_property=True)
        add_field(ctx.graph, "MyApp.Models.Enrollment", "CourseId", "int", is_property=True)

        ctx.graph.get_node("MyApp.Data.AppDbContext").properties["fluent_configurations"] = [
            {"entity": "Enrollment", "composite_key": ["StudentId", "CourseId"]},
        ]

        result = await plugin.extract(ctx)
        col_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        pk_cols = [n for n in col_nodes if n.properties.get("is_primary_key")]
        pk_names = {n.name for n in pk_cols}
        assert pk_names == {"StudentId", "CourseId"}
```

- [ ] **Step 7: Implement composite keys**

In `_apply_fluent_configurations`, detect `composite_key` entries:

```python
if "composite_key" in config:
    composite_fields = config["composite_key"]
    for field_info in entity_info.fields:
        if field_info.name in composite_fields:
            field_info.is_key = True
```

- [ ] **Step 8: Write failing test for migration parsing**

```python
class TestMigrationParsing:
    @pytest.mark.asyncio
    async def test_migration_fk_creates_reference_edge(self):
        """AddForeignKey in migration creates a REFERENCES edge."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Orders", "DbSet<Order>", is_property=True, type_args=["Order"])
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.Order", "Order")
        add_field(ctx.graph, "MyApp.Models.Order", "Id", "int", is_property=True, annotations=["Key"])
        add_field(ctx.graph, "MyApp.Models.Order", "UserId", "int", is_property=True)
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True, annotations=["Key"])

        # Migration class with FK operation
        migration_node = add_class(ctx.graph, "MyApp.Migrations.Init", "Init")
        migration_node.properties["migration_operations"] = [
            {"operation": "AddForeignKey", "table": "Orders", "column": "UserId",
             "principal_table": "Users", "principal_column": "Id"},
        ]

        result = await plugin.extract(ctx)
        migration_refs = [e for e in result.edges
                          if e.kind == EdgeKind.REFERENCES and e.evidence == "entity-framework:migration"]
        assert len(migration_refs) >= 1
        assert any("UserId" in e.source_fqn and "Id" in e.target_fqn for e in migration_refs)
```

- [ ] **Step 9: Implement migration file parsing**

Add a new method `_parse_migrations` and call it from `extract()` after Step 3:

```python
    def _parse_migrations(
        self,
        graph: object,
        entities: dict[str, _EntityInfo],
        edges: list[GraphEdge],
        warnings: list[str],
    ) -> None:
        """Parse migration classes for ground-truth schema operations."""
        for node in graph.nodes.values():
            migration_ops = node.properties.get("migration_operations")
            if not migration_ops:
                continue

            for op in migration_ops:
                if op.get("operation") == "AddForeignKey":
                    table = op.get("table", "")
                    column = op.get("column", "")
                    principal_table = op.get("principal_table", "")
                    principal_column = op.get("principal_column", "")
                    if table and column and principal_table and principal_column:
                        fk_fqn = f"table:{table}.{column}"
                        pk_fqn = f"table:{principal_table}.{principal_column}"
                        edges.append(GraphEdge(
                            source_fqn=fk_fqn,
                            target_fqn=pk_fqn,
                            kind=EdgeKind.REFERENCES,
                            confidence=Confidence.HIGH,
                            evidence="entity-framework:migration",
                        ))
```

- [ ] **Step 10: Run all EF tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_entity_framework_plugin.py -v
```

Expected: All tests pass.

- [ ] **Step 11: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/dotnet/entity_framework.py cast-clone-backend/tests/unit/test_dotnet_entity_framework_plugin.py
git commit -m "feat(dotnet): enhance EF plugin with IEntityTypeConfiguration, many-to-many, composite keys, migration parsing"
```

---

## Task 8: SignalR Plugin (NEW)

Build the SignalR plugin from scratch with detection, hub discovery, method extraction, client events, and WebSocket endpoint mapping.

**Files:**
- Create: `app/stages/plugins/dotnet/signalr.py`
- Create: `tests/unit/test_dotnet_signalr_plugin.py`
- Modify: `app/stages/plugins/dotnet/__init__.py`
- Modify: `app/stages/plugins/__init__.py`

- [ ] **Step 1: Write failing detection test**

Create `tests/unit/test_dotnet_signalr_plugin.py`:

```python
"""Tests for the SignalR plugin — Hub discovery, method extraction, client events."""

import pytest
from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, SymbolGraph
from app.models.context import AnalysisContext
from app.stages.plugins.dotnet.signalr import SignalRPlugin
from tests.unit.helpers import make_dotnet_context, add_class, add_method, add_hub_class


class TestDetection:
    def test_detects_signalr_via_hub_base_class(self):
        """Detects SignalR when a class inherits from Hub."""
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.ChatHub", "ChatHub", base_class="Hub")
        result = plugin.detect(ctx)
        assert result.is_active

    def test_detects_signalr_via_typed_hub(self):
        """Detects SignalR when a class inherits from Hub<T>."""
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.NotificationHub", "NotificationHub", base_class="Hub<INotificationClient>")
        result = plugin.detect(ctx)
        assert result.is_active

    def test_no_detection_without_hubs(self):
        """No detection when no Hub subclasses exist."""
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        ctx.manifest.detected_frameworks = []  # Remove default aspnet framework
        result = plugin.detect(ctx)
        assert not result.is_active
```

- [ ] **Step 2: Write the minimal plugin skeleton**

Create `app/stages/plugins/dotnet/signalr.py`:

```python
"""SignalR Hub plugin — WebSocket endpoint discovery.

Finds Hub/Hub<T> subclasses, extracts hub methods, client events,
and MapHub<T> endpoint registrations.

Produces:
- Nodes: (:API_ENDPOINT {method: "WS", path, framework: "signalr", protocol: "websocket"})
- Edges: (:Class)-[:EXPOSES]->(:API_ENDPOINT)
         (:Function)-[:HANDLES]->(:API_ENDPOINT)
         (:Class)-[:PRODUCES {event}]->(:API_ENDPOINT)
- Entry points: hub methods as kind="websocket_endpoint"
- Layer: Hub classes -> Presentation
"""

from __future__ import annotations

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

_HUB_LIFECYCLE_METHODS = frozenset({"OnConnectedAsync", "OnDisconnectedAsync"})


class SignalRPlugin(FrameworkPlugin):
    name = "aspnet-signalr"
    version = "1.0.0"
    supported_languages = {"csharp"}
    depends_on: list[str] = ["aspnet-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "signalr" in fw.name.lower():
                    return PluginDetectionResult(confidence=Confidence.HIGH, reason=f"Framework '{fw.name}' detected")

        for node in context.graph.nodes.values():
            base = node.properties.get("base_class", "")
            if base == "Hub" or base.startswith("Hub<"):
                return PluginDetectionResult(confidence=Confidence.MEDIUM, reason="Hub subclass found")

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        return PluginResult.empty()

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[LayerRule(pattern="Hub", layer="Presentation")])
```

- [ ] **Step 3: Run detection tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_signalr_plugin.py::TestDetection -v
```

Expected: PASS

- [ ] **Step 4: Write failing extraction tests**

Append to `tests/unit/test_dotnet_signalr_plugin.py`:

```python
class TestHubExtraction:
    @pytest.mark.asyncio
    async def test_hub_creates_ws_endpoint(self):
        """Hub class with MapHub creates a WS API_ENDPOINT node."""
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()

        add_hub_class(ctx.graph, "MyApp.ChatHub", "ChatHub", methods=["SendMessage", "JoinGroup"])

        # MapHub registration
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]},
        ))

        result = await plugin.extract(ctx)

        endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoints) == 1
        assert endpoints[0].properties["method"] == "WS"
        assert endpoints[0].properties["path"] == "/chatHub"
        assert endpoints[0].properties["protocol"] == "websocket"

    @pytest.mark.asyncio
    async def test_hub_methods_create_handles_edges(self):
        """Hub methods (excluding lifecycle) create HANDLES edges to the endpoint."""
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()

        add_hub_class(ctx.graph, "MyApp.ChatHub", "ChatHub", methods=["SendMessage", "JoinGroup"])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]},
        ))

        result = await plugin.extract(ctx)

        handles = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        handler_fqns = {e.source_fqn for e in handles}
        assert "MyApp.ChatHub.SendMessage" in handler_fqns
        assert "MyApp.ChatHub.JoinGroup" in handler_fqns

    @pytest.mark.asyncio
    async def test_hub_creates_exposes_edge(self):
        """Hub class creates an EXPOSES edge to the endpoint."""
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()

        add_hub_class(ctx.graph, "MyApp.ChatHub", "ChatHub", methods=["SendMessage"])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]},
        ))

        result = await plugin.extract(ctx)

        exposes = [e for e in result.edges if e.kind == EdgeKind.EXPOSES]
        assert len(exposes) == 1
        assert exposes[0].source_fqn == "MyApp.ChatHub"

    @pytest.mark.asyncio
    async def test_hub_methods_create_entry_points(self):
        """Hub methods are registered as websocket_endpoint entry points."""
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()

        add_hub_class(ctx.graph, "MyApp.ChatHub", "ChatHub", methods=["SendMessage"])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]},
        ))

        result = await plugin.extract(ctx)
        assert len(result.entry_points) >= 1
        assert all(ep.kind == "websocket_endpoint" for ep in result.entry_points)

    @pytest.mark.asyncio
    async def test_client_events_create_produces_edges(self):
        """Hub methods with client_events create PRODUCES edges."""
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()

        add_hub_class(ctx.graph, "MyApp.ChatHub", "ChatHub",
                      methods=["SendMessage"], client_events=["ReceiveMessage"])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]},
        ))

        result = await plugin.extract(ctx)

        produces = [e for e in result.edges if e.kind == EdgeKind.PRODUCES]
        assert len(produces) >= 1
        assert produces[0].properties.get("event") == "ReceiveMessage"

    @pytest.mark.asyncio
    async def test_strongly_typed_hub_resolves_client_interface(self):
        """Hub<INotificationClient> resolves client interface methods as events."""
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()

        # Strongly-typed hub
        add_class(ctx.graph, "MyApp.NotificationHub", "NotificationHub", base_class="Hub<INotificationClient>")
        add_method(ctx.graph, "MyApp.NotificationHub", "SendNotification", return_type="Task")

        # Client interface with methods that become client events
        add_class(ctx.graph, "MyApp.INotificationClient", "INotificationClient", is_interface=True)
        add_method(ctx.graph, "MyApp.INotificationClient", "ReceiveNotification", return_type="Task")
        add_method(ctx.graph, "MyApp.INotificationClient", "UserJoined", return_type="Task")

        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"hub_mappings": [{"hub_type": "NotificationHub", "path": "/notifications"}]},
        ))

        result = await plugin.extract(ctx)

        produces = [e for e in result.edges if e.kind == EdgeKind.PRODUCES]
        event_names = {e.properties.get("event") for e in produces}
        assert "ReceiveNotification" in event_names
        assert "UserJoined" in event_names

    @pytest.mark.asyncio
    async def test_hub_classified_as_presentation(self):
        """Hub classes are assigned to the Presentation layer."""
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()

        add_hub_class(ctx.graph, "MyApp.ChatHub", "ChatHub", methods=["SendMessage"])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]},
        ))

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.ChatHub") == "Presentation"
```

- [ ] **Step 5: Implement full `extract()` method**

Replace the stub `extract()` in `signalr.py` with the full implementation — hub discovery, method extraction, client events, endpoint mapping, entry points, layer assignments. Follow the patterns established in the Web plugin.

- [ ] **Step 6: Run all SignalR tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_signalr_plugin.py -v
```

Expected: All tests pass.

- [ ] **Step 7: Register the plugin**

Update `app/stages/plugins/dotnet/__init__.py` to add:

```python
from app.stages.plugins.dotnet.signalr import SignalRPlugin
```

Update `app/stages/plugins/__init__.py` to add:

```python
from app.stages.plugins.dotnet.signalr import SignalRPlugin
global_registry.register(SignalRPlugin)
```

- [ ] **Step 8: Run full test suite**

```bash
cd cast-clone-backend
uv run pytest tests/unit/ -v
```

Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/dotnet/signalr.py cast-clone-backend/tests/unit/test_dotnet_signalr_plugin.py cast-clone-backend/app/stages/plugins/dotnet/__init__.py cast-clone-backend/app/stages/plugins/__init__.py
git commit -m "feat(dotnet): add SignalR Hub plugin with WebSocket endpoint discovery"
```

---

## Task 9: gRPC Plugin (NEW)

Build the gRPC plugin with detection, service class discovery, RPC method extraction, and endpoint mapping.

**Files:**
- Create: `app/stages/plugins/dotnet/grpc.py`
- Create: `tests/unit/test_dotnet_grpc_plugin.py`
- Modify: `app/stages/plugins/dotnet/__init__.py`
- Modify: `app/stages/plugins/__init__.py`

- [ ] **Step 1: Write failing detection tests**

Create `tests/unit/test_dotnet_grpc_plugin.py`:

```python
"""Tests for the gRPC plugin — service class discovery, RPC methods, endpoint mapping."""

import pytest
import re
from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, SymbolGraph
from app.models.context import AnalysisContext
from app.stages.plugins.dotnet.grpc import GRPCPlugin
from tests.unit.helpers import make_dotnet_context, add_class, add_method, add_grpc_service


class TestDetection:
    def test_detects_grpc_via_base_class_pattern(self):
        """Detects gRPC when a class inherits from Greeter.GreeterBase."""
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.GreeterService", "GreeterService", base_class="Greeter.GreeterBase")
        result = plugin.detect(ctx)
        assert result.is_active

    def test_no_false_positive_on_generic_base(self):
        """AutoMapper.ProfileBase should NOT trigger gRPC detection."""
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()
        ctx.manifest.detected_frameworks = []
        add_class(ctx.graph, "MyApp.MyProfile", "MyProfile", base_class="AutoMapper.ProfileBase")
        result = plugin.detect(ctx)
        assert not result.is_active

    def test_no_detection_without_grpc_classes(self):
        """No detection when no gRPC service classes exist."""
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()
        ctx.manifest.detected_frameworks = []
        result = plugin.detect(ctx)
        assert not result.is_active
```

- [ ] **Step 2: Write the minimal plugin skeleton**

Create `app/stages/plugins/dotnet/grpc.py`:

```python
"""gRPC Service plugin — gRPC endpoint discovery.

Finds gRPC service implementations (classes extending *.{Name}Base),
extracts RPC methods, and MapGrpcService<T> endpoint registrations.

Produces:
- Nodes: (:API_ENDPOINT {method: "GRPC", path, framework: "grpc"})
- Edges: (:Class)-[:EXPOSES]->(:API_ENDPOINT)
         (:Function)-[:HANDLES]->(:API_ENDPOINT)
- Entry points: RPC methods as kind="grpc_endpoint"
- Layer: gRPC service classes -> Presentation
"""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

_GRPC_BASE_RE = re.compile(r"^(\w+)\.\1Base$")


class GRPCPlugin(FrameworkPlugin):
    name = "aspnet-grpc"
    version = "1.0.0"
    supported_languages = {"csharp"}
    depends_on: list[str] = ["aspnet-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "grpc" in fw.name.lower():
                    return PluginDetectionResult(confidence=Confidence.HIGH, reason=f"Framework '{fw.name}' detected")

        for node in context.graph.nodes.values():
            base = node.properties.get("base_class", "")
            if _GRPC_BASE_RE.match(base):
                return PluginDetectionResult(confidence=Confidence.MEDIUM, reason=f"gRPC base class '{base}' found")

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        return PluginResult.empty()

    def get_layer_classification(self) -> LayerRules:
        # Note: gRPC services are Presentation layer, but the pattern "Service" is too broad.
        # Layer assignments are handled directly in extract() via layer_assignments dict.
        return LayerRules.empty()
```

- [ ] **Step 3: Run detection tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_grpc_plugin.py::TestDetection -v
```

Expected: PASS

- [ ] **Step 4: Write failing extraction tests**

Append to `tests/unit/test_dotnet_grpc_plugin.py`:

```python
class TestGRPCExtraction:
    @pytest.mark.asyncio
    async def test_grpc_service_creates_endpoint_per_method(self):
        """gRPC service with 2 override methods creates 2 GRPC API_ENDPOINT nodes."""
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()

        add_grpc_service(ctx.graph, "MyApp.GreeterService", "GreeterService",
                         base_class="Greeter.GreeterBase",
                         override_methods=[
                             {"name": "SayHello", "request_type": "HelloRequest", "response_type": "Task<HelloReply>"},
                             {"name": "SayGoodbye", "request_type": "GoodbyeRequest", "response_type": "Task<GoodbyeReply>"},
                         ])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"grpc_mappings": [{"service_type": "GreeterService"}]},
        ))

        result = await plugin.extract(ctx)

        endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoints) == 2
        assert all(ep.properties["method"] == "GRPC" for ep in endpoints)
        paths = {ep.properties["path"] for ep in endpoints}
        assert "/Greeter/SayHello" in paths
        assert "/Greeter/SayGoodbye" in paths

    @pytest.mark.asyncio
    async def test_grpc_creates_handles_and_exposes_edges(self):
        """Each RPC method gets HANDLES edge; service class gets EXPOSES edge."""
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()

        add_grpc_service(ctx.graph, "MyApp.GreeterService", "GreeterService",
                         base_class="Greeter.GreeterBase",
                         override_methods=[
                             {"name": "SayHello", "request_type": "HelloRequest", "response_type": "Task<HelloReply>"},
                         ])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"grpc_mappings": [{"service_type": "GreeterService"}]},
        ))

        result = await plugin.extract(ctx)

        handles = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        assert len(handles) == 1
        assert handles[0].source_fqn == "MyApp.GreeterService.SayHello"

        exposes = [e for e in result.edges if e.kind == EdgeKind.EXPOSES]
        assert len(exposes) >= 1
        assert exposes[0].source_fqn == "MyApp.GreeterService"

    @pytest.mark.asyncio
    async def test_grpc_creates_entry_points(self):
        """RPC methods are registered as grpc_endpoint entry points."""
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()

        add_grpc_service(ctx.graph, "MyApp.GreeterService", "GreeterService",
                         base_class="Greeter.GreeterBase",
                         override_methods=[
                             {"name": "SayHello", "request_type": "HelloRequest", "response_type": "Task<HelloReply>"},
                         ])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"grpc_mappings": [{"service_type": "GreeterService"}]},
        ))

        result = await plugin.extract(ctx)
        assert len(result.entry_points) >= 1
        assert all(ep.kind == "grpc_endpoint" for ep in result.entry_points)

    @pytest.mark.asyncio
    async def test_grpc_service_classified_as_presentation(self):
        """gRPC service classes are assigned to the Presentation layer."""
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()

        add_grpc_service(ctx.graph, "MyApp.GreeterService", "GreeterService",
                         base_class="Greeter.GreeterBase",
                         override_methods=[
                             {"name": "SayHello", "request_type": "HelloRequest", "response_type": "Task<HelloReply>"},
                         ])
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"grpc_mappings": [{"service_type": "GreeterService"}]},
        ))

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.GreeterService") == "Presentation"
```

- [ ] **Step 5: Implement full `extract()` method**

In `grpc.py`, implement the extraction:

1. Find service classes: scan for classes whose `base_class` matches `_GRPC_BASE_RE`
2. Extract service name from the match group
3. Find gRPC mappings on Program class
4. For each service class, find override methods (CONTAINS edges → FUNCTION nodes with `is_override: true`)
5. Create API_ENDPOINT, HANDLES, EXPOSES, entry points, layer assignments
6. **Proto file linking (deferred):** The spec describes optional `.proto` → service class DEPENDS_ON edges. This is deferred from this plan because the tree-sitter extractor does not yet parse `.proto` files or produce `CONFIG_FILE` nodes for them. When proto parsing is added, create DEPENDS_ON edges from service class FQN to the proto CONFIG_FILE FQN.

- [ ] **Step 6: Run all gRPC tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_dotnet_grpc_plugin.py -v
```

Expected: All tests pass.

- [ ] **Step 7: Register the plugin**

Update `app/stages/plugins/dotnet/__init__.py` to add:

```python
from app.stages.plugins.dotnet.grpc import GRPCPlugin
```

Update `app/stages/plugins/__init__.py` to add:

```python
from app.stages.plugins.dotnet.grpc import GRPCPlugin
global_registry.register(GRPCPlugin)
```

- [ ] **Step 8: Run full test suite**

```bash
cd cast-clone-backend
uv run pytest tests/unit/ -v
```

Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/dotnet/grpc.py cast-clone-backend/tests/unit/test_dotnet_grpc_plugin.py cast-clone-backend/app/stages/plugins/dotnet/__init__.py cast-clone-backend/app/stages/plugins/__init__.py
git commit -m "feat(dotnet): add gRPC service plugin with RPC endpoint discovery"
```

---

## Final Verification

After all 9 tasks are complete:

- [ ] **Run the full test suite**

```bash
cd cast-clone-backend
uv run pytest tests/unit/ -v --tb=short
```

Expected: All tests pass, no import errors, no regressions.

- [ ] **Verify no old imports remain**

```bash
cd cast-clone-backend
grep -r "from app.stages.plugins.aspnet" app/ tests/ || echo "No old aspnet imports found"
grep -r "from app.stages.plugins.entity_framework" app/ tests/ || echo "No old entity_framework imports found"
```

Expected: No matches.

- [ ] **Final commit (if any cleanup needed)**

```bash
git status
```
