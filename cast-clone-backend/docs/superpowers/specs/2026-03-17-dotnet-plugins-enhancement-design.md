# .NET Plugin Suite Enhancement & Expansion — Design Spec

**Date:** 2026-03-17
**Scope:** Enhance 4 existing .NET plugins, add 2 new plugins (SignalR, gRPC), consolidate folder structure under `dotnet/`.
**Research:** `cast-clone-backend/docs/13-DOT-NET-PLUGINS-RESEARCH`

---

## 1. Overview

The .NET plugin suite currently has 4 plugins split across `aspnet/` and `entity_framework/` folders. This work:

1. **Consolidates** all .NET plugins under a single `dotnet/` folder (matching the `spring/` pattern for Java)
2. **Enhances** the 4 existing plugins to close gaps identified in the research doc
3. **Adds** 2 new plugins: SignalR and gRPC

### Plugin Summary

| Plugin | Status | Key Enhancements |
|--------|--------|-----------------|
| `aspnet-di` | Enhance | Keyed services, open generics, shared DI map, AddDbContext wiring |
| `aspnet-web` | Enhance | `[FromBody]` DTO linking, HttpOptions/Head, extension method endpoints, `[Route]` override |
| `aspnet-middleware` | Enhance | Custom middleware class resolution, terminal middleware, technology nodes, layer classification |
| `entity-framework` | Enhance | Convention PK, `[NotMapped]`, `[Required]`/`[MaxLength]`, `[InverseProperty]`, `IEntityTypeConfiguration<T>`, many-to-many, composite keys, migration parsing |
| `aspnet-signalr` | NEW | Hub discovery, method extraction, client events, WS endpoint mapping |
| `aspnet-grpc` | NEW | Service class discovery, RPC method extraction, GRPC endpoint mapping |

---

## 2. Folder Structure

### Before

```
app/stages/plugins/
├── aspnet/
│   ├── __init__.py
│   ├── di.py
│   ├── web.py
│   └── middleware.py
├── entity_framework/
│   ├── __init__.py
│   └── dbcontext.py
```

### After

```
app/stages/plugins/
├── dotnet/
│   ├── __init__.py          # Exports all 6 plugin classes
│   ├── di.py                # ASPNetDIPlugin (from aspnet/di.py)
│   ├── web.py               # ASPNetWebPlugin (from aspnet/web.py)
│   ├── middleware.py         # ASPNetMiddlewarePlugin (from aspnet/middleware.py)
│   ├── entity_framework.py  # EntityFrameworkPlugin (from entity_framework/dbcontext.py)
│   ├── signalr.py           # SignalRPlugin (NEW)
│   └── grpc.py              # GRPCPlugin (NEW)
```

Old `aspnet/` and `entity_framework/` folders are deleted. All imports in `plugins/__init__.py`, test files, and the global registry are updated.

### Test Files

```
tests/unit/
├── test_dotnet_di_plugin.py              # renamed from test_aspnet_di_plugin.py
├── test_dotnet_web_plugin.py             # renamed from test_aspnet_web_plugin.py
├── test_dotnet_middleware_plugin.py       # renamed from test_aspnet_middleware_plugin.py
├── test_dotnet_entity_framework_plugin.py # renamed from test_entity_framework_plugin.py
├── test_dotnet_signalr_plugin.py         # NEW
└── test_dotnet_grpc_plugin.py            # NEW
```

---

## 3. DI Plugin Enhancements (`di.py`)

### 3.1 AddDbContext<T> Wiring

When `AddDbContext` appears in `di_registrations`, create an INJECTS edge from the DbContext class to any class whose constructor takes it as a parameter. Currently `AddDbContext` is recognized for lifetime mapping but not fully wired as an injection source.

**Implementation:** In `_collect_registrations`, when `method == "AddDbContext"`, treat the interface name as both interface and implementation (self-registration pattern).

### 3.2 Keyed Services

Support `.AddKeyedScoped<I, T>("key")` registrations. The `di_registrations` property will include a `key` field when present.

