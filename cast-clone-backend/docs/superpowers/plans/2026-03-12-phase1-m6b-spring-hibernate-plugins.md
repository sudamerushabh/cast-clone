# M6b: Spring DI, Spring Web, Spring Data & Hibernate/JPA Plugins Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the four Tier 1 Java/Spring framework plugins that extract invisible connections — dependency injection wiring, REST endpoint mappings, JPA entity-to-table mappings with FK relationships, and Spring Data repository query resolution. These plugins read from the existing `SymbolGraph` (populated by tree-sitter in earlier stages) and produce new nodes/edges via `PluginResult`.

**Architecture:** Each plugin extends `FrameworkPlugin` (from M6a). Plugins scan `context.graph` for Java classes/fields/methods with specific annotations (stored in `node.properties["annotations"]`), resolve cross-class relationships (interface-to-implementor, entity-to-table), and emit `INJECTS`, `HANDLES`, `EXPOSES`, `MAPS_TO`, `HAS_COLUMN`, `REFERENCES`, `READS`, `WRITES`, and `MANAGES` edges. Hibernate runs before Spring Data (dependency chain: `spring-di` -> `hibernate` -> `spring-data`; `spring-di` -> `spring-web`).

**Tech Stack:** Python 3.12, dataclasses, re (for derived query parsing), pytest+pytest-asyncio

