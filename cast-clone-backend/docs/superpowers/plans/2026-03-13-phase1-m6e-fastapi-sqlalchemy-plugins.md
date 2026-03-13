# M6d: FastAPI & SQLAlchemy Plugins Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement two independent Python framework plugins — FastAPI (route decorators, `Depends()` DI, Pydantic model linking) and SQLAlchemy (declarative model-to-table mapping, ForeignKey relationships, `relationship()` resolution). These are the Python equivalents of Spring Web and Hibernate/JPA respectively. Both are dependency-free and can be built in parallel.

**Architecture:** Each plugin extends `FrameworkPlugin` (from M6a). Plugins scan `context.graph` for Python classes/functions with specific decorators (stored in `node.properties["annotations"]` by the Python tree-sitter extractor M4d). FastAPI extracts route endpoints + DI wiring. SQLAlchemy extracts entity-to-table mappings + FK relationships. Both produce nodes/edges via `PluginResult`.

**Tech Stack:** Python 3.12, dataclasses, re (for decorator parsing), pytest+pytest-asyncio

**Dependencies:** M1 (AnalysisContext, SymbolGraph, GraphNode, GraphEdge, enums), M6a (FrameworkPlugin, PluginResult, PluginDetectionResult, LayerRules, LayerRule), M4d (Python tree-sitter extractor — provides the graph nodes these plugins read from)

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       └── plugins/
│           ├── fastapi_plugin/
│           │   ├── __init__.py              # CREATE — re-export plugin class
│           │   └── routes.py                # CREATE — FastAPIPlugin
│           └── sqlalchemy_plugin/
│               ├── __init__.py              # CREATE — re-export plugin class
│               └── models.py                # CREATE — SQLAlchemyPlugin
├── tests/
│   └── unit/
│       ├── test_fastapi_plugin.py           # CREATE
│       └── test_sqlalchemy_plugin.py        # CREATE
```

Note: Using `fastapi_plugin/` and `sqlalchemy_plugin/` directory names to avoid collision with the `fastapi` and `sqlalchemy` PyPI packages.

---

## Shared Test Helpers — Python Node Conventions

All test files build `AnalysisContext` objects pre-populated with Python nodes as the tree-sitter extractor (M4d) would produce them. The key conventions from the Python extractor:

**Node conventions from tree-sitter (M4d):**
- `Class` nodes: `properties["annotations"]` = `["app.get(\"/users\")"]` (full decorator text), `language="python"`, `INHERITS` edges for base classes
- `Function` nodes: `properties["annotations"]` = `["app.get(\"/users/{user_id}\")"]`, `properties["params"]` = `[{"name": "user_id", "type": "int"}, {"name": "db", "type": "Session"}]`, `properties["return_type"]` = `"User"`, `properties["is_method"]` = `True/False`
- `Field` nodes: Created for `self.x = ...` in `__init__` AND for class-level assignments like `__tablename__ = "users"`. `properties["type"]` when type annotation present.
- Containment: `(:Module)-[:CONTAINS]->(:Class)` and `(:Class)-[:CONTAINS]->(:Function)` and `(:Class)-[:CONTAINS]->(:Field)` edges exist
- Inheritance: `(:Class)-[:INHERITS]->(:Class)` edges exist (e.g., `User` → `Base`, `UserView` → `ModelViewSet`)
- Imports: `(:Module)-[:IMPORTS]->(:Module)` edges exist

**Decorator parsing note:** Python decorators are stored as full text strings including arguments. For example, `@app.get("/users/{user_id}", response_model=UserResponse)` is stored as the string `'app.get("/users/{user_id}", response_model=UserResponse)'`. The plugins parse these strings with regex to extract HTTP method, path, and keyword arguments.

---

## Task 1: FastAPI Plugin — Route Extraction & DI

**Files:**
- Create: `app/stages/plugins/fastapi_plugin/__init__.py`
- Create: `app/stages/plugins/fastapi_plugin/routes.py`
- Test: `tests/unit/test_fastapi_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_fastapi_plugin.py
"""Tests for the FastAPI plugin — route endpoints, Depends() DI, Pydantic model linking."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework, EntryPoint
from app.stages.plugins.base import PluginDetectionResult, PluginResult
from app.stages.plugins.fastapi_plugin.routes import FastAPIPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_fastapi() -> AnalysisContext:
    """Create an AnalysisContext with fastapi detected."""
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="fastapi",
                language="python",
                confidence=Confidence.HIGH,
                evidence=["pyproject.toml contains fastapi"],
            ),
        ],
    )
    return ctx


def _add_module(graph: SymbolGraph, fqn: str, name: str) -> GraphNode:
    """Add a module node."""
    node = GraphNode(fqn=fqn, name=name, kind=NodeKind.MODULE, language="python")
    graph.add_node(node)
    return node


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    annotations: list[str] | None = None,
    bases: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.CLASS,
        language="python",
        properties={
            "annotations": annotations or [],
        },
    )
    graph.add_node(node)
    # Add INHERITS edges for base classes
    for base in (bases or []):
        graph.add_edge(GraphEdge(
            source_fqn=fqn, target_fqn=base, kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW, evidence="tree-sitter",
        ))
    return node


def _add_function(
    graph: SymbolGraph,
    parent_fqn: str,
    func_name: str,
    annotations: list[str] | None = None,
    params: list[dict] | None = None,
    return_type: str | None = None,
    is_method: bool = False,
) -> GraphNode:
    fqn = f"{parent_fqn}.{func_name}"
    node = GraphNode(
        fqn=fqn,
        name=func_name,
        kind=NodeKind.FUNCTION,
        language="python",
        properties={
            "annotations": annotations or [],
            "params": params or [],
            "return_type": return_type,
            "is_method": is_method,
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=parent_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestFastAPIDetection:
    def test_detect_high_when_fastapi_in_frameworks(self):
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_fastapi(self):
        plugin = FastAPIPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp"),
            detected_frameworks=[],
        )
        result = plugin.detect(ctx)
        assert result.is_active is False

    def test_detect_medium_when_decorators_found(self):
        """If no fastapi in frameworks but route decorators exist in graph."""
        plugin = FastAPIPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp"),
            detected_frameworks=[],
        )
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "get_users",
            annotations=['app.get("/users")'],
        )
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM


# ---------------------------------------------------------------------------
# Route endpoint extraction tests
# ---------------------------------------------------------------------------

class TestFastAPIRouteExtraction:
    @pytest.mark.asyncio
    async def test_get_endpoint_simple(self):
        """@app.get("/users") -> APIEndpoint node + HANDLES edge."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "get_users",
            annotations=['app.get("/users")'],
            return_type="list[User]",
        )

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["method"] == "GET"
        assert endpoint_nodes[0].properties["path"] == "/users"

        handles_edges = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        assert len(handles_edges) == 1
        assert handles_edges[0].source_fqn == "myapp.main.get_users"

    @pytest.mark.asyncio
    async def test_post_endpoint(self):
        """@app.post("/users") -> POST endpoint."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "create_user",
            annotations=['app.post("/users")'],
        )

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["method"] == "POST"
        assert endpoint_nodes[0].properties["path"] == "/users"

    @pytest.mark.asyncio
    async def test_all_http_methods(self):
        """All HTTP method decorators produce correct method values."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        methods = ["get", "post", "put", "delete", "patch"]
        for m in methods:
            _add_function(
                ctx.graph, "myapp.main", f"handle_{m}",
                annotations=[f'app.{m}("/resource")'],
            )

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 5
        extracted_methods = {n.properties["method"] for n in endpoint_nodes}
        assert extracted_methods == {"GET", "POST", "PUT", "DELETE", "PATCH"}

    @pytest.mark.asyncio
    async def test_path_with_parameters(self):
        """@app.get("/users/{user_id}") -> path preserved with parameter."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "get_user",
            annotations=['app.get("/users/{user_id}")'],
            params=[{"name": "user_id", "type": "int"}],
        )

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["path"] == "/users/{user_id}"

    @pytest.mark.asyncio
    async def test_router_prefix_composition(self):
        """APIRouter prefix is combined with method-level path.

        When tree-sitter sees: router = APIRouter(prefix="/api/v1")
        and @router.get("/users"), the decorator text is 'router.get("/users")'.
        The plugin should detect router variables and resolve their prefix.
        For this test, we simulate by storing the prefix in a field node.
        """
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.routes", "routes")

        # Simulate router = APIRouter(prefix="/api/v1") as a module-level field
        router_node = GraphNode(
            fqn="myapp.routes.router",
            name="router",
            kind=NodeKind.FIELD,
            language="python",
            properties={
                "type": "APIRouter",
                "annotations": [],
                "value": 'APIRouter(prefix="/api/v1")',
            },
        )
        ctx.graph.add_node(router_node)
        ctx.graph.add_edge(GraphEdge(
            source_fqn="myapp.routes", target_fqn="myapp.routes.router",
            kind=EdgeKind.CONTAINS,
        ))

        _add_function(
            ctx.graph, "myapp.routes", "list_users",
            annotations=['router.get("/users")'],
        )

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["path"] == "/api/v1/users"

    @pytest.mark.asyncio
    async def test_endpoint_creates_entry_point(self):
        """Each endpoint should be registered as an entry point."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "get_users",
            annotations=['app.get("/users")'],
        )

        result = await plugin.extract(ctx)
        assert len(result.entry_points) == 1
        assert result.entry_points[0].kind == "http_endpoint"
        assert result.entry_points[0].metadata["method"] == "GET"
        assert result.entry_points[0].metadata["path"] == "/users"