**Implementation:**
- In `_DIRegistration`, add `key: str | None = None` field
- In `_collect_registrations`, read `reg_dict.get("key")` and store it
- In INJECTS edge properties, include `key` when present
- In `_resolve_constructor_injection`, keyed services match by key + type (not type alone)

### 3.3 Open Generic Registrations

Support `AddScoped(typeof(IRepo<>), typeof(Repo<>))`. The `di_registrations` property will include `is_open_generic: true`.

**Implementation:**
- In `_collect_registrations`, detect open generic registrations (interface/implementation names ending with `<>`)
- Store them separately in a `_open_generics` list
- In `_resolve_constructor_injection`, when a constructor parameter type is a closed generic (e.g., `IRepo<User>`), check if there's an open generic registration matching the base type (`IRepo<>`), and resolve to the corresponding closed implementation (`Repo<User>`)
- These edges get `Confidence.MEDIUM` (type substitution is inferred)

### 3.4 Shared DI Map

Store the resolved `interface_name → implementation_fqn` map on `context` so downstream plugins can consume it.

**Implementation:**
- Add a `dotnet_di_map: dict[str, str] = field(default_factory=dict)` field to `AnalysisContext` in `app/models/context.py`. This is a proper dataclass field, not a dynamic attribute.
- After Phase 2 (creating INJECTS edges), set `context.dotnet_di_map = di_lookup` where `di_lookup` is the dict already built in `_resolve_constructor_injection`.

### 3.5 Keyed Service Constructor Resolution

In ASP.NET Core, consumers of keyed services declare their dependency via `[FromKeyedServices("key")]` on constructor parameters. The DI plugin must check for this attribute when resolving constructor injection:

- When a constructor parameter has `FromKeyedServices` in its annotations, extract the key from `annotation_args`
- Match against keyed DI registrations by both type + key
- Non-keyed parameters continue to resolve via type-only matching as before

### 3.6 Not Doing (Deferred)

- Factory registrations (`sp => new ServiceImpl(...)`) — can't statically resolve lambda returns
- Third-party DI containers (Autofac, Scrutor) — each has its own DSL, out of scope for v1

---

## 4. Web Plugin Enhancements (`web.py`)

### 4.1 `[FromBody]`/`[FromQuery]`/`[FromRoute]` DTO Linking

When a controller method parameter has one of these attributes, create a `DEPENDS_ON` edge from the endpoint node to the DTO class node.

**Implementation:**
- After creating the `API_ENDPOINT` node, iterate the method's `parameters` list
- For each parameter with `FromBody`, `FromQuery`, or `FromRoute` in its annotations, resolve the parameter `type` to a class FQN via the name-to-FQN index
- Create `DEPENDS_ON` edge: `endpoint_fqn → dto_class_fqn` with `properties={"binding": "body|query|route"}`

### 4.2 HttpOptions/HttpHead + MapOptions/MapHead

Add to the existing dicts:

```python
_HTTP_METHODS["HttpOptions"] = "OPTIONS"
_HTTP_METHODS["HttpHead"] = "HEAD"
_MAP_METHODS["MapOptions"] = "OPTIONS"
_MAP_METHODS["MapHead"] = "HEAD"
```

### 4.3 Extension Method Endpoint Patterns (1-hop)

Detect extension methods that register endpoints. When `Program.cs` calls `app.MapUserEndpoints()`, trace into the extension method to find nested endpoint registrations.

**Implementation:**
- Tree-sitter extractor stores an `extension_endpoints` property on extension method class nodes, containing the same `minimal_api_endpoints` / `minimal_api_groups` structure
- In `_extract_minimal_apis`, also scan for nodes with `extension_endpoints` property
- Limit to 1 hop: only direct extension methods called from Program.cs, not chains of extension methods calling other extension methods

### 4.4 `[Route]` Override on Methods

When a method has both `[Route("custom/path")]` and an HTTP verb attribute, the `[Route]` path replaces the verb attribute's path argument.