**Dependencies:** M1 (AnalysisContext, SymbolGraph, GraphNode, GraphEdge, enums), M6a (FrameworkPlugin, PluginResult, PluginDetectionResult, LayerRules, LayerRule)

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       └── plugins/
│           ├── spring/
│           │   ├── __init__.py              # CREATE — re-export plugin classes
│           │   ├── di.py                    # CREATE — SpringDIPlugin
│           │   ├── web.py                   # CREATE — SpringWebPlugin
│           │   └── data.py                  # CREATE — SpringDataPlugin
│           └── hibernate/
│               ├── __init__.py              # CREATE — re-export plugin classes
│               └── jpa.py                   # CREATE — HibernateJPAPlugin
├── tests/
│   └── unit/
│       ├── test_spring_di_plugin.py         # CREATE
│       ├── test_spring_web_plugin.py        # CREATE
│       ├── test_spring_data_plugin.py       # CREATE
│       └── test_hibernate_plugin.py         # CREATE
```

---

## Shared Test Helpers

All four test files need to build `AnalysisContext` objects pre-populated with tree-sitter-parsed Java nodes. We define helpers at the top of each test file (or they can be extracted to a conftest later). The key convention from tree-sitter extractors (M4b): annotations are stored in `node.properties["annotations"]` as a `list[str]`, field types in `properties["type"]`, generic type args in `properties["type_args"]`, annotation arguments in `properties["annotation_args"]` as a `dict[str, str]`, and interface implementations in `properties["implements"]` as a `list[str]`.

**Node conventions from tree-sitter (M4b):**
- `Class` nodes: `properties["annotations"]` = `["Service", "Component", ...]`, `properties["implements"]` = `["UserRepository", ...]`, `properties["is_interface"]` = `True/False`
- `Field` nodes: `properties["annotations"]` = `["Autowired", "Qualifier", ...]`, `properties["type"]` = `"UserService"`, `properties["annotation_args"]` = `{"Qualifier": "primaryUserService"}`
- `Function` nodes: `properties["annotations"]` = `["GetMapping", ...]`, `properties["annotation_args"]` = `{"GetMapping": "/users/{id}"}`, `properties["params"]` = `[{"name": "id", "type": "Long", "annotations": ["PathVariable"]}]`, `properties["return_type"]` = `"User"`, `properties["is_constructor"]` = `True/False`
- Containment: `(:Class)-[:CONTAINS]->(:Field)` and `(:Class)-[:CONTAINS]->(:Function)` edges exist
- Inheritance: `(:Class)-[:IMPLEMENTS]->(:Interface)` edges exist

---

## Task 1: Spring DI Plugin (`spring/di.py`)

**Files:**
- Create: `app/stages/plugins/spring/__init__.py`
- Create: `app/stages/plugins/spring/di.py`
- Test: `tests/unit/test_spring_di_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_spring_di_plugin.py
"""Tests for the Spring DI plugin — bean detection, injection resolution, layer classification."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult
from app.stages.plugins.spring.di import SpringDIPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_spring() -> AnalysisContext:
    """Create an AnalysisContext with spring-boot detected and a populated graph."""
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="spring-boot",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains spring-boot-starter"],
            ),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    annotations: list[str] | None = None,
    implements: list[str] | None = None,
    is_interface: bool = False,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.INTERFACE if is_interface else NodeKind.CLASS,
        language="java",
        properties={
            "annotations": annotations or [],
            "implements": implements or [],
            "is_interface": is_interface,
        },
    )
    graph.add_node(node)
    return node


def _add_field(
    graph: SymbolGraph,
    class_fqn: str,
    field_name: str,
    field_type: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{field_name}"
    node = GraphNode(
        fqn=fqn,
        name=field_name,
        kind=NodeKind.FIELD,
        language="java",
        properties={
            "type": field_type,
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


def _add_constructor(
    graph: SymbolGraph,
    class_fqn: str,
    params: list[dict],
) -> GraphNode:
    fqn = f"{class_fqn}.<init>"
    node = GraphNode(
        fqn=fqn,
        name="<init>",
        kind=NodeKind.FUNCTION,
        language="java",
        properties={
            "is_constructor": True,
            "params": params,
            "annotations": [],
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


def _add_method(
    graph: SymbolGraph,
    class_fqn: str,
    method_name: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    return_type: str | None = None,
    params: list[dict] | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{method_name}"
    node = GraphNode(
        fqn=fqn,
        name=method_name,
        kind=NodeKind.FUNCTION,
        language="java",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "return_type": return_type,
            "params": params or [],
            "is_constructor": False,
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

class TestSpringDIPluginDetection:
    def test_detect_high_when_spring_boot_present(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_when_no_spring(self):
        plugin = SpringDIPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp/test"),
            detected_frameworks=[],
        )
        result = plugin.detect(ctx)
        assert result.is_active is False

    def test_detect_medium_when_annotations_found_but_no_framework(self):
        """If no spring-boot in frameworks but @Component annotations exist in graph."""
        plugin = SpringDIPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp/test"),
            detected_frameworks=[],
        )
        _add_class(ctx.graph, "com.example.Foo", "Foo", annotations=["Component"])
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM


# ---------------------------------------------------------------------------
# Bean detection tests
# ---------------------------------------------------------------------------

class TestSpringDIBeanDetection:
    @pytest.mark.asyncio
    async def test_stereotype_annotations_detected_as_beans(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserService", "UserService", annotations=["Service"])
        _add_class(ctx.graph, "com.example.UserRepo", "UserRepo", annotations=["Repository"])
        _add_class(ctx.graph, "com.example.UserController", "UserController", annotations=["RestController"])
        _add_class(ctx.graph, "com.example.AppConfig", "AppConfig", annotations=["Configuration"])
        _add_class(ctx.graph, "com.example.NotABean", "NotABean")

        result = await plugin.extract(ctx)
        # Layer assignments should exist for all annotated beans
        assert result.layer_assignments.get("com.example.UserService") == "Business Logic"
        assert result.layer_assignments.get("com.example.UserRepo") == "Data Access"
        assert result.layer_assignments.get("com.example.UserController") == "Presentation"
        assert result.layer_assignments.get("com.example.AppConfig") == "Configuration"
        assert "com.example.NotABean" not in result.layer_assignments

    @pytest.mark.asyncio
    async def test_bean_methods_in_configuration_class(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.AppConfig", "AppConfig", annotations=["Configuration"])
        _add_method(
            ctx.graph,
            "com.example.AppConfig",
            "dataSource",
            annotations=["Bean"],
            return_type="DataSource",
        )

        result = await plugin.extract(ctx)
        # The @Bean method should register DataSource as a bean type
        # We verify by checking that if someone injects DataSource, it resolves
        # (tested in injection resolution tests below)
        assert result.layer_assignments.get("com.example.AppConfig") == "Configuration"


# ---------------------------------------------------------------------------
# Injection resolution tests
# ---------------------------------------------------------------------------

class TestSpringDIInjectionResolution:
    @pytest.mark.asyncio
    async def test_autowired_field_concrete_class(self):
        """@Autowired on a field with a concrete class type -> direct HIGH confidence edge."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserService", "UserService", annotations=["Service"])
        _add_class(ctx.graph, "com.example.UserController", "UserController", annotations=["RestController"])
        _add_field(
            ctx.graph, "com.example.UserController", "userService",
            field_type="UserService", annotations=["Autowired"],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].source_fqn == "com.example.UserController"
        assert inject_edges[0].target_fqn == "com.example.UserService"
        assert inject_edges[0].confidence == Confidence.HIGH
        assert inject_edges[0].properties.get("framework") == "spring"

    @pytest.mark.asyncio
    async def test_autowired_interface_single_implementor(self):
        """Interface with exactly one implementor -> HIGH confidence."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserRepo", "UserRepo", is_interface=True)
        _add_class(
            ctx.graph, "com.example.UserRepoImpl", "UserRepoImpl",
            annotations=["Repository"], implements=["UserRepo"],
        )
        # Add IMPLEMENTS edge (tree-sitter would have created this)
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.UserRepoImpl",
            target_fqn="com.example.UserRepo",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(ctx.graph, "com.example.UserService", "UserService", annotations=["Service"])
        _add_field(
            ctx.graph, "com.example.UserService", "userRepo",
            field_type="UserRepo", annotations=["Autowired"],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].source_fqn == "com.example.UserService"
        assert inject_edges[0].target_fqn == "com.example.UserRepoImpl"
        assert inject_edges[0].confidence == Confidence.HIGH

    @pytest.mark.asyncio
    async def test_autowired_interface_multiple_impls_with_primary(self):
        """Multiple implementors with @Primary -> resolve to the @Primary one."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.Notifier", "Notifier", is_interface=True)
        _add_class(
            ctx.graph, "com.example.EmailNotifier", "EmailNotifier",
            annotations=["Component", "Primary"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.EmailNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(
            ctx.graph, "com.example.SmsNotifier", "SmsNotifier",
            annotations=["Component"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.SmsNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(ctx.graph, "com.example.AlertService", "AlertService", annotations=["Service"])
        _add_field(
            ctx.graph, "com.example.AlertService", "notifier",
            field_type="Notifier", annotations=["Autowired"],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].target_fqn == "com.example.EmailNotifier"
        assert inject_edges[0].confidence == Confidence.HIGH

    @pytest.mark.asyncio
    async def test_autowired_interface_multiple_impls_with_qualifier(self):
        """Multiple implementors with @Qualifier -> resolve by qualifier match."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.Notifier", "Notifier", is_interface=True)
        _add_class(
            ctx.graph, "com.example.EmailNotifier", "EmailNotifier",
            annotations=["Component"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.EmailNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(
            ctx.graph, "com.example.SmsNotifier", "SmsNotifier",
            annotations=["Component"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.SmsNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(ctx.graph, "com.example.AlertService", "AlertService", annotations=["Service"])
        _add_field(
            ctx.graph, "com.example.AlertService", "notifier",
            field_type="Notifier",
            annotations=["Autowired", "Qualifier"],
            annotation_args={"Qualifier": "smsNotifier"},
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].target_fqn == "com.example.SmsNotifier"
        assert inject_edges[0].confidence == Confidence.HIGH
        assert inject_edges[0].properties.get("qualifier") == "smsNotifier"

    @pytest.mark.asyncio
    async def test_autowired_interface_multiple_impls_ambiguous(self):
        """Multiple implementors, no @Primary, no @Qualifier -> LOW confidence edges to all."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.Notifier", "Notifier", is_interface=True)
        _add_class(
            ctx.graph, "com.example.EmailNotifier", "EmailNotifier",
            annotations=["Component"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.EmailNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(
            ctx.graph, "com.example.SmsNotifier", "SmsNotifier",
            annotations=["Component"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.SmsNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(ctx.graph, "com.example.AlertService", "AlertService", annotations=["Service"])
        _add_field(
            ctx.graph, "com.example.AlertService", "notifier",
            field_type="Notifier", annotations=["Autowired"],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 2
        targets = {e.target_fqn for e in inject_edges}
        assert targets == {"com.example.EmailNotifier", "com.example.SmsNotifier"}
        assert all(e.confidence == Confidence.LOW for e in inject_edges)

    @pytest.mark.asyncio
    async def test_constructor_injection(self):
        """Constructor params matching bean types -> INJECTS edges."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserService", "UserService", annotations=["Service"])
        _add_class(ctx.graph, "com.example.OrderService", "OrderService", annotations=["Service"])
        _add_class(ctx.graph, "com.example.UserController", "UserController", annotations=["RestController"])
        _add_constructor(ctx.graph, "com.example.UserController", params=[
            {"name": "userService", "type": "UserService", "annotations": []},
            {"name": "orderService", "type": "OrderService", "annotations": []},
        ])

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 2
        targets = {e.target_fqn for e in inject_edges}
        assert "com.example.UserService" in targets
        assert "com.example.OrderService" in targets

    @pytest.mark.asyncio
    async def test_bean_method_injection(self):
        """@Bean method return type is injectable."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.AppConfig", "AppConfig", annotations=["Configuration"])
        _add_method(
            ctx.graph, "com.example.AppConfig", "dataSource",
            annotations=["Bean"], return_type="DataSource",
        )
        _add_class(ctx.graph, "com.example.UserRepo", "UserRepo", annotations=["Repository"])
        _add_field(
            ctx.graph, "com.example.UserRepo", "ds",
            field_type="DataSource", annotations=["Autowired"],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        # Should resolve DataSource -> the @Bean method's declaring class (AppConfig)
        assert len(inject_edges) == 1
        assert inject_edges[0].source_fqn == "com.example.UserRepo"
        assert inject_edges[0].target_fqn == "com.example.AppConfig"
        assert inject_edges[0].confidence == Confidence.HIGH


# ---------------------------------------------------------------------------
# Layer classification tests
# ---------------------------------------------------------------------------

class TestSpringDILayerClassification:
    def test_layer_rules(self):
        plugin = SpringDIPlugin()
        rules = plugin.get_layer_classification()
        assert len(rules.rules) > 0

    @pytest.mark.asyncio
    async def test_controller_is_presentation(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController", annotations=["Controller"])
        result = await plugin.extract(ctx)
        assert result.layer_assignments["com.example.UserController"] == "Presentation"

    @pytest.mark.asyncio
    async def test_rest_controller_is_presentation(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.ApiController", "ApiController", annotations=["RestController"])
        result = await plugin.extract(ctx)
        assert result.layer_assignments["com.example.ApiController"] == "Presentation"

    @pytest.mark.asyncio
    async def test_service_is_business_logic(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserService", "UserService", annotations=["Service"])
        result = await plugin.extract(ctx)
        assert result.layer_assignments["com.example.UserService"] == "Business Logic"

    @pytest.mark.asyncio
    async def test_repository_is_data_access(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserRepo", "UserRepo", annotations=["Repository"])
        result = await plugin.extract(ctx)
        assert result.layer_assignments["com.example.UserRepo"] == "Data Access"


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestSpringDIPluginMetadata:
    def test_plugin_name(self):
        plugin = SpringDIPlugin()
        assert plugin.name == "spring-di"

    def test_supported_languages(self):
        plugin = SpringDIPlugin()
        assert plugin.supported_languages == {"java"}

    def test_depends_on_empty(self):
        plugin = SpringDIPlugin()
        assert plugin.depends_on == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_spring_di_plugin.py -v`
Expected: FAIL (ImportError — `app.stages.plugins.spring.di` doesn't exist)

- [ ] **Step 3: Create `__init__.py` files**

```python
# app/stages/plugins/spring/__init__.py
"""Spring framework plugins — DI, Web, Data."""

from app.stages.plugins.spring.di import SpringDIPlugin
from app.stages.plugins.spring.web import SpringWebPlugin
from app.stages.plugins.spring.data import SpringDataPlugin

__all__ = ["SpringDIPlugin", "SpringWebPlugin", "SpringDataPlugin"]
```

Note: This file will fail to import until all three plugins exist. For initial development, start with only the `SpringDIPlugin` import and add others as they are implemented. Or use lazy imports / try-except.

- [ ] **Step 4: Implement `spring/di.py`**

```python
# app/stages/plugins/spring/di.py
"""Spring Dependency Injection plugin.

Detects Spring beans (@Component, @Service, @Repository, @Controller,
@RestController, @Configuration, @Bean methods) and resolves injection
wiring (@Autowired fields, constructor injection).

Produces:
- INJECTS edges: (:Class)-[:INJECTS {framework, qualifier, confidence}]->(:Class)
- Layer assignments: Controller->Presentation, Service->Business Logic, etc.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field

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

# Annotations that mark a class as a Spring bean
STEREOTYPE_ANNOTATIONS = frozenset({
    "Component", "Service", "Repository",
    "Controller", "RestController", "Configuration",
})

# Annotation -> architectural layer
_LAYER_MAP: dict[str, str] = {
    "Controller": "Presentation",
    "RestController": "Presentation",
    "Service": "Business Logic",
    "Repository": "Data Access",
    "Configuration": "Configuration",
}


@dataclass
class _BeanInfo:
    """Internal tracking for a detected Spring bean."""
    fqn: str
    name: str
    bean_type: str  # The type this bean provides (class name or interface name)
    is_primary: bool = False
    source: str = "stereotype"  # "stereotype" or "bean_method"


class SpringDIPlugin(FrameworkPlugin):
    name = "spring-di"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        # Check manifest for spring-boot framework detection
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "spring" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: check graph for Spring annotations
        for node in context.graph.nodes.values():
            annotations = node.properties.get("annotations", [])
            if any(a in STEREOTYPE_ANNOTATIONS for a in annotations):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="Spring stereotype annotations found in graph",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("spring_di_extract_start")

        graph = context.graph
        edges: list[GraphEdge] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        # Phase 1: Detect all beans (stereotype + @Bean methods)
        beans = self._detect_beans(graph)
        log.info("spring_di_beans_detected", count=len(beans))

        # Phase 2: Assign layers
        for fqn, layer in self._classify_layers(graph).items():
            layer_assignments[fqn] = layer

        # Phase 3: Resolve injections
        inject_edges = self._resolve_injections(graph, beans)
        edges.extend(inject_edges)
        log.info("spring_di_injections_resolved", count=len(inject_edges))

        return PluginResult(
            nodes=[],
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[
            LayerRule(pattern="@RestController", layer="Presentation"),
            LayerRule(pattern="@Controller", layer="Presentation"),
            LayerRule(pattern="@Service", layer="Business Logic"),
            LayerRule(pattern="@Repository", layer="Data Access"),
            LayerRule(pattern="@Configuration", layer="Configuration"),
        ])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_beans(self, graph: SymbolGraph) -> dict[str, _BeanInfo]:
        """Find all Spring beans: stereotype-annotated classes + @Bean methods.

        Returns a dict of bean_type_name -> _BeanInfo. For stereotypes, the
        bean_type is the class name. For @Bean methods, the bean_type is the
        method return type.
        """
        beans: dict[str, list[_BeanInfo]] = {}

        for node in graph.nodes.values():
            if node.kind not in (NodeKind.CLASS, NodeKind.INTERFACE):
                continue
            annotations = set(node.properties.get("annotations", []))
            if annotations & STEREOTYPE_ANNOTATIONS:
                info = _BeanInfo(
                    fqn=node.fqn,
                    name=node.name,
                    bean_type=node.name,
                    is_primary="Primary" in annotations,
                )
                beans.setdefault(node.name, []).append(info)

        # Scan for @Bean methods in @Configuration classes
        for node in graph.nodes.values():
            if node.kind != NodeKind.CLASS:
                continue
            annotations = set(node.properties.get("annotations", []))
            if "Configuration" not in annotations:
                continue
            # Find methods in this class
            for edge in graph.get_edges_from(node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                method = graph.get_node(edge.target_fqn)
                if method is None or method.kind != NodeKind.FUNCTION:
                    continue
                method_annotations = set(method.properties.get("annotations", []))
                if "Bean" in method_annotations:
                    return_type = method.properties.get("return_type")
                    if return_type:
                        info = _BeanInfo(
                            fqn=node.fqn,  # The config class FQN
                            name=method.name,
                            bean_type=return_type,
                            source="bean_method",
                        )
                        beans.setdefault(return_type, []).append(info)

        return beans

    def _classify_layers(self, graph: SymbolGraph) -> dict[str, str]:
        """Assign architectural layers based on stereotype annotations."""
        assignments: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind not in (NodeKind.CLASS, NodeKind.INTERFACE):
                continue
            annotations = node.properties.get("annotations", [])
            for ann in annotations:
                if ann in _LAYER_MAP:
                    assignments[node.fqn] = _LAYER_MAP[ann]
                    break
        return assignments

    def _resolve_injections(
        self, graph: SymbolGraph, beans: dict[str, list[_BeanInfo]]
    ) -> list[GraphEdge]:
        """Resolve @Autowired fields and constructor params to INJECTS edges."""
        edges: list[GraphEdge] = []

        for node in graph.nodes.values():
            if node.kind not in (NodeKind.CLASS, NodeKind.INTERFACE):
                continue
            annotations = set(node.properties.get("annotations", []))
            if not (annotations & STEREOTYPE_ANNOTATIONS):
                continue

            # Check @Autowired fields
            for containment_edge in graph.get_edges_from(node.fqn):
                if containment_edge.kind != EdgeKind.CONTAINS:
                    continue
                child = graph.get_node(containment_edge.target_fqn)
                if child is None:
                    continue

                if child.kind == NodeKind.FIELD:
                    child_annotations = set(child.properties.get("annotations", []))
                    if "Autowired" in child_annotations:
                        field_type = child.properties.get("type", "")
                        qualifier = child.properties.get("annotation_args", {}).get("Qualifier")
                        new_edges = self._resolve_type_to_beans(
                            source_fqn=node.fqn,
                            target_type=field_type,
                            qualifier=qualifier,
                            graph=graph,
                            beans=beans,
                        )
                        edges.extend(new_edges)

                elif child.kind == NodeKind.FUNCTION:
                    if child.properties.get("is_constructor"):
                        params = child.properties.get("params", [])
                        for param in params:
                            param_type = param.get("type", "")
                            param_qualifier = None
                            param_annotations = param.get("annotations", [])
                            # Check if param has @Qualifier
                            if isinstance(param_annotations, list):
                                for pa in param_annotations:
                                    if isinstance(pa, dict) and pa.get("name") == "Qualifier":
                                        param_qualifier = pa.get("value")
                            new_edges = self._resolve_type_to_beans(
                                source_fqn=node.fqn,
                                target_type=param_type,
                                qualifier=param_qualifier,
                                graph=graph,
                                beans=beans,
                            )
                            edges.extend(new_edges)

        return edges

    def _resolve_type_to_beans(
        self,
        source_fqn: str,
        target_type: str,
        qualifier: str | None,
        graph: SymbolGraph,
        beans: dict[str, list[_BeanInfo]],
    ) -> list[GraphEdge]:
        """Resolve a type name to bean(s) and create INJECTS edges.

        Resolution order:
        1. Direct match (concrete class is a bean)
        2. Interface -> find implementors that are beans
        3. @Primary disambiguation
        4. @Qualifier disambiguation
        5. Ambiguous -> LOW confidence edges to all candidates
        """
        if not target_type:
            return []

        # Check if direct bean match exists
        candidates = beans.get(target_type, [])

        if len(candidates) == 1:
            return [self._make_inject_edge(
                source_fqn, candidates[0].fqn, Confidence.HIGH, qualifier=qualifier,
            )]

        if len(candidates) > 1:
            return self._disambiguate(source_fqn, candidates, qualifier)

        # No direct match — look for interface implementors
        # Find the interface node
        interface_node = None
        for n in graph.nodes.values():
            if n.name == target_type and n.properties.get("is_interface", False):
                interface_node = n
                break

        if interface_node is None:
            # No interface found — maybe it's a @Bean-provided type
            return []

        # Find all classes that implement this interface AND are beans
        implementors: list[_BeanInfo] = []
        for edge in graph.get_edges_to(interface_node.fqn):
            if edge.kind != EdgeKind.IMPLEMENTS:
                continue
            impl_node = graph.get_node(edge.source_fqn)
            if impl_node is None:
                continue
            impl_annotations = set(impl_node.properties.get("annotations", []))
            if impl_annotations & STEREOTYPE_ANNOTATIONS:
                implementors.append(_BeanInfo(
                    fqn=impl_node.fqn,
                    name=impl_node.name,
                    bean_type=impl_node.name,
                    is_primary="Primary" in impl_annotations,
                ))

        if len(implementors) == 0:
            return []
        if len(implementors) == 1:
            return [self._make_inject_edge(
                source_fqn, implementors[0].fqn, Confidence.HIGH, qualifier=qualifier,
            )]

        return self._disambiguate(source_fqn, implementors, qualifier)

    def _disambiguate(
        self,
        source_fqn: str,
        candidates: list[_BeanInfo],
        qualifier: str | None,
    ) -> list[GraphEdge]:
        """Disambiguate among multiple bean candidates."""
        # Check @Primary
        primary = [c for c in candidates if c.is_primary]
        if len(primary) == 1:
            return [self._make_inject_edge(
                source_fqn, primary[0].fqn, Confidence.HIGH, qualifier=qualifier,
            )]

        # Check @Qualifier
        if qualifier:
            # Match qualifier against bean name (case-insensitive comparison)
            for candidate in candidates:
                # Bean name matches: class name with lowercase first char, or exact match
                bean_name_lower = candidate.name[0].lower() + candidate.name[1:] if candidate.name else ""
                if qualifier == bean_name_lower or qualifier == candidate.name:
                    return [self._make_inject_edge(
                        source_fqn, candidate.fqn, Confidence.HIGH, qualifier=qualifier,
                    )]

        # Ambiguous — LOW confidence to all
        return [
            self._make_inject_edge(source_fqn, c.fqn, Confidence.LOW, qualifier=qualifier)
            for c in candidates
        ]

    def _make_inject_edge(
        self,
        source_fqn: str,
        target_fqn: str,
        confidence: Confidence,
        qualifier: str | None = None,
    ) -> GraphEdge:
        props: dict = {"framework": "spring"}
        if qualifier:
            props["qualifier"] = qualifier
        return GraphEdge(
            source_fqn=source_fqn,
            target_fqn=target_fqn,
            kind=EdgeKind.INJECTS,
            confidence=confidence,
            evidence="spring-di",
            properties=props,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_spring_di_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/spring/__init__.py app/stages/plugins/spring/di.py tests/unit/test_spring_di_plugin.py && git commit -m "feat(plugins): add Spring DI plugin with bean detection, injection resolution, and layer classification"
```

---

## Task 2: Spring Web Plugin (`spring/web.py`)

**Files:**
- Create: `app/stages/plugins/spring/web.py`
- Test: `tests/unit/test_spring_web_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_spring_web_plugin.py
"""Tests for the Spring Web plugin — endpoint extraction, path combining, entry points."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult
from app.stages.plugins.spring.web import SpringWebPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_spring() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="spring-boot",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains spring-boot-starter-web"],
            ),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.CLASS,
        language="java",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
        },
    )
    graph.add_node(node)
    return node


def _add_method(
    graph: SymbolGraph,
    class_fqn: str,
    method_name: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    return_type: str | None = None,
    params: list[dict] | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{method_name}"
    node = GraphNode(
        fqn=fqn,
        name=method_name,
        kind=NodeKind.FUNCTION,
        language="java",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "return_type": return_type,
            "params": params or [],
            "is_constructor": False,
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

class TestSpringWebDetection:
    def test_detect_high_when_spring_present(self):
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_spring(self):
        plugin = SpringWebPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# Endpoint extraction tests
# ---------------------------------------------------------------------------

class TestSpringWebEndpointExtraction:
    @pytest.mark.asyncio
    async def test_get_mapping_simple(self):
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController",
                   annotations=["RestController"])
        _add_method(ctx.graph, "com.example.UserController", "getUsers",
                    annotations=["GetMapping"],
                    annotation_args={"GetMapping": "/users"},
                    return_type="List<User>")

        result = await plugin.extract(ctx)
        # Should create an APIEndpoint node
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["method"] == "GET"
        assert endpoint_nodes[0].properties["path"] == "/users"

        # Should create HANDLES edge (method -> endpoint)
        handles_edges = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        assert len(handles_edges) == 1
        assert handles_edges[0].source_fqn == "com.example.UserController.getUsers"

        # Should create EXPOSES edge (class -> endpoint)
        exposes_edges = [e for e in result.edges if e.kind == EdgeKind.EXPOSES]
        assert len(exposes_edges) == 1
        assert exposes_edges[0].source_fqn == "com.example.UserController"

    @pytest.mark.asyncio
    async def test_class_level_request_mapping_prefix(self):
        """Class-level @RequestMapping prefix is combined with method-level path."""
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController",
                   annotations=["RestController", "RequestMapping"],
                   annotation_args={"RequestMapping": "/api/v1"})
        _add_method(ctx.graph, "com.example.UserController", "getUser",
                    annotations=["GetMapping"],
                    annotation_args={"GetMapping": "/users/{id}"},
                    return_type="User")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["path"] == "/api/v1/users/{id}"

    @pytest.mark.asyncio
    async def test_multiple_http_methods(self):
        """Different HTTP method annotations produce correct method values."""
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController",
                   annotations=["RestController"])
        _add_method(ctx.graph, "com.example.UserController", "createUser",
                    annotations=["PostMapping"],
                    annotation_args={"PostMapping": "/users"},
                    return_type="User")
        _add_method(ctx.graph, "com.example.UserController", "updateUser",
                    annotations=["PutMapping"],
                    annotation_args={"PutMapping": "/users/{id}"})
        _add_method(ctx.graph, "com.example.UserController", "deleteUser",
                    annotations=["DeleteMapping"],
                    annotation_args={"DeleteMapping": "/users/{id}"})
        _add_method(ctx.graph, "com.example.UserController", "patchUser",
                    annotations=["PatchMapping"],
                    annotation_args={"PatchMapping": "/users/{id}"})

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        methods = {n.properties["method"] for n in endpoint_nodes}
        assert methods == {"POST", "PUT", "DELETE", "PATCH"}

    @pytest.mark.asyncio
    async def test_request_mapping_with_method_attribute(self):
        """@RequestMapping(method=GET, path="/users") at method level."""
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController",
                   annotations=["Controller"])
        _add_method(ctx.graph, "com.example.UserController", "listUsers",
                    annotations=["RequestMapping"],
                    annotation_args={"RequestMapping": "/users", "method": "GET"})

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["method"] == "GET"
        assert endpoint_nodes[0].properties["path"] == "/users"

    @pytest.mark.asyncio
    async def test_no_endpoints_for_non_controller(self):
        """Classes without @Controller/@RestController produce no endpoints."""
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserService", "UserService",
                   annotations=["Service"])
        _add_method(ctx.graph, "com.example.UserService", "getUsers",
                    annotations=["GetMapping"],
                    annotation_args={"GetMapping": "/users"})

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 0


# ---------------------------------------------------------------------------
# Entry points tests
# ---------------------------------------------------------------------------

class TestSpringWebEntryPoints:
    @pytest.mark.asyncio
    async def test_endpoints_are_entry_points(self):
        plugin = SpringWebPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController",
                   annotations=["RestController"])
        _add_method(ctx.graph, "com.example.UserController", "getUsers",
                    annotations=["GetMapping"],
                    annotation_args={"GetMapping": "/users"})
        _add_method(ctx.graph, "com.example.UserController", "createUser",
                    annotations=["PostMapping"],
                    annotation_args={"PostMapping": "/users"})

        result = await plugin.extract(ctx)
        assert len(result.entry_points) == 2
        entry_fqns = {ep.fqn for ep in result.entry_points}
        assert "com.example.UserController.getUsers" in entry_fqns
        assert "com.example.UserController.createUser" in entry_fqns
        assert all(ep.kind == "http_endpoint" for ep in result.entry_points)


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestSpringWebMetadata:
    def test_name(self):
        assert SpringWebPlugin().name == "spring-web"

    def test_depends_on(self):
        assert SpringWebPlugin().depends_on == ["spring-di"]

    def test_supported_languages(self):
        assert SpringWebPlugin().supported_languages == {"java"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_spring_web_plugin.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `spring/web.py`**

```python
# app/stages/plugins/spring/web.py
"""Spring Web plugin — REST endpoint extraction.

Finds @Controller/@RestController classes, extracts @GetMapping/@PostMapping/etc.
method annotations, combines class-level @RequestMapping prefix with method paths,
and produces APIEndpoint nodes + HANDLES/EXPOSES edges.

Produces:
- Nodes: (:APIEndpoint {method, path, framework, response_type})
- Edges: (:Function)-[:HANDLES]->(:APIEndpoint)
         (:Class)-[:EXPOSES]->(:APIEndpoint)
- Entry points: each endpoint handler method
"""

from __future__ import annotations

import structlog

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext, EntryPoint
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Annotation name -> HTTP method
_HTTP_METHOD_ANNOTATIONS: dict[str, str] = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}

_CONTROLLER_ANNOTATIONS = frozenset({"Controller", "RestController"})


class SpringWebPlugin(FrameworkPlugin):
    name = "spring-web"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = ["spring-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "spring" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("spring_web_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []

        for class_node in graph.nodes.values():
            if class_node.kind != NodeKind.CLASS:
                continue
            class_annotations = set(class_node.properties.get("annotations", []))
            if not (class_annotations & _CONTROLLER_ANNOTATIONS):
                continue

            # Get class-level @RequestMapping prefix
            class_annotation_args = class_node.properties.get("annotation_args", {})
            class_prefix = class_annotation_args.get("RequestMapping", "")
            # Normalize: strip trailing slash
            class_prefix = class_prefix.rstrip("/")

            # Scan methods in this controller
            for containment_edge in graph.get_edges_from(class_node.fqn):
                if containment_edge.kind != EdgeKind.CONTAINS:
                    continue
                method_node = graph.get_node(containment_edge.target_fqn)
                if method_node is None or method_node.kind != NodeKind.FUNCTION:
                    continue

                method_annotations = set(method_node.properties.get("annotations", []))
                method_annotation_args = method_node.properties.get("annotation_args", {})

                http_method = None
                method_path = ""

                # Check specific HTTP method annotations
                for ann_name, http_verb in _HTTP_METHOD_ANNOTATIONS.items():
                    if ann_name in method_annotations:
                        http_method = http_verb
                        method_path = method_annotation_args.get(ann_name, "")
                        break

                # Check generic @RequestMapping on method
                if http_method is None and "RequestMapping" in method_annotations:
                    method_path = method_annotation_args.get("RequestMapping", "")
                    http_method = method_annotation_args.get("method", "GET").upper()

                if http_method is None:
                    continue

                # Combine paths
                # Normalize method path
                if method_path and not method_path.startswith("/"):
                    method_path = "/" + method_path
                full_path = class_prefix + method_path if method_path else class_prefix
                if not full_path:
                    full_path = "/"

                # Create APIEndpoint node
                endpoint_fqn = f"endpoint:{http_method}:{full_path}"
                response_type = method_node.properties.get("return_type")
                endpoint_node = GraphNode(
                    fqn=endpoint_fqn,
                    name=f"{http_method} {full_path}",
                    kind=NodeKind.API_ENDPOINT,
                    language="java",
                    properties={
                        "method": http_method,
                        "path": full_path,
                        "framework": "spring",
                        "response_type": response_type,
                    },
                )
                nodes.append(endpoint_node)

                # HANDLES edge: method -> endpoint
                edges.append(GraphEdge(
                    source_fqn=method_node.fqn,
                    target_fqn=endpoint_fqn,
                    kind=EdgeKind.HANDLES,
                    confidence=Confidence.HIGH,
                    evidence="spring-web",
                ))

                # EXPOSES edge: class -> endpoint
                edges.append(GraphEdge(
                    source_fqn=class_node.fqn,
                    target_fqn=endpoint_fqn,
                    kind=EdgeKind.EXPOSES,
                    confidence=Confidence.HIGH,
                    evidence="spring-web",
                ))

                # Entry point
                entry_points.append(EntryPoint(
                    fqn=method_node.fqn,
                    kind="http_endpoint",
                    metadata={"method": http_method, "path": full_path},
                ))

        log.info("spring_web_extract_done", endpoints=len(nodes))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=entry_points,
            warnings=[],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_spring_web_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/spring/web.py tests/unit/test_spring_web_plugin.py && git commit -m "feat(plugins): add Spring Web plugin with endpoint extraction and entry point detection"
```

---

## Task 3: Hibernate/JPA Plugin (`hibernate/jpa.py`)

**Files:**
- Create: `app/stages/plugins/hibernate/__init__.py`
- Create: `app/stages/plugins/hibernate/jpa.py`
- Test: `tests/unit/test_hibernate_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_hibernate_plugin.py
"""Tests for the Hibernate/JPA plugin — entity mapping, table/column nodes, FK relationships."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult
from app.stages.plugins.hibernate.jpa import HibernateJPAPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_spring() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="spring-boot",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains spring-boot-starter-data-jpa"],
            ),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.CLASS,
        language="java",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
        },
    )
    graph.add_node(node)
    return node


def _add_field(
    graph: SymbolGraph,
    class_fqn: str,
    field_name: str,
    field_type: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    type_args: list[str] | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{field_name}"
    node = GraphNode(
        fqn=fqn,
        name=field_name,
        kind=NodeKind.FIELD,
        language="java",
        properties={
            "type": field_type,
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "type_args": type_args or [],
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

class TestHibernateDetection:
    def test_detect_high_when_spring_data_jpa_present(self):
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_medium_when_entity_annotations_found(self):
        plugin = HibernateJPAPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM

    def test_detect_none_without_hibernate(self):
        plugin = HibernateJPAPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# Entity-to-table mapping tests
# ---------------------------------------------------------------------------

class TestHibernateEntityMapping:
    @pytest.mark.asyncio
    async def test_entity_creates_table_node(self):
        """@Entity class -> Table node with MAPS_TO edge."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "users"  # camelCase -> snake_case

        maps_to = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
        assert len(maps_to) == 1
        assert maps_to[0].source_fqn == "com.example.User"
        assert maps_to[0].properties.get("orm") == "hibernate"

    @pytest.mark.asyncio
    async def test_entity_with_table_annotation(self):
        """@Table(name="app_users") overrides derived table name."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.User", "User",
                   annotations=["Entity", "Table"],
                   annotation_args={"Table": "app_users"})

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "app_users"

    @pytest.mark.asyncio
    async def test_fields_create_column_nodes(self):
        """Entity fields -> Column nodes with HAS_COLUMN edges."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.User", "email", "String")
        _add_field(ctx.graph, "com.example.User", "firstName", "String")

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        assert len(column_nodes) == 3
        col_names = {n.name for n in column_nodes}
        assert col_names == {"id", "email", "first_name"}  # camelCase -> snake_case

        has_column = [e for e in result.edges if e.kind == EdgeKind.HAS_COLUMN]
        assert len(has_column) == 3

    @pytest.mark.asyncio
    async def test_column_annotation_overrides_name(self):
        """@Column(name="email_address") overrides derived column name."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "email", "String",
                   annotations=["Column"],
                   annotation_args={"Column": "email_address"})

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        assert any(n.name == "email_address" for n in column_nodes)

    @pytest.mark.asyncio
    async def test_id_field_marked_as_primary_key(self):
        """@Id annotation sets is_primary_key on column."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "id", "Long", annotations=["Id"])

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        id_col = [n for n in column_nodes if n.name == "id"][0]
        assert id_col.properties.get("is_primary_key") is True


# ---------------------------------------------------------------------------
# Relationship mapping tests
# ---------------------------------------------------------------------------

class TestHibernateRelationships:
    @pytest.mark.asyncio
    async def test_many_to_one_creates_fk(self):
        """@ManyToOne + @JoinColumn -> REFERENCES edge between columns."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()

        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "id", "Long", annotations=["Id"])

        _add_class(ctx.graph, "com.example.Order", "Order", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.Order", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.Order", "user", "User",
                   annotations=["ManyToOne", "JoinColumn"],
                   annotation_args={"JoinColumn": "user_id"})

        result = await plugin.extract(ctx)
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1
        # The FK column (user_id in orders table) references (id in users table)
        assert "user_id" in ref_edges[0].source_fqn
        assert "id" in ref_edges[0].target_fqn

    @pytest.mark.asyncio
    async def test_one_to_many_with_mapped_by(self):
        """@OneToMany(mappedBy="user") — inverse side, no new FK, but relationship edge."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()

        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.User", "orders", "List",
                   annotations=["OneToMany"],
                   annotation_args={"OneToMany": "user"},  # mappedBy value
                   type_args=["Order"])

        _add_class(ctx.graph, "com.example.Order", "Order", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.Order", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.Order", "user", "User",
                   annotations=["ManyToOne", "JoinColumn"],
                   annotation_args={"JoinColumn": "user_id"})

        result = await plugin.extract(ctx)
        # The FK REFERENCES edge should exist from the ManyToOne side
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) >= 1

    @pytest.mark.asyncio
    async def test_many_to_many_creates_junction_table(self):
        """@ManyToMany + @JoinTable -> junction table node + FK edges."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()

        _add_class(ctx.graph, "com.example.Student", "Student", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.Student", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.Student", "courses", "Set",
                   annotations=["ManyToMany", "JoinTable"],
                   annotation_args={"JoinTable": "student_courses"},
                   type_args=["Course"])

        _add_class(ctx.graph, "com.example.Course", "Course", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.Course", "id", "Long", annotations=["Id"])

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        table_names = {n.name for n in table_nodes}
        # Should have students, courses, and the junction table student_courses
        assert "student_courses" in table_names
        assert "students" in table_names
        assert "courses" in table_names

    @pytest.mark.asyncio
    async def test_one_to_one(self):
        """@OneToOne + @JoinColumn -> unique FK."""
        plugin = HibernateJPAPlugin()
        ctx = _make_context_with_spring()

        _add_class(ctx.graph, "com.example.User", "User", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.User", "id", "Long", annotations=["Id"])

        _add_class(ctx.graph, "com.example.Profile", "Profile", annotations=["Entity"])
        _add_field(ctx.graph, "com.example.Profile", "id", "Long", annotations=["Id"])
        _add_field(ctx.graph, "com.example.Profile", "user", "User",
                   annotations=["OneToOne", "JoinColumn"],
                   annotation_args={"JoinColumn": "user_id"})

        result = await plugin.extract(ctx)
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestHibernateMetadata:
    def test_name(self):
        assert HibernateJPAPlugin().name == "hibernate"

    def test_depends_on(self):
        assert HibernateJPAPlugin().depends_on == ["spring-di"]

    def test_supported_languages(self):
        assert HibernateJPAPlugin().supported_languages == {"java"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_hibernate_plugin.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Create `__init__.py`**

```python
# app/stages/plugins/hibernate/__init__.py
"""Hibernate/JPA plugin — entity-to-table mapping and relationship extraction."""

from app.stages.plugins.hibernate.jpa import HibernateJPAPlugin

__all__ = ["HibernateJPAPlugin"]
```

- [ ] **Step 4: Implement `hibernate/jpa.py`**

```python
# app/stages/plugins/hibernate/jpa.py
"""Hibernate/JPA plugin — entity-to-table mapping, column extraction, FK relationships.

Finds @Entity classes, derives table/column names, and resolves relationship
annotations (@OneToMany, @ManyToOne, @ManyToMany, @OneToOne) into REFERENCES
edges between columns and MAPS_TO edges between entities and tables.

Produces:
- Nodes: (:Table), (:Column)
- Edges: (:Class)-[:MAPS_TO {orm: "hibernate"}]->(:Table)
         (:Table)-[:HAS_COLUMN]->(:Column)
         (:Column)-[:REFERENCES]->(:Column)
"""

from __future__ import annotations

import re
import structlog

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext, EntryPoint
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case: 'firstName' -> 'first_name', 'User' -> 'user'."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1).lower()


def _pluralize(name: str) -> str:
    """Naive pluralization: add 's' (handles common cases)."""
    if name.endswith("s") or name.endswith("x") or name.endswith("z"):
        return name + "es"
    if name.endswith("y") and len(name) > 1 and name[-2] not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def _derive_table_name(class_name: str) -> str:
    """Derive table name from entity class name: 'User' -> 'users', 'OrderItem' -> 'order_items'."""
    return _pluralize(_camel_to_snake(class_name))


class HibernateJPAPlugin(FrameworkPlugin):
    name = "hibernate"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = ["spring-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                name_lower = fw.name.lower()
                if "hibernate" in name_lower or "jpa" in name_lower or "spring" in name_lower:
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: check for @Entity annotations
        for node in context.graph.nodes.values():
            annotations = node.properties.get("annotations", [])
            if "Entity" in annotations:
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="@Entity annotations found in graph",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("hibernate_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []

        # Collect all entities first (needed for cross-entity FK resolution)
        entities: dict[str, _EntityInfo] = {}

        for class_node in graph.nodes.values():
            if class_node.kind != NodeKind.CLASS:
                continue
            annotations = set(class_node.properties.get("annotations", []))
            if "Entity" not in annotations:
                continue

            annotation_args = class_node.properties.get("annotation_args", {})

            # Derive table name
            table_name = annotation_args.get("Table") or _derive_table_name(class_node.name)

            entity_info = _EntityInfo(
                fqn=class_node.fqn,
                name=class_node.name,
                table_name=table_name,
                fields=[],
            )

            # Collect fields
            for containment_edge in graph.get_edges_from(class_node.fqn):
                if containment_edge.kind != EdgeKind.CONTAINS:
                    continue
                field_node = graph.get_node(containment_edge.target_fqn)
                if field_node is None or field_node.kind != NodeKind.FIELD:
                    continue
                field_annotations = set(field_node.properties.get("annotations", []))
                field_annotation_args = field_node.properties.get("annotation_args", {})
                field_type_args = field_node.properties.get("type_args", [])

                # Derive column name
                column_name = field_annotation_args.get("Column") or _camel_to_snake(field_node.name)

                entity_info.fields.append(_FieldInfo(
                    fqn=field_node.fqn,
                    name=field_node.name,
                    field_type=field_node.properties.get("type", ""),
                    column_name=column_name,
                    annotations=field_annotations,
                    annotation_args=field_annotation_args,
                    type_args=field_type_args,
                    is_id="Id" in field_annotations,
                ))

            entities[class_node.name] = entity_info

        # Now create Table/Column nodes and relationship edges
        for entity in entities.values():
            table_fqn = f"table:{entity.table_name}"

            # Create Table node
            table_node = GraphNode(
                fqn=table_fqn,
                name=entity.table_name,
                kind=NodeKind.TABLE,
                properties={"column_count": len(entity.fields)},
            )
            nodes.append(table_node)

            # MAPS_TO edge: entity -> table
            edges.append(GraphEdge(
                source_fqn=entity.fqn,
                target_fqn=table_fqn,
                kind=EdgeKind.MAPS_TO,
                confidence=Confidence.HIGH,
                evidence="hibernate",
                properties={"orm": "hibernate"},
            ))

            # Create Column nodes for non-relationship fields + @Id + @JoinColumn
            for field_info in entity.fields:
                # Skip collection-type relationship fields without @JoinColumn
                is_relationship = bool(
                    field_info.annotations & {"OneToMany", "ManyToMany"}
                    and "JoinColumn" not in field_info.annotations
                    and "JoinTable" not in field_info.annotations
                )
                if is_relationship:
                    continue

                # For @ManyToOne/@OneToOne with @JoinColumn, use the JoinColumn name
                if ("ManyToOne" in field_info.annotations or "OneToOne" in field_info.annotations):
                    if "JoinColumn" in field_info.annotations:
                        col_name = field_info.annotation_args.get("JoinColumn", field_info.column_name)
                    else:
                        col_name = field_info.column_name
                else:
                    col_name = field_info.column_name

                col_fqn = f"{table_fqn}.{col_name}"
                col_node = GraphNode(
                    fqn=col_fqn,
                    name=col_name,
                    kind=NodeKind.COLUMN,
                    properties={
                        "type": field_info.field_type,
                        "is_primary_key": field_info.is_id,
                        "is_foreign_key": bool(
                            field_info.annotations & {"ManyToOne", "OneToOne", "JoinColumn"}
                            - {"Id"}
                        ),
                    },
                )
                nodes.append(col_node)

                # HAS_COLUMN edge: table -> column
                edges.append(GraphEdge(
                    source_fqn=table_fqn,
                    target_fqn=col_fqn,
                    kind=EdgeKind.HAS_COLUMN,
                    confidence=Confidence.HIGH,
                    evidence="hibernate",
                ))

                # REFERENCES edge for FK columns
                if "ManyToOne" in field_info.annotations or "OneToOne" in field_info.annotations:
                    target_entity_name = field_info.field_type
                    target_entity = entities.get(target_entity_name)
                    if target_entity:
                        # Find the PK column of the target entity
                        target_pk = self._find_pk_column(target_entity)
                        if target_pk:
                            target_col_fqn = f"table:{target_entity.table_name}.{target_pk}"
                            edges.append(GraphEdge(
                                source_fqn=col_fqn,
                                target_fqn=target_col_fqn,
                                kind=EdgeKind.REFERENCES,
                                confidence=Confidence.HIGH,
                                evidence="hibernate",
                            ))

            # Handle @ManyToMany with @JoinTable
            for field_info in entity.fields:
                if "ManyToMany" not in field_info.annotations:
                    continue
                if "JoinTable" not in field_info.annotations:
                    continue

                junction_table_name = field_info.annotation_args.get("JoinTable", "")
                if not junction_table_name:
                    continue

                junction_fqn = f"table:{junction_table_name}"
                junction_node = GraphNode(
                    fqn=junction_fqn,
                    name=junction_table_name,
                    kind=NodeKind.TABLE,
                    properties={"is_junction": True},
                )
                nodes.append(junction_node)

                # FK from junction to owning entity
                owning_pk = self._find_pk_column(entity)
                if owning_pk:
                    fk_col_name = f"{_camel_to_snake(entity.name)}_id"
                    fk_col_fqn = f"{junction_fqn}.{fk_col_name}"
                    fk_col_node = GraphNode(
                        fqn=fk_col_fqn, name=fk_col_name, kind=NodeKind.COLUMN,
                        properties={"is_foreign_key": True},
                    )
                    nodes.append(fk_col_node)
                    edges.append(GraphEdge(
                        source_fqn=junction_fqn, target_fqn=fk_col_fqn,
                        kind=EdgeKind.HAS_COLUMN, confidence=Confidence.HIGH, evidence="hibernate",
                    ))
                    edges.append(GraphEdge(
                        source_fqn=fk_col_fqn,
                        target_fqn=f"table:{entity.table_name}.{owning_pk}",
                        kind=EdgeKind.REFERENCES, confidence=Confidence.HIGH, evidence="hibernate",
                    ))

                # FK from junction to target entity
                target_entity_name = field_info.type_args[0] if field_info.type_args else ""
                target_entity = entities.get(target_entity_name)
                if target_entity:
                    target_pk = self._find_pk_column(target_entity)
                    if target_pk:
                        fk_col_name2 = f"{_camel_to_snake(target_entity_name)}_id"
                        fk_col_fqn2 = f"{junction_fqn}.{fk_col_name2}"
                        fk_col_node2 = GraphNode(
                            fqn=fk_col_fqn2, name=fk_col_name2, kind=NodeKind.COLUMN,
                            properties={"is_foreign_key": True},
                        )
                        nodes.append(fk_col_node2)
                        edges.append(GraphEdge(
                            source_fqn=junction_fqn, target_fqn=fk_col_fqn2,
                            kind=EdgeKind.HAS_COLUMN, confidence=Confidence.HIGH, evidence="hibernate",
                        ))
                        edges.append(GraphEdge(
                            source_fqn=fk_col_fqn2,
                            target_fqn=f"table:{target_entity.table_name}.{target_pk}",
                            kind=EdgeKind.REFERENCES, confidence=Confidence.HIGH, evidence="hibernate",
                        ))

        log.info("hibernate_extract_done", entities=len(entities), tables=len([n for n in nodes if n.kind == NodeKind.TABLE]))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=warnings,
        )

    def _find_pk_column(self, entity: _EntityInfo) -> str | None:
        """Find the primary key column name for an entity."""
        for field_info in entity.fields:
            if field_info.is_id:
                return field_info.column_name
        return None


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field as dataclass_field


@dataclass
class _FieldInfo:
    fqn: str
    name: str
    field_type: str
    column_name: str
    annotations: set[str]
    annotation_args: dict[str, str]
    type_args: list[str]
    is_id: bool = False


@dataclass
class _EntityInfo:
    fqn: str
    name: str
    table_name: str
    fields: list[_FieldInfo] = dataclass_field(default_factory=list)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_hibernate_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/hibernate/__init__.py app/stages/plugins/hibernate/jpa.py tests/unit/test_hibernate_plugin.py && git commit -m "feat(plugins): add Hibernate/JPA plugin with entity-table mapping, column extraction, and FK relationships"
```

---

## Task 4: Spring Data Plugin (`spring/data.py`)

**Files:**
- Create: `app/stages/plugins/spring/data.py`
- Test: `tests/unit/test_spring_data_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_spring_data_plugin.py
"""Tests for the Spring Data plugin — repository detection, derived queries, @Query parsing."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult
from app.stages.plugins.spring.data import SpringDataPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_spring() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="spring-boot",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains spring-boot-starter-data-jpa"],
            ),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    annotations: list[str] | None = None,
    is_interface: bool = False,
    implements: list[str] | None = None,
    type_args: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.INTERFACE if is_interface else NodeKind.CLASS,
        language="java",
        properties={
            "annotations": annotations or [],
            "implements": implements or [],
            "is_interface": is_interface,
            "type_args": type_args or [],
        },
    )
    graph.add_node(node)
    return node


def _add_method(
    graph: SymbolGraph,
    class_fqn: str,
    method_name: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    return_type: str | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{method_name}"
    node = GraphNode(
        fqn=fqn,
        name=method_name,
        kind=NodeKind.FUNCTION,
        language="java",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "return_type": return_type,
            "is_constructor": False,
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


def _add_table(graph: SymbolGraph, table_name: str) -> GraphNode:
    """Add a table node (as Hibernate plugin would have produced)."""
    fqn = f"table:{table_name}"
    node = GraphNode(fqn=fqn, name=table_name, kind=NodeKind.TABLE)
    graph.add_node(node)
    return node


def _add_entity_with_table(
    graph: SymbolGraph, entity_fqn: str, entity_name: str, table_name: str
) -> None:
    """Add entity class + table + MAPS_TO edge (simulating Hibernate plugin output)."""
    _add_class(graph, entity_fqn, entity_name, annotations=["Entity"])
    _add_table(graph, table_name)
    graph.add_edge(GraphEdge(
        source_fqn=entity_fqn,
        target_fqn=f"table:{table_name}",
        kind=EdgeKind.MAPS_TO,
        confidence=Confidence.HIGH,
        evidence="hibernate",
        properties={"orm": "hibernate"},
    ))


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestSpringDataDetection:
    def test_detect_high_when_spring_present(self):
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_spring(self):
        plugin = SpringDataPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# Repository detection tests
# ---------------------------------------------------------------------------

class TestSpringDataRepositoryDetection:
    @pytest.mark.asyncio
    async def test_jpa_repository_detected(self):
        """Interface extending JpaRepository<User, Long> -> MANAGES edge to entity."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )

        result = await plugin.extract(ctx)
        manages_edges = [e for e in result.edges if e.kind == EdgeKind.MANAGES]
        assert len(manages_edges) == 1
        assert manages_edges[0].source_fqn == "com.example.UserRepository"
        assert manages_edges[0].target_fqn == "com.example.User"

    @pytest.mark.asyncio
    async def test_crud_repository_detected(self):
        """Interface extending CrudRepository -> MANAGES edge."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.Order", "Order", "orders")
        _add_class(
            ctx.graph, "com.example.OrderRepository", "OrderRepository",
            is_interface=True,
            implements=["CrudRepository"],
            type_args=["Order", "Long"],
        )

        result = await plugin.extract(ctx)
        manages_edges = [e for e in result.edges if e.kind == EdgeKind.MANAGES]
        assert len(manages_edges) == 1


# ---------------------------------------------------------------------------
# Derived query method tests
# ---------------------------------------------------------------------------

class TestSpringDataDerivedQueries:
    @pytest.mark.asyncio
    async def test_find_by_single_field(self):
        """findByEmail -> READS edge to users table with column 'email'."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(ctx.graph, "com.example.UserRepository", "findByEmail",
                    return_type="User")

        result = await plugin.extract(ctx)
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        assert len(reads_edges) >= 1
        reads_to_users = [e for e in reads_edges if "users" in e.target_fqn]
        assert len(reads_to_users) == 1
        assert "email" in reads_to_users[0].properties.get("columns", [])

    @pytest.mark.asyncio
    async def test_find_by_multiple_fields(self):
        """findByEmailAndStatus -> READS with columns ['email', 'status']."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(ctx.graph, "com.example.UserRepository", "findByEmailAndStatus",
                    return_type="List<User>")

        result = await plugin.extract(ctx)
        reads_edges = [e for e in reads_edges if e.kind == EdgeKind.READS]  # noqa: F821 — intentional
        # Fix: filter from result.edges
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        reads_to_users = [e for e in reads_edges if "users" in e.target_fqn]
        assert len(reads_to_users) == 1
        cols = set(reads_to_users[0].properties.get("columns", []))
        assert cols == {"email", "status"}

    @pytest.mark.asyncio
    async def test_count_by_method(self):
        """countByStatus -> READS edge."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(ctx.graph, "com.example.UserRepository", "countByStatus",
                    return_type="Long")

        result = await plugin.extract(ctx)
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        assert len(reads_edges) >= 1

    @pytest.mark.asyncio
    async def test_delete_by_method(self):
        """deleteByEmail -> WRITES edge."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(ctx.graph, "com.example.UserRepository", "deleteByEmail",
                    return_type="void")

        result = await plugin.extract(ctx)
        writes_edges = [e for e in result.edges if e.kind == EdgeKind.WRITES]
        assert len(writes_edges) >= 1


# ---------------------------------------------------------------------------
# @Query annotation tests
# ---------------------------------------------------------------------------

class TestSpringDataQueryAnnotation:
    @pytest.mark.asyncio
    async def test_query_annotation_select(self):
        """@Query("SELECT u FROM User u WHERE u.email = ?1") -> READS users table."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(
            ctx.graph, "com.example.UserRepository", "findActiveUsers",
            annotations=["Query"],
            annotation_args={"Query": "SELECT u FROM User u WHERE u.active = true"},
            return_type="List<User>",
        )

        result = await plugin.extract(ctx)
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        assert len(reads_edges) >= 1

    @pytest.mark.asyncio
    async def test_query_annotation_native_sql(self):
        """@Query with native SQL referencing actual table name."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(
            ctx.graph, "com.example.UserRepository", "findByNativeQuery",
            annotations=["Query"],
            annotation_args={"Query": "SELECT * FROM users WHERE email = ?1"},
            return_type="List<User>",
        )

        result = await plugin.extract(ctx)
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        assert len(reads_edges) >= 1


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestSpringDataMetadata:
    def test_name(self):
        assert SpringDataPlugin().name == "spring-data"

    def test_depends_on(self):
        assert SpringDataPlugin().depends_on == ["spring-di", "hibernate"]

    def test_supported_languages(self):
        assert SpringDataPlugin().supported_languages == {"java"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_spring_data_plugin.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `spring/data.py`**

```python
# app/stages/plugins/spring/data.py
"""Spring Data plugin — repository interface detection and query resolution.

Finds interfaces extending JpaRepository/CrudRepository, resolves the managed
entity type from generics, parses derived query method names (findByEmailAndStatus)
into column references, and parses @Query annotation SQL.

Produces:
- Edges: (:Interface)-[:MANAGES]->(:Class {entity})
         (:Function)-[:READS {columns}]->(:Table)
         (:Function)-[:WRITES {columns}]->(:Table)
"""

from __future__ import annotations

import re
import structlog

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext, EntryPoint
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Spring Data repository base interfaces
_REPO_BASE_INTERFACES = frozenset({
    "JpaRepository", "CrudRepository", "PagingAndSortingRepository",
    "ReactiveCrudRepository", "Repository",
})

# Derived query method prefixes and their access type
_READ_PREFIXES = ("findBy", "getBy", "queryBy", "readBy", "searchBy", "streamBy", "countBy", "existsBy")
_WRITE_PREFIXES = ("deleteBy", "removeBy")

# Keywords that separate field names in derived queries
_QUERY_KEYWORDS = re.compile(
    r"(And|Or|Between|LessThan|GreaterThan|LessThanEqual|GreaterThanEqual|"
    r"After|Before|IsNull|IsNotNull|NotNull|Like|NotLike|StartingWith|"
    r"EndingWith|Containing|OrderBy|Not|In|NotIn|True|False|"
    r"IgnoreCase|AllIgnoreCase|Top\d*|First\d*|Distinct)"
)


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1).lower()


def _parse_derived_query_fields(method_name: str) -> tuple[str, list[str]]:
    """Parse a Spring Data derived query method name into (access_type, [field_names]).

    Examples:
        findByEmail -> ("read", ["email"])
        findByEmailAndStatus -> ("read", ["email", "status"])
        deleteByEmail -> ("write", ["email"])
        countByStatus -> ("read", ["status"])

    Returns ("unknown", []) if the method name doesn't match a known pattern.
    """
    access_type = "unknown"
    remaining = ""

    for prefix in _READ_PREFIXES:
        if method_name.startswith(prefix):
            access_type = "read"
            remaining = method_name[len(prefix):]
            break

    if access_type == "unknown":
        for prefix in _WRITE_PREFIXES:
            if method_name.startswith(prefix):
                access_type = "write"
                remaining = method_name[len(prefix):]
                break

    if access_type == "unknown" or not remaining:
        return access_type, []

    # Remove OrderBy clause
    order_by_idx = remaining.find("OrderBy")
    if order_by_idx >= 0:
        remaining = remaining[:order_by_idx]

    # Split on keywords to extract field names
    # First, split by And/Or which are the main separators
    parts = re.split(r"(?:And|Or)", remaining)

    fields = []
    for part in parts:
        if not part:
            continue
        # Remove trailing condition keywords
        clean = _QUERY_KEYWORDS.sub("", part).strip()
        if clean:
            # Convert PascalCase field name to snake_case column name
            fields.append(_camel_to_snake(clean))

    return access_type, fields


def _extract_table_refs_from_query(query_str: str, entity_to_table: dict[str, str]) -> tuple[set[str], set[str]]:
    """Extract table references from a @Query string (JPQL or native SQL).

    Returns (tables_read, tables_written).
    For JPQL, entity names are mapped to table names.
    For native SQL, table names are used directly.
    """
    tables_read: set[str] = set()
    tables_written: set[str] = set()

    query_upper = query_str.upper().strip()

    # Try to detect if it's a SELECT, INSERT, UPDATE, DELETE
    if query_upper.startswith("SELECT") or query_upper.startswith("FROM"):
        # Extract FROM and JOIN clauses
        # JPQL: FROM User u -> entity name "User"
        # Native: FROM users u -> table name "users"
        from_matches = re.findall(r'\bFROM\s+(\w+)', query_str, re.IGNORECASE)
        join_matches = re.findall(r'\bJOIN\s+(\w+)', query_str, re.IGNORECASE)
        for name in from_matches + join_matches:
            # Check if it's an entity name
            if name in entity_to_table:
                tables_read.add(entity_to_table[name])
            else:
                # Might be a raw table name
                tables_read.add(name)

    elif query_upper.startswith("UPDATE"):
        update_match = re.search(r'\bUPDATE\s+(\w+)', query_str, re.IGNORECASE)
        if update_match:
            name = update_match.group(1)
            if name in entity_to_table:
                tables_written.add(entity_to_table[name])
            else:
                tables_written.add(name)

    elif query_upper.startswith("DELETE"):
        delete_match = re.search(r'\bFROM\s+(\w+)', query_str, re.IGNORECASE)
        if delete_match:
            name = delete_match.group(1)
            if name in entity_to_table:
                tables_written.add(entity_to_table[name])
            else:
                tables_written.add(name)

    elif query_upper.startswith("INSERT"):
        insert_match = re.search(r'\bINTO\s+(\w+)', query_str, re.IGNORECASE)
        if insert_match:
            name = insert_match.group(1)
            if name in entity_to_table:
                tables_written.add(entity_to_table[name])
            else:
                tables_written.add(name)

    return tables_read, tables_written


class SpringDataPlugin(FrameworkPlugin):
    name = "spring-data"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = ["spring-di", "hibernate"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "spring" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("spring_data_extract_start")

        graph = context.graph
        edges: list[GraphEdge] = []
        warnings: list[str] = []

        # Build entity name -> table FQN mapping from MAPS_TO edges (produced by Hibernate plugin)
        entity_to_table: dict[str, str] = {}  # entity class name -> table FQN
        entity_name_to_table_name: dict[str, str] = {}  # entity class name -> table name
        for edge in graph.edges:
            if edge.kind == EdgeKind.MAPS_TO:
                entity_node = graph.get_node(edge.source_fqn)
                table_node = graph.get_node(edge.target_fqn)
                if entity_node and table_node:
                    entity_to_table[entity_node.name] = edge.target_fqn
                    entity_name_to_table_name[entity_node.name] = table_node.name

        # Find repository interfaces
        for node in graph.nodes.values():
            if not node.properties.get("is_interface", False):
                continue
            implements = set(node.properties.get("implements", []))
            if not (implements & _REPO_BASE_INTERFACES):
                continue

            type_args = node.properties.get("type_args", [])
            if not type_args:
                continue

            entity_name = type_args[0]

            # MANAGES edge: repository -> entity
            entity_fqn = self._find_entity_fqn(graph, entity_name)
            if entity_fqn:
                edges.append(GraphEdge(
                    source_fqn=node.fqn,
                    target_fqn=entity_fqn,
                    kind=EdgeKind.MANAGES,
                    confidence=Confidence.HIGH,
                    evidence="spring-data",
                ))

            # Get the table FQN for this entity
            table_fqn = entity_to_table.get(entity_name)
            if not table_fqn:
                warnings.append(f"No table mapping found for entity '{entity_name}' in repo '{node.fqn}'")
                continue

            # Process methods
            for containment_edge in graph.get_edges_from(node.fqn):
                if containment_edge.kind != EdgeKind.CONTAINS:
                    continue
                method = graph.get_node(containment_edge.target_fqn)
                if method is None or method.kind != NodeKind.FUNCTION:
                    continue

                method_annotations = set(method.properties.get("annotations", []))
                method_annotation_args = method.properties.get("annotation_args", {})

                # Check @Query annotation first
                if "Query" in method_annotations:
                    query_str = method_annotation_args.get("Query", "")
                    if query_str:
                        reads, writes = _extract_table_refs_from_query(
                            query_str, entity_name_to_table_name
                        )
                        for table_name in reads:
                            t_fqn = f"table:{table_name}"
                            if graph.get_node(t_fqn) or t_fqn == table_fqn:
                                edges.append(GraphEdge(
                                    source_fqn=method.fqn,
                                    target_fqn=t_fqn,
                                    kind=EdgeKind.READS,
                                    confidence=Confidence.HIGH,
                                    evidence="spring-data",
                                    properties={"query_type": "SELECT"},
                                ))
                        for table_name in writes:
                            t_fqn = f"table:{table_name}"
                            edges.append(GraphEdge(
                                source_fqn=method.fqn,
                                target_fqn=t_fqn,
                                kind=EdgeKind.WRITES,
                                confidence=Confidence.HIGH,
                                evidence="spring-data",
                                properties={"query_type": "MODIFY"},
                            ))
                    continue

                # Parse derived query method name
                access_type, columns = _parse_derived_query_fields(method.name)
                if access_type == "read":
                    edges.append(GraphEdge(
                        source_fqn=method.fqn,
                        target_fqn=table_fqn,
                        kind=EdgeKind.READS,
                        confidence=Confidence.HIGH,
                        evidence="spring-data",
                        properties={
                            "query_type": "FIND",
                            "columns": columns,
                        },
                    ))
                elif access_type == "write":
                    edges.append(GraphEdge(
                        source_fqn=method.fqn,
                        target_fqn=table_fqn,
                        kind=EdgeKind.WRITES,
                        confidence=Confidence.HIGH,
                        evidence="spring-data",
                        properties={
                            "query_type": "DELETE",
                            "columns": columns,
                        },
                    ))

        log.info("spring_data_extract_done", edges=len(edges))

        return PluginResult(
            nodes=[],
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=warnings,
        )

    def _find_entity_fqn(self, graph: SymbolGraph, entity_name: str) -> str | None:
        """Find the FQN of an entity class by its simple name."""
        for node in graph.nodes.values():
            if node.kind == NodeKind.CLASS and node.name == entity_name:
                annotations = node.properties.get("annotations", [])
                if "Entity" in annotations:
                    return node.fqn
        return None
```

- [ ] **Step 4: Fix test bug and run**

Note: The test `test_find_by_multiple_fields` has a deliberate bug (referencing `reads_edges` before assignment). Fix it:

```python
    @pytest.mark.asyncio
    async def test_find_by_multiple_fields(self):
        """findByEmailAndStatus -> READS with columns ['email', 'status']."""
        plugin = SpringDataPlugin()
        ctx = _make_context_with_spring()
        _add_entity_with_table(ctx.graph, "com.example.User", "User", "users")
        _add_class(
            ctx.graph, "com.example.UserRepository", "UserRepository",
            is_interface=True,
            implements=["JpaRepository"],
            type_args=["User", "Long"],
        )
        _add_method(ctx.graph, "com.example.UserRepository", "findByEmailAndStatus",
                    return_type="List<User>")

        result = await plugin.extract(ctx)
        reads_edges = [e for e in result.edges if e.kind == EdgeKind.READS]
        reads_to_users = [e for e in reads_edges if "users" in e.target_fqn]
        assert len(reads_to_users) == 1
        cols = set(reads_to_users[0].properties.get("columns", []))
        assert cols == {"email", "status"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_spring_data_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/spring/data.py tests/unit/test_spring_data_plugin.py && git commit -m "feat(plugins): add Spring Data plugin with repository detection, derived query parsing, and @Query resolution"
```

---

## Task 5: Update `__init__.py` files and verify full suite

- [ ] **Step 1: Finalize `spring/__init__.py`**

Ensure all three Spring plugins are importable:

```python
# app/stages/plugins/spring/__init__.py
"""Spring framework plugins — DI, Web, Data."""

from app.stages.plugins.spring.di import SpringDIPlugin
from app.stages.plugins.spring.web import SpringWebPlugin
from app.stages.plugins.spring.data import SpringDataPlugin

__all__ = ["SpringDIPlugin", "SpringWebPlugin", "SpringDataPlugin"]
```

- [ ] **Step 2: Run the full test suite**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_spring_di_plugin.py tests/unit/test_spring_web_plugin.py tests/unit/test_spring_data_plugin.py tests/unit/test_hibernate_plugin.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit init files**

```bash
cd cast-clone-backend && git add app/stages/plugins/spring/__init__.py app/stages/plugins/hibernate/__init__.py && git commit -m "feat(plugins): finalize spring and hibernate plugin package init files"
```

---

## Summary of Produced Graph Artifacts

| Plugin | Nodes Created | Edges Created |
|--------|--------------|---------------|
| `spring-di` | (none) | `INJECTS` (Class->Class) |
| `spring-web` | `APIEndpoint` | `HANDLES` (Function->APIEndpoint), `EXPOSES` (Class->APIEndpoint) |
| `hibernate` | `Table`, `Column` | `MAPS_TO` (Class->Table), `HAS_COLUMN` (Table->Column), `REFERENCES` (Column->Column) |
| `spring-data` | (none) | `MANAGES` (Interface->Class), `READS` (Function->Table), `WRITES` (Function->Table) |

## Dependency Chain

```
spring-di (no deps)
    ├── spring-web (depends on spring-di)
    └── hibernate (depends on spring-di)
            └── spring-data (depends on spring-di, hibernate)
```

The plugin registry (M6a) topologically sorts these so `spring-di` runs first, then `spring-web` and `hibernate` can run concurrently, then `spring-data` runs last.