# ---------------------------------------------------------------------------
# Depends() DI tests
# ---------------------------------------------------------------------------

class TestFastAPIDependsInjection:
    @pytest.mark.asyncio
    async def test_depends_creates_injects_edge(self):
        """Parameter with Depends(get_db) -> INJECTS edge."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")

        # The dependency provider function
        _add_function(ctx.graph, "myapp.main", "get_db", return_type="AsyncSession")

        # The consumer with Depends()
        _add_function(
            ctx.graph, "myapp.main", "list_users",
            annotations=['app.get("/users")'],
            params=[
                {"name": "db", "type": "AsyncSession", "default": "Depends(get_db)"},
            ],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].source_fqn == "myapp.main.get_db"
        assert inject_edges[0].target_fqn == "myapp.main.list_users"
        assert inject_edges[0].properties.get("framework") == "fastapi"

    @pytest.mark.asyncio
    async def test_depends_with_dotted_path(self):
        """Depends(deps.get_db) — dotted import reference."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_module(ctx.graph, "myapp.deps", "deps")
        _add_function(ctx.graph, "myapp.deps", "get_db", return_type="AsyncSession")

        _add_function(
            ctx.graph, "myapp.main", "list_users",
            annotations=['app.get("/users")'],
            params=[
                {"name": "db", "type": "AsyncSession", "default": "Depends(deps.get_db)"},
            ],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1

    @pytest.mark.asyncio
    async def test_multiple_depends_in_one_function(self):
        """Multiple Depends() params -> multiple INJECTS edges."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(ctx.graph, "myapp.main", "get_db")
        _add_function(ctx.graph, "myapp.main", "get_current_user")

        _add_function(
            ctx.graph, "myapp.main", "create_item",
            annotations=['app.post("/items")'],
            params=[
                {"name": "db", "type": "Session", "default": "Depends(get_db)"},
                {"name": "user", "type": "User", "default": "Depends(get_current_user)"},
            ],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 2
        sources = {e.source_fqn for e in inject_edges}
        assert "myapp.main.get_db" in sources
        assert "myapp.main.get_current_user" in sources

    @pytest.mark.asyncio
    async def test_no_depends_no_inject_edges(self):
        """Function without Depends() -> no INJECTS edges."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "health",
            annotations=['app.get("/health")'],
            params=[],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 0


# ---------------------------------------------------------------------------
# Layer classification tests
# ---------------------------------------------------------------------------

class TestFastAPILayerClassification:
    @pytest.mark.asyncio
    async def test_route_handler_is_presentation(self):
        """Functions with route decorators -> Presentation layer."""
        plugin = FastAPIPlugin()
        ctx = _make_context_with_fastapi()
        _add_module(ctx.graph, "myapp.main", "main")
        _add_function(
            ctx.graph, "myapp.main", "get_users",
            annotations=['app.get("/users")'],
        )

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("myapp.main.get_users") == "Presentation"


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestFastAPIPluginMetadata:
    def test_plugin_name(self):
        assert FastAPIPlugin().name == "fastapi"

    def test_supported_languages(self):
        assert FastAPIPlugin().supported_languages == {"python"}

    def test_depends_on_empty(self):
        assert FastAPIPlugin().depends_on == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_fastapi_plugin.py -v`
Expected: FAIL (ImportError — `app.stages.plugins.fastapi_plugin.routes` doesn't exist)

- [ ] **Step 3: Create `__init__.py`**

```python
# app/stages/plugins/fastapi_plugin/__init__.py
"""FastAPI framework plugin — route extraction, Depends() DI, Pydantic model linking."""

from app.stages.plugins.fastapi_plugin.routes import FastAPIPlugin

__all__ = ["FastAPIPlugin"]
```

- [ ] **Step 4: Implement `fastapi_plugin/routes.py`**

```python
# app/stages/plugins/fastapi_plugin/routes.py
"""FastAPI plugin.

Detects FastAPI route decorators (@app.get, @router.post, etc.),
resolves Depends() dependency injection wiring, and links Pydantic
request/response models to endpoints.

Produces:
- APIEndpoint nodes: (:APIEndpoint {method, path})
- HANDLES edges: (:Function)-[:HANDLES]->(:APIEndpoint)
- INJECTS edges: (:Function)-[:INJECTS {framework: "fastapi"}]->(:Function)
- Layer assignments: route handlers -> Presentation
"""

from __future__ import annotations

import re
import structlog

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext, EntryPoint
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Regex to match route decorators: app.get("/path") or router.post("/path")
# Captures: variable name, HTTP method, path string
_ROUTE_DECORATOR_RE = re.compile(
    r"^(\w+)\.(get|post|put|delete|patch|options|head)\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)

# Regex to extract Depends(func_name) from default values
_DEPENDS_RE = re.compile(r"Depends\(\s*([a-zA-Z_][\w.]*)\s*\)")

# Regex to extract APIRouter prefix
_ROUTER_PREFIX_RE = re.compile(r'APIRouter\([^)]*prefix\s*=\s*["\']([^"\']+)["\']')


class FastAPIPlugin(FrameworkPlugin):
    name = "fastapi"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        # Check manifest for fastapi framework detection
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "fastapi" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: check graph for FastAPI-style route decorators
        for node in context.graph.nodes.values():
            if node.language != "python":
                continue
            for deco in node.properties.get("annotations", []):
                if _ROUTE_DECORATOR_RE.match(deco):
                    return PluginDetectionResult(
                        confidence=Confidence.MEDIUM,
                        reason="FastAPI route decorators found in graph",
                    )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("fastapi_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        # Phase 1: Build router prefix map (router variable -> prefix string)
        router_prefixes = self._build_router_prefix_map(graph)

        # Phase 2: Extract route endpoints
        for func_node in graph.nodes.values():
            if func_node.kind != NodeKind.FUNCTION or func_node.language != "python":
                continue

            for deco in func_node.properties.get("annotations", []):
                match = _ROUTE_DECORATOR_RE.match(deco)
                if not match:
                    continue

                router_var, http_method, path = match.groups()
                http_method = http_method.upper()

                # Resolve router prefix
                prefix = router_prefixes.get(router_var, "")
                full_path = prefix + path if not path.startswith(prefix) else path

                # Create APIEndpoint node
                endpoint_fqn = f"{http_method}:{full_path}"
                endpoint_node = GraphNode(
                    fqn=endpoint_fqn,
                    name=f"{http_method} {full_path}",
                    kind=NodeKind.API_ENDPOINT,
                    language="python",
                    properties={
                        "method": http_method,
                        "path": full_path,
                        "framework": "fastapi",
                    },
                )
                nodes.append(endpoint_node)

                # HANDLES edge: function -> endpoint
                edges.append(GraphEdge(
                    source_fqn=func_node.fqn,
                    target_fqn=endpoint_fqn,
                    kind=EdgeKind.HANDLES,
                    confidence=Confidence.HIGH,
                    evidence="fastapi-decorator",
                ))

                # Entry point
                entry_points.append(EntryPoint(
                    fqn=endpoint_fqn,
                    kind="http_endpoint",
                    metadata={"method": http_method, "path": full_path},
                ))

                # Layer assignment
                layer_assignments[func_node.fqn] = "Presentation"

        # Phase 3: Extract Depends() injection edges
        inject_edges = self._resolve_depends(graph)
        edges.extend(inject_edges)

        log.info(
            "fastapi_extract_complete",
            endpoints=len([n for n in nodes if n.kind == NodeKind.API_ENDPOINT]),
            injects=len(inject_edges),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[
            LayerRule(pattern="@app.get", layer="Presentation"),
            LayerRule(pattern="@app.post", layer="Presentation"),
            LayerRule(pattern="@router.get", layer="Presentation"),
        ])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_router_prefix_map(self, graph: SymbolGraph) -> dict[str, str]:
        """Find APIRouter(..., prefix="/xxx") assignments and map variable name -> prefix."""
        prefix_map: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind != NodeKind.FIELD or node.language != "python":
                continue
            value = node.properties.get("value", "")
            match = _ROUTER_PREFIX_RE.search(value)
            if match:
                # node.name is the variable name (e.g., "router")
                prefix_map[node.name] = match.group(1)
        return prefix_map

    def _resolve_depends(self, graph: SymbolGraph) -> list[GraphEdge]:
        """Scan function params for Depends(...) and create INJECTS edges."""
        edges: list[GraphEdge] = []
        for node in graph.nodes.values():
            if node.kind != NodeKind.FUNCTION or node.language != "python":
                continue
            for param in node.properties.get("params", []):
                default = param.get("default", "")
                match = _DEPENDS_RE.search(default)
                if not match:
                    continue

                dep_ref = match.group(1)

                # Resolve the dependency function FQN
                dep_fqn = self._resolve_dependency_fqn(graph, node.fqn, dep_ref)
                if dep_fqn:
                    edges.append(GraphEdge(
                        source_fqn=dep_fqn,
                        target_fqn=node.fqn,
                        kind=EdgeKind.INJECTS,
                        confidence=Confidence.HIGH,
                        evidence="fastapi-depends",
                        properties={"framework": "fastapi"},
                    ))
        return edges

    def _resolve_dependency_fqn(
        self, graph: SymbolGraph, consumer_fqn: str, dep_ref: str
    ) -> str | None:
        """Resolve a Depends() reference to a graph node FQN.

        Tries: 1) same module (sibling function), 2) dotted path lookup,
        3) full FQN match anywhere in graph.
        """
        # Try sibling in same module
        module_fqn = ".".join(consumer_fqn.split(".")[:-1])
        candidate = f"{module_fqn}.{dep_ref}"
        if candidate in graph.nodes:
            return candidate

        # Try dotted reference as-is
        if dep_ref in graph.nodes:
            return dep_ref

        # Try fuzzy: search for nodes ending with the ref
        for fqn in graph.nodes:
            if fqn.endswith(f".{dep_ref}"):
                return fqn

        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_fastapi_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/fastapi_plugin/ tests/unit/test_fastapi_plugin.py && git commit -m "feat(plugins): add FastAPI plugin — route extraction, Depends() DI, entry points"
```

---

## Task 2: SQLAlchemy Plugin — Declarative Model Mapping

**Files:**
- Create: `app/stages/plugins/sqlalchemy_plugin/__init__.py`
- Create: `app/stages/plugins/sqlalchemy_plugin/models.py`
- Test: `tests/unit/test_sqlalchemy_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_sqlalchemy_plugin.py
"""Tests for the SQLAlchemy plugin — declarative model mapping, FK resolution, relationship edges."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult, PluginResult
from app.stages.plugins.sqlalchemy_plugin.models import SQLAlchemyPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_sqlalchemy() -> AnalysisContext:
    """Create an AnalysisContext with sqlalchemy detected."""
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="sqlalchemy",
                language="python",
                confidence=Confidence.HIGH,
                evidence=["pyproject.toml contains sqlalchemy"],
            ),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    bases: list[str] | None = None,
    annotations: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.CLASS,
        language="python",
        properties={
            "annotations": annotations or [],
        },
    )
    graph.add_node(node)
    for base in (bases or []):
        graph.add_edge(GraphEdge(
            source_fqn=fqn, target_fqn=base, kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW, evidence="tree-sitter",
        ))
    return node


def _add_field(
    graph: SymbolGraph,
    class_fqn: str,
    field_name: str,
    field_type: str | None = None,
    value: str | None = None,
    annotations: list[str] | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{field_name}"
    node = GraphNode(
        fqn=fqn,
        name=field_name,
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "type": field_type,
            "value": value or "",
            "annotations": annotations or [],
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestSQLAlchemyDetection:
    def test_detect_high_when_sqlalchemy_in_frameworks(self):
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_sqlalchemy(self):
        plugin = SQLAlchemyPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp"),
            detected_frameworks=[],
        )
        result = plugin.detect(ctx)
        assert result.is_active is False

    def test_detect_medium_when_tablename_found(self):
        """If no sqlalchemy in frameworks but __tablename__ fields exist."""
        plugin = SQLAlchemyPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp"),
            detected_frameworks=[],
        )
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM


# ---------------------------------------------------------------------------
# Entity-to-table mapping tests
# ---------------------------------------------------------------------------

class TestSQLAlchemyEntityMapping:
    @pytest.mark.asyncio
    async def test_model_creates_table_node(self):
        """Class with __tablename__ -> Table node + MAPS_TO edge."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')
        _add_field(ctx.graph, "myapp.models.User", "name", value='Column(String(50))')
        _add_field(ctx.graph, "myapp.models.User", "email", value='Column(String, unique=True)')

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "users"
        assert table_nodes[0].fqn == "table:users"

        maps_to = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
        assert len(maps_to) == 1
        assert maps_to[0].source_fqn == "myapp.models.User"
        assert maps_to[0].target_fqn == "table:users"
        assert maps_to[0].properties.get("orm") == "sqlalchemy"

    @pytest.mark.asyncio
    async def test_columns_create_column_nodes(self):
        """Column() fields -> Column nodes + HAS_COLUMN edges."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')
        _add_field(ctx.graph, "myapp.models.User", "name", value='Column(String(50))')

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        column_names = {n.name for n in column_nodes}
        assert "id" in column_names
        assert "name" in column_names

        has_col_edges = [e for e in result.edges if e.kind == EdgeKind.HAS_COLUMN]
        assert len(has_col_edges) >= 2
        assert all(e.source_fqn == "table:users" for e in has_col_edges)

    @pytest.mark.asyncio
    async def test_primary_key_detected(self):
        """Column(primary_key=True) -> Column node with is_primary_key property."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        id_col = [n for n in column_nodes if n.name == "id"][0]
        assert id_col.properties.get("is_primary_key") is True

    @pytest.mark.asyncio
    async def test_mapped_column_style(self):
        """SQLAlchemy 2.0 mapped_column() style also detected."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='mapped_column(primary_key=True)')
        _add_field(ctx.graph, "myapp.models.User", "name", value='mapped_column(String(50))')

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        assert len(column_nodes) >= 2

    @pytest.mark.asyncio
    async def test_class_without_tablename_is_skipped(self):
        """Class inheriting Base but without __tablename__ (abstract) -> no Table."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.BaseModel", "BaseModel", bases=["myapp.db.Base"])
        # No __tablename__ field -> abstract model

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 0


# ---------------------------------------------------------------------------
# Foreign key relationship tests
# ---------------------------------------------------------------------------

class TestSQLAlchemyRelationships:
    @pytest.mark.asyncio
    async def test_foreign_key_creates_references_edge(self):
        """Column(ForeignKey("users.id")) -> REFERENCES edge."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()

        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')

        _add_class(ctx.graph, "myapp.models.Post", "Post", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.Post", "__tablename__", value='"posts"')
        _add_field(ctx.graph, "myapp.models.Post", "id", value='Column(Integer, primary_key=True)')
        _add_field(
            ctx.graph, "myapp.models.Post", "author_id",
            value='Column(Integer, ForeignKey("users.id"))',
        )

        result = await plugin.extract(ctx)
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1
        assert "author_id" in ref_edges[0].source_fqn
        assert "id" in ref_edges[0].target_fqn

    @pytest.mark.asyncio
    async def test_relationship_field_is_ignored_for_columns(self):
        """relationship("User") field should NOT create a Column node (it's ORM-only)."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()

        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')

        _add_class(ctx.graph, "myapp.models.Post", "Post", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.Post", "__tablename__", value='"posts"')
        _add_field(ctx.graph, "myapp.models.Post", "id", value='Column(Integer, primary_key=True)')
        _add_field(ctx.graph, "myapp.models.Post", "author_id", value='Column(Integer, ForeignKey("users.id"))')
        _add_field(ctx.graph, "myapp.models.Post", "author", value='relationship("User", back_populates="posts")')

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        column_names = {n.name for n in column_nodes}
        assert "author" not in column_names  # relationship is not a column

    @pytest.mark.asyncio
    async def test_multiple_models_with_fks(self):
        """Multiple models with cross-references produce correct REFERENCES edges."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()

        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')
        _add_field(ctx.graph, "myapp.models.User", "id", value='Column(Integer, primary_key=True)')

        _add_class(ctx.graph, "myapp.models.Post", "Post", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.Post", "__tablename__", value='"posts"')
        _add_field(ctx.graph, "myapp.models.Post", "id", value='Column(Integer, primary_key=True)')
        _add_field(ctx.graph, "myapp.models.Post", "author_id", value='Column(Integer, ForeignKey("users.id"))')

        _add_class(ctx.graph, "myapp.models.Comment", "Comment", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.Comment", "__tablename__", value='"comments"')
        _add_field(ctx.graph, "myapp.models.Comment", "id", value='Column(Integer, primary_key=True)')
        _add_field(ctx.graph, "myapp.models.Comment", "post_id", value='Column(Integer, ForeignKey("posts.id"))')
        _add_field(ctx.graph, "myapp.models.Comment", "user_id", value='Column(Integer, ForeignKey("users.id"))')

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 3
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 3  # author_id->users.id, post_id->posts.id, user_id->users.id


# ---------------------------------------------------------------------------
# Layer classification tests
# ---------------------------------------------------------------------------

class TestSQLAlchemyLayerClassification:
    @pytest.mark.asyncio
    async def test_model_is_data_access(self):
        """SQLAlchemy model classes -> Data Access layer."""
        plugin = SQLAlchemyPlugin()
        ctx = _make_context_with_sqlalchemy()
        _add_class(ctx.graph, "myapp.models.User", "User", bases=["myapp.db.Base"])
        _add_field(ctx.graph, "myapp.models.User", "__tablename__", value='"users"')

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("myapp.models.User") == "Data Access"


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestSQLAlchemyPluginMetadata:
    def test_plugin_name(self):
        assert SQLAlchemyPlugin().name == "sqlalchemy"

    def test_supported_languages(self):
        assert SQLAlchemyPlugin().supported_languages == {"python"}

    def test_depends_on_empty(self):
        assert SQLAlchemyPlugin().depends_on == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_sqlalchemy_plugin.py -v`
Expected: FAIL (ImportError — `app.stages.plugins.sqlalchemy_plugin.models` doesn't exist)

- [ ] **Step 3: Create `__init__.py`**

```python
# app/stages/plugins/sqlalchemy_plugin/__init__.py
"""SQLAlchemy framework plugin — declarative model-to-table mapping, FK resolution."""

from app.stages.plugins.sqlalchemy_plugin.models import SQLAlchemyPlugin

__all__ = ["SQLAlchemyPlugin"]
```

- [ ] **Step 4: Implement `sqlalchemy_plugin/models.py`**

```python
# app/stages/plugins/sqlalchemy_plugin/models.py
"""SQLAlchemy plugin.

Detects SQLAlchemy declarative models (classes with __tablename__),
extracts Column definitions, resolves ForeignKey references, and
produces Table/Column nodes + MAPS_TO/HAS_COLUMN/REFERENCES edges.

Produces:
- Table nodes: (:Table {name})
- Column nodes: (:Column {name, is_primary_key, column_type})
- MAPS_TO edges: (:Class)-[:MAPS_TO {orm: "sqlalchemy"}]->(:Table)
- HAS_COLUMN edges: (:Table)-[:HAS_COLUMN]->(:Column)
- REFERENCES edges: (:Column)-[:REFERENCES]->(:Column)
- Layer assignments: model classes -> Data Access
"""

from __future__ import annotations

import re
import structlog

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Regex patterns for parsing Column/mapped_column values
_COLUMN_RE = re.compile(r"^(Column|mapped_column)\(")
_FK_RE = re.compile(r'ForeignKey\(\s*["\']([^"\']+)["\']\s*\)')
_PK_RE = re.compile(r"primary_key\s*=\s*True")
_RELATIONSHIP_RE = re.compile(r'^relationship\(')
_TABLENAME_RE = re.compile(r'^["\']([^"\']+)["\']$')


class SQLAlchemyPlugin(FrameworkPlugin):
    name = "sqlalchemy"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "sqlalchemy" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: look for __tablename__ fields
        for node in context.graph.nodes.values():
            if (
                node.kind == NodeKind.FIELD
                and node.language == "python"
                and node.name == "__tablename__"
            ):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="__tablename__ field found in graph",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("sqlalchemy_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        # Find all models: classes that have a __tablename__ child field
        models = self._find_models(graph)
        log.info("sqlalchemy_models_found", count=len(models))

        for model_fqn, table_name in models.items():
            # Create Table node
            table_fqn = f"table:{table_name}"
            table_node = GraphNode(
                fqn=table_fqn,
                name=table_name,
                kind=NodeKind.TABLE,
                properties={"orm": "sqlalchemy"},
            )
            nodes.append(table_node)

            # MAPS_TO edge
            edges.append(GraphEdge(
                source_fqn=model_fqn,
                target_fqn=table_fqn,
                kind=EdgeKind.MAPS_TO,
                confidence=Confidence.HIGH,
                evidence="sqlalchemy-tablename",
                properties={"orm": "sqlalchemy"},
            ))

            # Layer assignment
            layer_assignments[model_fqn] = "Data Access"

            # Extract columns from class fields
            col_nodes, col_edges, fk_edges = self._extract_columns(
                graph, model_fqn, table_name
            )
            nodes.extend(col_nodes)
            edges.extend(col_edges)
            edges.extend(fk_edges)

        log.info(
            "sqlalchemy_extract_complete",
            tables=len(models),
            columns=len([n for n in nodes if n.kind == NodeKind.COLUMN]),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_models(self, graph: SymbolGraph) -> dict[str, str]:
        """Find classes with __tablename__ field. Returns {class_fqn: table_name}."""
        models: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind != NodeKind.FIELD or node.name != "__tablename__":
                continue
            # Find parent class via CONTAINS edge
            for edge in graph.edges:
                if edge.target_fqn == node.fqn and edge.kind == EdgeKind.CONTAINS:
                    class_fqn = edge.source_fqn
                    # Extract table name from value
                    value = node.properties.get("value", "").strip()
                    match = _TABLENAME_RE.match(value)
                    if match:
                        models[class_fqn] = match.group(1)
                    break
        return models

    def _extract_columns(
        self,
        graph: SymbolGraph,
        model_fqn: str,
        table_name: str,
    ) -> tuple[list[GraphNode], list[GraphEdge], list[GraphEdge]]:
        """Extract Column nodes and FK edges from a model's fields."""
        col_nodes: list[GraphNode] = []
        has_col_edges: list[GraphEdge] = []
        fk_edges: list[GraphEdge] = []
        table_fqn = f"table:{table_name}"

        # Find all FIELD children of this class
        for edge in graph.edges:
            if edge.source_fqn != model_fqn or edge.kind != EdgeKind.CONTAINS:
                continue
            field_node = graph.nodes.get(edge.target_fqn)
            if not field_node or field_node.kind != NodeKind.FIELD:
                continue

            field_name = field_node.name
            value = field_node.properties.get("value", "")

            # Skip __tablename__, __table_args__, and relationship() fields
            if field_name.startswith("__"):
                continue
            if _RELATIONSHIP_RE.match(value):
                continue

            # Only process Column() or mapped_column() fields
            if not _COLUMN_RE.match(value):
                continue

            # Create Column node
            is_pk = bool(_PK_RE.search(value))
            col_fqn = f"table:{table_name}.{field_name}"
            col_node = GraphNode(
                fqn=col_fqn,
                name=field_name,
                kind=NodeKind.COLUMN,
                properties={
                    "is_primary_key": is_pk,
                    "table": table_name,
                },
            )
            col_nodes.append(col_node)

            # HAS_COLUMN edge
            has_col_edges.append(GraphEdge(
                source_fqn=table_fqn,
                target_fqn=col_fqn,
                kind=EdgeKind.HAS_COLUMN,
                confidence=Confidence.HIGH,
                evidence="sqlalchemy-column",
            ))

            # Check for ForeignKey
            fk_match = _FK_RE.search(value)
            if fk_match:
                fk_target = fk_match.group(1)  # e.g., "users.id"
                parts = fk_target.split(".")
                if len(parts) == 2:
                    target_table, target_col = parts
                    target_col_fqn = f"table:{target_table}.{target_col}"
                    fk_edges.append(GraphEdge(
                        source_fqn=col_fqn,
                        target_fqn=target_col_fqn,
                        kind=EdgeKind.REFERENCES,
                        confidence=Confidence.HIGH,
                        evidence="sqlalchemy-foreignkey",
                    ))

        return col_nodes, has_col_edges, fk_edges
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_sqlalchemy_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/sqlalchemy_plugin/ tests/unit/test_sqlalchemy_plugin.py && git commit -m "feat(plugins): add SQLAlchemy plugin — declarative model mapping, ForeignKey resolution"
```

---

## Task 3: Register Both Plugins in Global Registry

**Files:**
- Modify: `app/stages/plugins/__init__.py`

- [ ] **Step 1: Add imports and registrations**

Add the following after the existing Spring/Hibernate/SQL registrations in `app/stages/plugins/__init__.py`:

```python
from app.stages.plugins.fastapi_plugin.routes import FastAPIPlugin
from app.stages.plugins.sqlalchemy_plugin.models import SQLAlchemyPlugin

global_registry.register(FastAPIPlugin)
global_registry.register(SQLAlchemyPlugin)
```

Also add to `__all__`:
```python
"FastAPIPlugin",
"SQLAlchemyPlugin",
```

- [ ] **Step 2: Verify imports work**

Run: `cd cast-clone-backend && uv run python -c "from app.stages.plugins.fastapi_plugin import FastAPIPlugin; from app.stages.plugins.sqlalchemy_plugin import SQLAlchemyPlugin; print('OK')"`

- [ ] **Step 3: Run the full test suite**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_fastapi_plugin.py tests/unit/test_sqlalchemy_plugin.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/__init__.py && git commit -m "feat(plugins): register FastAPI and SQLAlchemy plugins in global registry"
```

---

## Task 4: Lint and Type-Check

- [ ] **Step 1: Run ruff check**

Run: `cd cast-clone-backend && uv run ruff check app/stages/plugins/fastapi_plugin/ app/stages/plugins/sqlalchemy_plugin/ tests/unit/test_fastapi_plugin.py tests/unit/test_sqlalchemy_plugin.py`
Expected: No errors. If there are errors, fix them.

- [ ] **Step 2: Run ruff format**

Run: `cd cast-clone-backend && uv run ruff format app/stages/plugins/fastapi_plugin/ app/stages/plugins/sqlalchemy_plugin/ tests/unit/test_fastapi_plugin.py tests/unit/test_sqlalchemy_plugin.py`

- [ ] **Step 3: Commit any formatting fixes**

```bash
cd cast-clone-backend && git add -u && git commit -m "style(plugins): apply ruff formatting to FastAPI and SQLAlchemy plugins"
```

---

## Summary of Produced Graph Artifacts

| Plugin | Nodes Created | Edges Created |
|--------|--------------|---------------|
| `fastapi` | `APIEndpoint` | `HANDLES` (Function->APIEndpoint), `INJECTS` (Function->Function) |
| `sqlalchemy` | `Table`, `Column` | `MAPS_TO` (Class->Table), `HAS_COLUMN` (Table->Column), `REFERENCES` (Column->Column) |

## Dependency Chain

```
fastapi (no deps)       ── can run in parallel ──     sqlalchemy (no deps)
```

Both plugins are independent and can execute concurrently via the registry's topological sort.

---

## Implementation Notes

### FQN Conventions

- **APIEndpoint FQN:** `{METHOD}:{path}` (e.g., `GET:/api/v1/users/{user_id}`)
- **Table FQN:** `table:{table_name}` (e.g., `table:users`) — matches Hibernate convention from M6b
- **Column FQN:** `table:{table_name}.{column_name}` (e.g., `table:users.email`) — matches M6c convention

### Decorator Parsing

Python decorators are stored as full text strings by the tree-sitter extractor. The FastAPI plugin uses regex to parse these strings. Examples of what the regex handles:
- `app.get("/users")` → method=GET, path=/users
- `router.post("/users/{user_id}")` → method=POST, path=/users/{user_id}
- `app.delete("/items/{item_id}")` → method=DELETE, path=/items/{item_id}

The regex deliberately matches any variable name (not just `app` or `router`) to handle custom FastAPI instance names.

### Column Value Parsing

SQLAlchemy field values are stored as the raw assignment RHS text. The plugin uses regex to detect:
- `Column(...)` vs `mapped_column(...)` — both are valid column definitions
- `ForeignKey("table.column")` — FK reference extraction
- `primary_key=True` — PK detection
- `relationship(...)` — ORM-only, not a database column (skipped)

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] `uv run pytest tests/unit/test_fastapi_plugin.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/test_sqlalchemy_plugin.py -v` — all tests pass
- [ ] `uv run ruff check app/stages/plugins/fastapi_plugin/ app/stages/plugins/sqlalchemy_plugin/` — no lint errors
- [ ] `app/stages/plugins/fastapi_plugin/__init__.py` exports `FastAPIPlugin`
- [ ] `app/stages/plugins/sqlalchemy_plugin/__init__.py` exports `SQLAlchemyPlugin`
- [ ] FastAPI plugin produces `APIEndpoint` nodes with `method` and `path` properties
- [ ] FastAPI plugin produces `INJECTS` edges for `Depends()` parameters
- [ ] FastAPI plugin produces `EntryPoint` objects for each endpoint
- [ ] SQLAlchemy plugin produces `Table`/`Column` nodes matching Hibernate FQN conventions
- [ ] SQLAlchemy plugin produces `REFERENCES` edges for `ForeignKey()` fields
- [ ] Both plugins are registered in `global_registry` via `__init__.py`
- [ ] `relationship()` fields do NOT create Column nodes
- [ ] Abstract models (no `__tablename__`) do NOT create Table nodes