**Implementation:**
- In the method scanning loop, check if `"Route"` is in `method_annotations`
- If the `[Route]` path is absolute (starts with `/` or `~/`), use it directly — ignoring both the class prefix and the verb attribute path
- If the `[Route]` path is relative, combine it with the class prefix (replacing only the verb attribute's path argument)
- This matches ASP.NET Core's actual routing behavior: absolute `[Route]` overrides everything, relative `[Route]` overrides just the method-level segment

---

## 5. Middleware Plugin Enhancements (`middleware.py`)

**Dependency fix:** Change `depends_on` from `[]` to `["aspnet-di"]` to match the dependency chain in section 9.4. This ensures the middleware plugin runs after DI resolution and can access the shared DI map for custom middleware class resolution.

### 5.1 Custom Middleware Class Resolution

When `middleware_calls` contains `UseMiddleware<T>`, resolve the generic type arg to the actual class node.

**Implementation:**
- Middleware calls that are `UseMiddleware<T>` are stored with the type name (e.g., `"UseMiddleware<RequestLoggingMiddleware>"`)
- Parse the type name from between `<` and `>`
- Find the class node in the graph, verify it has an `Invoke` or `InvokeAsync` method
- Create a `HANDLES` edge: `class_fqn → middleware_component_fqn`

### 5.2 Terminal Middleware Mapping

`MapControllers()`, `MapHub<T>()`, `MapGrpcService<T>()` appear as terminal entries in the middleware pipeline.

**Implementation:**
- Store these as middleware component nodes with `properties={"terminal": true}`
- For `MapHub<T>` and `MapGrpcService<T>`, also store `generic_type` in properties for cross-referencing with SignalR/gRPC plugins

### 5.3 Technology Node Creation

For each well-known `Use*` call, create a `COMPONENT` node tagged as a technology node.

**Mapping:**

| Middleware Call | Technology Name |
|---------------|----------------|
| `UseAuthentication` | Authentication |
| `UseAuthorization` | Authorization |
| `UseCors` | CORS |
| `UseRateLimiter` | Rate Limiting |
| `UseResponseCaching` | Response Caching |
| `UseHttpsRedirection` | HTTPS Redirection |
| `UseStaticFiles` | Static Files |
| `UseHsts` | HSTS |

**Implementation:**
- Maintain a `_TECHNOLOGY_MAP: dict[str, str]` mapping middleware call names to technology names
- For each matched call, create a `COMPONENT` node with `properties={"technology": true, "name": tech_name, "framework": "aspnet"}`
- FQN: `technology:aspnet:{tech_name_lower}`

### 5.4 Layer Classification

Add `get_layer_classification()` override:

```python
LayerRules(rules=[
    LayerRule(pattern="Middleware", layer="Cross-Cutting"),
])
```

Custom middleware classes (those resolved via `UseMiddleware<T>`) get classified as "Cross-Cutting" layer via `layer_assignments`.

---

## 6. Entity Framework Plugin Enhancements (`entity_framework.py`)

### 6.1 Convention-Based PK Detection

When no `[Key]` annotation exists, infer PK from property named `Id` or `{ClassName}Id`.

**Implementation:** Update `_find_pk_column` to add a fallback after checking `is_key`:

```python
# Fallback: convention-based PK
for field_info in entity.fields:
    if field_info.name == "Id" or field_info.name == f"{entity.name}Id":
        return field_info.name
```

### 6.2 `[NotMapped]` Annotation

Skip properties annotated with `[NotMapped]` from column generation.

**Implementation:** In the field processing loop (Step 3), add an early check:

```python
if "NotMapped" in field_info.annotations:
    continue
```

### 6.3 `[Required]`/`[MaxLength]` Annotations

Store as metadata on column nodes.

**Implementation:** When creating column nodes, add to properties:

```python
"is_nullable": "Required" not in field_info.annotations,
"max_length": field_info.annotation_args.get("MaxLength"),  # None if not present
```

### 6.4 `[InverseProperty("name")]` Annotation

Disambiguate when an entity has multiple navigation properties to the same target type.

**Implementation:** In `_infer_fk_from_navigation`, when the target entity has an `[InverseProperty]` annotation, use the specified property name to match the correct bidirectional relationship instead of falling back to the `{EntityName}Id` convention.

### 6.5 `IEntityTypeConfiguration<T>` Support

Find classes implementing `IEntityTypeConfiguration<T>` and parse their Fluent API configurations.

**Implementation:**
- Scan graph for classes where `implements` list contains a string matching `IEntityTypeConfiguration<*>`
- Extract the entity type name from the generic arg
- Read the `fluent_configurations` property on these configuration class nodes (populated by tree-sitter, same format as `OnModelCreating`)
- Feed them into the same `_apply_fluent_configurations` method, merging with any configurations from the DbContext itself
- Layer classification: these classes → "Data Access"

### 6.6 Many-to-Many Relationships

Handle `HasMany().WithMany().UsingEntity()` Fluent API pattern.

**Implementation:**
- In `_apply_fluent_configurations`, detect config entries with `has_many` + `with_many` keys
- If `using_entity` is present (explicit join table name), create a TABLE node for the join table
- Create REFERENCES edges from both FK columns in the join table to the respective PK columns
- For skip navigations (no explicit join entity): when two entities each have `ICollection<OtherEntity>` pointing at each other, infer a many-to-many with a conventional join table name `{EntityA}{EntityB}`

### 6.7 Composite Keys

Handle `HasKey(sc => new { sc.StudentId, sc.CourseId })`.

**Implementation:**
- In `_apply_fluent_configurations`, detect config entries with `composite_key` key containing a list of field names
- When creating column nodes for these fields, set `is_primary_key: true` on each

### 6.8 Migration File Parsing

Parse migration classes for ground-truth schema operations.

**Implementation:**
- Scan graph for class nodes in namespaces containing `Migrations` with a `migration_operations` property (populated by tree-sitter)
- `migration_operations` contains structured data: `[{"operation": "CreateTable", "table": "Users", "columns": [...], "foreign_keys": [...]}]`
- For each `CreateTable`, validate against model-based Table nodes — warn if discrepancies found
- For `AddForeignKey` operations, create REFERENCES edges with `confidence=Confidence.HIGH` and `evidence="entity-framework:migration"`
- Migration-sourced edges supplement (don't replace) model-based edges

---

## 7. SignalR Plugin (NEW) — `signalr.py`

**Class:** `SignalRPlugin`
**Name:** `"aspnet-signalr"`
**Version:** `"1.0.0"`
**Depends on:** `["aspnet-di"]`
**Supported languages:** `{"csharp"}`

### 7.1 Detection

- Check manifest for `signalr` in framework name → `Confidence.HIGH`
- Fallback: scan graph for classes with `base_class` of `Hub` or starting with `Hub<` → `Confidence.MEDIUM`

### 7.2 Extraction

**Hub discovery:**
- Find classes where `base_class == "Hub"` or `base_class.startswith("Hub<")`
- For `Hub<T>`, extract `T` from `type_args` or parse from `base_class` string

**Hub method extraction:**
- All public methods on hub classes (via CONTAINS edges → FUNCTION nodes)
- Exclude `OnConnectedAsync` and `OnDisconnectedAsync` (lifecycle methods)
- Each hub method becomes a handler for the hub's endpoint

**Client event extraction:**
- Hub method nodes may have `client_events` property: `["ReceiveMessage", "UserJoined"]`
- For strongly-typed hubs, find the client interface (`Hub<T>` → interface `T`) and extract its methods as client events
- Create PRODUCES edges from the hub class to its own WebSocket API_ENDPOINT node: `(:Class)-[:PRODUCES {event: "ReceiveMessage"}]->(:API_ENDPOINT)`. The `event` property on the edge identifies the specific client event. Client events are not separate nodes — they are metadata on the PRODUCES edge, since they flow over the same WebSocket connection represented by the hub's endpoint.

**Endpoint mapping:**
- Find `hub_mappings` property on Program class node: `[{"hub_type": "ChatHub", "path": "/chatHub"}]`
- Create `API_ENDPOINT` node: `fqn="endpoint:WS:/chatHub"`, `properties={"method": "WS", "path": "/chatHub", "framework": "signalr", "protocol": "websocket"}`
- Create EXPOSES edge: `hub_class_fqn → endpoint_fqn`
- Create HANDLES edges: each hub method → endpoint
- Create entry points: `kind="websocket_endpoint"`

### 7.3 Layer Classification

```python
LayerRules(rules=[
    LayerRule(pattern="Hub", layer="Presentation"),
])
```

---

## 8. gRPC Plugin (NEW) — `grpc.py`

**Class:** `GRPCPlugin`
**Name:** `"aspnet-grpc"`
**Version:** `"1.0.0"`
**Depends on:** `["aspnet-di"]`
**Supported languages:** `{"csharp"}`

### 8.1 Detection

- Check manifest for `grpc` in framework name → `Confidence.HIGH`
- Fallback: scan graph for classes whose `base_class` matches the pattern `{Name}.{Name}Base` where both names share a common root (e.g., `Greeter.GreeterBase` — the protobuf-generated naming convention). Regex: `^(\w+)\.\1Base$`. This avoids false positives on unrelated `*.Base` patterns like `AutoMapper.ProfileBase`. → `Confidence.MEDIUM`

### 8.2 Extraction

**Service class discovery:**
- Find classes where `base_class` matches `*.{Name}Base` pattern
- Extract service name from base class: `Greeter.GreeterBase` → `"Greeter"`
- Extract package/namespace from the base class for path construction

**RPC method extraction:**
- Find methods on service classes with `is_override: true` property
- Exclude framework lifecycle methods
- First parameter type = request message, return type = response message
- Store request/response types in endpoint properties

**Endpoint mapping:**
- Find `grpc_mappings` property on Program class node: `[{"service_type": "GreeterService"}]`
- Create `API_ENDPOINT` node: `fqn="endpoint:GRPC:/{service}/{method}"`, `properties={"method": "GRPC", "path": "/{service}/{method}", "framework": "grpc"}`
- Create EXPOSES edge: `service_class_fqn → endpoint_fqn`
- Create HANDLES edges: each RPC method → endpoint
- Create entry points: `kind="grpc_endpoint"`

**Proto file linking (optional):**
- If `.proto` `CONFIG_FILE` nodes exist in graph, create `DEPENDS_ON` edges from service implementation class to proto file
- Best-effort, not required for core functionality

### 8.3 Layer Classification

```python
LayerRules(rules=[
    LayerRule(pattern="Service", layer="Presentation"),  # gRPC services are presentation
])
```

Note: This is scoped narrowly — only applies to classes whose `base_class` matches the gRPC pattern, not all classes ending in "Service". The plugin's `extract()` method handles this directly via `layer_assignments` rather than relying solely on the pattern rule.

---

## 9. Shared Concerns

### 9.1 Test Helpers

Update existing helpers in `tests/unit/helpers.py`:

- **`add_method`** — Add `is_override: bool = False` kwarg. Stores `is_override` in node properties. Required by the gRPC plugin (section 8.2) to identify overridden RPC methods.

Add new helpers:

```python
def add_hub_class(graph, fqn, name, *, hub_type_arg=None, methods=None, client_events=None): ...
def add_grpc_service(graph, fqn, name, *, base_class, override_methods=None): ...
```

`add_grpc_service` internally uses `add_method` with `is_override=True` for each override method.

### 9.2 No New Enums

All node/edge kinds already exist: `API_ENDPOINT`, `COMPONENT`, `PRODUCES`, `DEPENDS_ON`, `HANDLES`, `EXPOSES`.

**New `EntryPoint.kind` values** introduced by this spec (free-form strings, no enum change needed):
- `"websocket_endpoint"` — SignalR hub methods (section 7.2)
- `"grpc_endpoint"` — gRPC service methods (section 8.2)

These join the existing `"http_endpoint"` kind used by the Web plugin.

### 9.3 Registry Update

`plugins/__init__.py` updates all imports to `dotnet/` and registers `SignalRPlugin` + `GRPCPlugin`.

### 9.4 Dependency Chain

```
aspnet-di (foundation)
  ├── aspnet-web
  ├── aspnet-middleware
  ├── entity-framework
  ├── aspnet-signalr
  └── aspnet-grpc
```

All 5 downstream plugins depend on `aspnet-di`. They are independent of each other and run concurrently in the same topological sort layer.

### 9.5 `dotnet/__init__.py` Role

The `dotnet/__init__.py` re-exports all 6 plugin classes for convenience. Plugin registration with `global_registry` stays in `plugins/__init__.py` (following the existing pattern).

---

## 10. Tree-sitter Extractor Prerequisites

Several plugin enhancements depend on the C# tree-sitter extractor (`app/stages/treesitter/extractors/csharp.py`) populating specific properties on graph nodes. These properties must exist before plugins run (Stage 5 depends on Stage 3 output).

| Property | On Node Type | Required By | Description |
|----------|-------------|-------------|-------------|
| `di_registrations` | Program/Startup class | DI plugin (existing) | List of `{method, interface, implementation, key?, is_open_generic?}` |
| `middleware_calls` | Program/Startup class | Middleware plugin (existing) | Ordered list of `Use*` call names |
| `minimal_api_endpoints` | Program class | Web plugin (existing) | List of `{method, path, handler_fqn}` |
| `minimal_api_groups` | Program class | Web plugin (existing) | List of `{prefix, endpoints: [...]}` |
| `extension_endpoints` | Extension method class | Web plugin (NEW - section 4.3) | Same format as `minimal_api_endpoints` |
| `fluent_configurations` | DbContext / IEntityTypeConfiguration class | EF plugin (existing on DbContext, NEW on config classes) | List of config dicts |
| `migration_operations` | Migration class | EF plugin (NEW - section 6.8) | List of `{operation, table, columns, foreign_keys}` |
| `hub_mappings` | Program class | SignalR plugin (NEW - section 7.2) | List of `{hub_type, path}` |
| `client_events` | Hub method nodes | SignalR plugin (NEW - section 7.2) | List of event name strings |
| `grpc_mappings` | Program class | gRPC plugin (NEW - section 8.2) | List of `{service_type}` |
| `is_override` | Method nodes | gRPC plugin (NEW - section 8.2) | Boolean |
| `FromKeyedServices` in annotations | Constructor params | DI plugin (NEW - section 3.5) | Attribute with key arg |

Properties marked "existing" are already produced by the extractor. Properties marked "NEW" require extractor enhancements that are included in the phasing estimates below.

---

## 11. Phasing

### Phase 1 (M6f): Core Enhancements + SignalR

| Task | Description | Est. |
|------|-------------|------|
| 1 | Folder consolidation: move files, update imports, rename tests, verify all tests pass | 0.5d |
| 2 | C# tree-sitter extractor enhancements: add `extension_endpoints`, `migration_operations`, `hub_mappings`, `client_events`, `grpc_mappings`, `is_override`, keyed service annotation support | 2d |
| 3 | `AnalysisContext` update: add `dotnet_di_map` field | 0.1d |
| 4 | DI plugin enhancements (keyed services, open generics, shared map, AddDbContext, FromKeyedServices) | 1.5d |
| 5 | Web plugin enhancements (DTO linking, verbs, extension endpoints, Route override) | 1.5d |
| 6 | Middleware plugin enhancements (depends_on fix, custom class resolution, terminal, tech nodes, layers) | 1d |
| 7 | EF plugin enhancements (all 8 items) | 3.5d |
| 8 | SignalR plugin (new) | 1.5d |
| **Total** | | **~11.6d** |

### Phase 2 (M6g): gRPC

| Task | Description | Est. |
|------|-------------|------|
| 9 | gRPC plugin (new) | 1.5d |
| **Total** | | **~1.5d** |

**Grand total: ~13 days**

Note: Task 2 (tree-sitter extractor) is a prerequisite for tasks 4-9. Tasks 4-8 can be worked in parallel once task 2 is complete. Task 1 (folder consolidation) is independent and can be done first.
