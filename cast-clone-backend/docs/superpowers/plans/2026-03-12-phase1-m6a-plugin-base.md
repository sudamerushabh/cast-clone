# M6a: Framework Plugin Base Class & Registry Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the plugin base class (ABC), result types, and registry system that discovers, detects, orders, and executes framework plugins. This is the foundation that all Tier 1/2/4 plugins (Spring, Hibernate, React, Express, etc.) will extend.

**Architecture:** `FrameworkPlugin` ABC defines the contract (detect, extract, layer classification, entry points). `PluginResult` is a dataclass carrying nodes/edges/layer assignments/entry points/warnings. The registry auto-discovers plugin subclasses, runs detection, topologically sorts by `depends_on`, executes in dependency order (independent plugins concurrently via `asyncio.gather`), and merges results into `AnalysisContext`. Failed plugins skip their dependents with logged warnings.

**Tech Stack:** Python 3.12, dataclasses, abc, asyncio, structlog, pytest+pytest-asyncio

**Dependencies:** M1 (AnalysisContext, SymbolGraph, GraphNode, GraphEdge, Confidence, EntryPoint)

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       └── plugins/
│           ├── __init__.py              # CREATE — re-export key types
│           ├── base.py                  # CREATE — FrameworkPlugin ABC, PluginResult, LayerRules, LayerRule
│           └── registry.py              # CREATE — register_plugin, _detect_plugins, _topological_sort, run_framework_plugins
├── tests/
│   └── unit/
│       ├── test_plugin_base.py          # CREATE — PluginResult, LayerRules, FrameworkPlugin contract tests
│       └── test_plugin_registry.py      # CREATE — discovery, detection, topo sort, execution, error handling
```

---

## Task 1: Plugin Base Class & Result Types (`base.py`)

**Files:**
- Create: `app/stages/plugins/__init__.py`
- Create: `app/stages/plugins/base.py`
- Test: `tests/unit/test_plugin_base.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_plugin_base.py
import pytest
from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, EntryPoint
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginResult,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
)


# ---------------------------------------------------------------------------
# PluginResult tests
# ---------------------------------------------------------------------------

class TestPluginResult:
    def test_empty_result(self):
        result = PluginResult.empty()
        assert result.nodes == []
        assert result.edges == []
        assert result.layer_assignments == {}
        assert result.entry_points == []
        assert result.warnings == []

    def test_result_with_nodes_and_edges(self):
        node = GraphNode(fqn="com.example.Foo", name="Foo", kind=NodeKind.CLASS)
        edge = GraphEdge(
            source_fqn="com.example.Foo",
            target_fqn="com.example.Bar",
            kind=EdgeKind.INJECTS,
            confidence=Confidence.HIGH,
            evidence="spring-di",
        )
        result = PluginResult(
            nodes=[node],
            edges=[edge],
            layer_assignments={"com.example.Foo": "Presentation"},
            entry_points=[],
            warnings=["Some warning"],
        )
        assert len(result.nodes) == 1
        assert len(result.edges) == 1
        assert result.layer_assignments["com.example.Foo"] == "Presentation"
        assert result.warnings == ["Some warning"]

    def test_result_node_count_and_edge_count(self):
        result = PluginResult(
            nodes=[
                GraphNode(fqn="a", name="a", kind=NodeKind.CLASS),
                GraphNode(fqn="b", name="b", kind=NodeKind.CLASS),
            ],
            edges=[
                GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS),
            ],
            layer_assignments={},
            entry_points=[],
            warnings=[],
        )
        assert result.node_count == 2
        assert result.edge_count == 1

    def test_merge_results(self):
        r1 = PluginResult(
            nodes=[GraphNode(fqn="a", name="a", kind=NodeKind.CLASS)],
            edges=[GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS)],
            layer_assignments={"a": "Presentation"},
            entry_points=[
                EntryPoint(fqn="a.handle", kind="http_endpoint", metadata={"method": "GET"}),
            ],
            warnings=["warn1"],
        )
        r2 = PluginResult(
            nodes=[GraphNode(fqn="c", name="c", kind=NodeKind.CLASS)],
            edges=[GraphEdge(source_fqn="c", target_fqn="d", kind=EdgeKind.INJECTS)],
            layer_assignments={"c": "Business Logic"},
            entry_points=[],
            warnings=["warn2"],
        )
        merged = PluginResult.merge([r1, r2])
        assert merged.node_count == 2
        assert merged.edge_count == 2
        assert merged.layer_assignments == {"a": "Presentation", "c": "Business Logic"}
        assert merged.warnings == ["warn1", "warn2"]
        assert len(merged.entry_points) == 1


# ---------------------------------------------------------------------------
# LayerRules tests
# ---------------------------------------------------------------------------

class TestLayerRules:
    def test_empty_rules(self):
        rules = LayerRules.empty()
        assert rules.rules == []

    def test_rules_with_entries(self):
        rules = LayerRules(rules=[
            LayerRule(pattern="@RestController", layer="Presentation"),
            LayerRule(pattern="@Service", layer="Business Logic"),
            LayerRule(pattern="@Repository", layer="Data Access"),
        ])
        assert len(rules.rules) == 3
        assert rules.rules[0].layer == "Presentation"

    def test_layer_rule_fields(self):
        rule = LayerRule(pattern="@Controller", layer="Presentation")
        assert rule.pattern == "@Controller"
        assert rule.layer == "Presentation"

    def test_classify_fqn_matches_first_rule(self):
        rules = LayerRules(rules=[
            LayerRule(pattern="Controller", layer="Presentation"),
            LayerRule(pattern="Service", layer="Business Logic"),
        ])
        # classify checks if pattern appears in the fqn
        assert rules.classify("com.example.UserController") == "Presentation"
        assert rules.classify("com.example.UserService") == "Business Logic"
        assert rules.classify("com.example.SomeUtil") is None


# ---------------------------------------------------------------------------
# PluginDetectionResult tests
# ---------------------------------------------------------------------------

class TestPluginDetectionResult:
    def test_detection_result_fields(self):
        result = PluginDetectionResult(confidence=Confidence.HIGH, reason="pom.xml contains spring-boot")
        assert result.confidence == Confidence.HIGH
        assert result.reason == "pom.xml contains spring-boot"

    def test_detection_none_confidence(self):
        result = PluginDetectionResult.not_detected()
        assert result.confidence is None
        assert result.reason == "not detected"

    def test_is_active_for_high(self):
        result = PluginDetectionResult(confidence=Confidence.HIGH, reason="found")
        assert result.is_active is True

    def test_is_active_for_medium(self):
        result = PluginDetectionResult(confidence=Confidence.MEDIUM, reason="found")
        assert result.is_active is True

    def test_is_active_for_low(self):
        result = PluginDetectionResult(confidence=Confidence.LOW, reason="heuristic")
        assert result.is_active is False

    def test_is_active_for_none(self):
        result = PluginDetectionResult.not_detected()
        assert result.is_active is False


# ---------------------------------------------------------------------------
# FrameworkPlugin ABC contract tests
# ---------------------------------------------------------------------------

class _MockPlugin(FrameworkPlugin):
    """Concrete test implementation of the ABC."""
    name = "mock-plugin"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

    async def extract(self, context: AnalysisContext) -> PluginResult:
        return PluginResult.empty()


class _IncompletePlugin(FrameworkPlugin):
    """Missing required abstract methods — cannot be instantiated."""
    name = "incomplete"
    version = "0.0.1"
    supported_languages = {"python"}


class TestFrameworkPluginContract:
    def test_concrete_plugin_instantiates(self):
        plugin = _MockPlugin()
        assert plugin.name == "mock-plugin"
        assert plugin.version == "1.0.0"
        assert plugin.supported_languages == {"java"}
        assert plugin.depends_on == []

    def test_abstract_methods_enforced(self):
        with pytest.raises(TypeError):
            _IncompletePlugin()  # type: ignore[abstract]

    def test_default_layer_classification_is_empty(self):
        plugin = _MockPlugin()
        rules = plugin.get_layer_classification()
        assert rules.rules == []

    def test_default_entry_points_is_empty(self):
        plugin = _MockPlugin()
        entry_points = plugin.get_entry_points(None)  # type: ignore[arg-type]
        assert entry_points == []

    def test_plugin_repr(self):
        plugin = _MockPlugin()
        assert "mock-plugin" in repr(plugin)
        assert "1.0.0" in repr(plugin)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_base.py -v`
Expected: FAIL (ImportError — `app.stages.plugins.base` doesn't exist)

- [ ] **Step 3: Create `__init__.py` files**

```python
# app/stages/__init__.py
```

```python
# app/stages/plugins/__init__.py
"""Framework plugin system for extracting invisible connections from code.

Plugins detect framework usage, extract hidden relationships (DI wiring,
ORM mappings, endpoint routes), and produce new graph nodes and edges.
"""

from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

__all__ = [
    "FrameworkPlugin",
    "LayerRule",
    "LayerRules",
    "PluginDetectionResult",
    "PluginResult",
]
```

- [ ] **Step 4: Implement `base.py`**

```python
# app/stages/plugins/base.py
"""Framework plugin base class and result types.

Every framework plugin (Spring, Hibernate, React, Express, etc.) extends
FrameworkPlugin and implements detect() + extract(). The registry discovers,
detects, orders, and executes plugins automatically.

Internal models use dataclasses (not Pydantic) for performance — plugins
create many nodes/edges during extraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import Confidence
from app.models.graph import GraphEdge, GraphNode
from app.models.manifest import EntryPoint


# ---------------------------------------------------------------------------
# Layer classification
# ---------------------------------------------------------------------------

@dataclass
class LayerRule:
    """Maps a pattern (annotation name, class suffix) to an architectural layer.

    The pattern is matched as a substring of the node's FQN. For annotation-based
    patterns, include the annotation marker (e.g., "@RestController").
    """

    pattern: str
    layer: str  # "Presentation", "Business Logic", "Data Access", "Configuration"


@dataclass
class LayerRules:
    """A collection of layer classification rules from a plugin.

    Rules are evaluated in order; the first match wins.
    """

    rules: list[LayerRule] = field(default_factory=list)

    @classmethod
    def empty(cls) -> LayerRules:
        """Return an empty rule set (default for plugins that don't classify layers)."""
        return cls(rules=[])

    def classify(self, fqn: str) -> str | None:
        """Return the layer name for a given FQN, or None if no rule matches.

        Matches are substring-based: if the pattern appears anywhere in the FQN,
        the rule applies. First matching rule wins.
        """
        for rule in self.rules:
            if rule.pattern in fqn:
                return rule.layer
        return None


# ---------------------------------------------------------------------------
# Detection result
# ---------------------------------------------------------------------------

@dataclass
class PluginDetectionResult:
    """Result of plugin.detect() — whether the plugin is relevant to the project.

    confidence=None means the framework was not detected at all.
    HIGH and MEDIUM auto-activate. LOW does not activate (logged as info).
    """

    confidence: Confidence | None
    reason: str

    @classmethod
    def not_detected(cls) -> PluginDetectionResult:
        """Convenience: the framework is not present in this project."""
        return cls(confidence=None, reason="not detected")

    @property
    def is_active(self) -> bool:
        """Whether this detection result means the plugin should run.

        Only HIGH and MEDIUM confidence activate a plugin.
        """
        if self.confidence is None:
            return False
        return self.confidence >= Confidence.MEDIUM


# ---------------------------------------------------------------------------
# Plugin result
# ---------------------------------------------------------------------------

@dataclass
class PluginResult:
    """Output of plugin.extract() — new nodes, edges, and metadata to merge.

    Each plugin produces its own PluginResult. The registry merges all results
    into the shared AnalysisContext after execution.
    """

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    layer_assignments: dict[str, str]  # fqn -> layer name
    entry_points: list[EntryPoint]
    warnings: list[str]

    @classmethod
    def empty(cls) -> PluginResult:
        """Convenience: an empty result with no nodes, edges, or metadata."""
        return cls(nodes=[], edges=[], layer_assignments={}, entry_points=[], warnings=[])

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @classmethod
    def merge(cls, results: list[PluginResult]) -> PluginResult:
        """Merge multiple plugin results into a single combined result.

        Layer assignments are merged with later results overwriting earlier ones
        for the same FQN. All other fields are concatenated.
        """
        merged_nodes: list[GraphNode] = []
        merged_edges: list[GraphEdge] = []
        merged_layers: dict[str, str] = {}
        merged_entry_points: list[EntryPoint] = []
        merged_warnings: list[str] = []
        for r in results:
            merged_nodes.extend(r.nodes)
            merged_edges.extend(r.edges)
            merged_layers.update(r.layer_assignments)
            merged_entry_points.extend(r.entry_points)
            merged_warnings.extend(r.warnings)
        return cls(
            nodes=merged_nodes,
            edges=merged_edges,
            layer_assignments=merged_layers,
            entry_points=merged_entry_points,
            warnings=merged_warnings,
        )


# ---------------------------------------------------------------------------
# Plugin ABC
# ---------------------------------------------------------------------------

class FrameworkPlugin(ABC):
    """Abstract base class for all framework plugins.

    Subclasses MUST define the class attributes (name, version,
    supported_languages) and implement detect() + extract().

    Lifecycle:
        1. detect(context)  — Is this framework present? Returns PluginDetectionResult.
        2. extract(context) — Parse code, produce nodes/edges. Only called if detect()
                              returned HIGH or MEDIUM confidence.
        3. get_layer_classification() — Optional: how to classify nodes into layers.
        4. get_entry_points(context) — Optional: transaction starting points.
    """

    # --- Class attributes: subclasses MUST set these ---
    name: str
    version: str
    supported_languages: set[str]
    depends_on: list[str] = []

    @abstractmethod
    def detect(self, context: Any) -> PluginDetectionResult:
        """Determine if this framework is present in the project.

        Args:
            context: The AnalysisContext for the current project.

        Returns:
            PluginDetectionResult with confidence and reason.
            HIGH: strong evidence (build file declares dependency).
            MEDIUM: moderate evidence (annotations found in code).
            LOW: weak heuristic (not auto-activated).
            None confidence: not detected at all.
        """
        ...

    @abstractmethod
    async def extract(self, context: Any) -> PluginResult:
        """Extract hidden connections from the codebase.

        This is the core work of each plugin. It reads the parsed AST from
        context.graph, applies framework-specific logic, and returns new
        nodes and edges that represent invisible connections.

        Args:
            context: The AnalysisContext for the current project.

        Returns:
            PluginResult with discovered nodes, edges, layer assignments,
            entry points, and warnings.
        """
        ...

    def get_layer_classification(self) -> LayerRules:
        """Return rules for classifying nodes into architectural layers.

        Override this to provide framework-specific layer rules. For example,
        Spring plugins map @Controller -> Presentation, @Service -> Business Logic.

        Default returns empty rules (no layer classification).
        """
        return LayerRules.empty()

    def get_entry_points(self, context: Any) -> list[EntryPoint]:
        """Return transaction starting points discovered by this plugin.

        Override this to identify entry points like HTTP endpoints, message
        consumers, or scheduled tasks that begin transaction flows.

        Default returns an empty list.
        """
        return []

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, version={self.version!r})"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_base.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Lint**

Run: `cd cast-clone-backend && uv run ruff check app/stages/plugins/ tests/unit/test_plugin_base.py && uv run ruff format --check app/stages/plugins/ tests/unit/test_plugin_base.py`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
cd cast-clone-backend && git add app/stages/__init__.py app/stages/plugins/__init__.py app/stages/plugins/base.py tests/unit/test_plugin_base.py && git commit -m "feat(plugins): add FrameworkPlugin ABC, PluginResult, LayerRules, and PluginDetectionResult"
```

---

## Task 2: Plugin Registry (`registry.py`)

**Files:**
- Create: `app/stages/plugins/registry.py`
- Test: `tests/unit/test_plugin_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_plugin_registry.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass, field

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.manifest import EntryPoint
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
    LayerRules,
    LayerRule,
)
from app.stages.plugins.registry import (
    PluginRegistry,
    _topological_sort,
    _detect_plugins,
    run_framework_plugins,
)


# ---------------------------------------------------------------------------
# Helpers: Mock plugins
# ---------------------------------------------------------------------------

class HighConfidencePlugin(FrameworkPlugin):
    name = "high-plugin"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = []

    def detect(self, context):
        return PluginDetectionResult(confidence=Confidence.HIGH, reason="build file found")

    async def extract(self, context) -> PluginResult:
        return PluginResult(
            nodes=[GraphNode(fqn="high.Node", name="Node", kind=NodeKind.CLASS, language="java")],
            edges=[GraphEdge(source_fqn="high.Node", target_fqn="high.Other", kind=EdgeKind.INJECTS, evidence="high-plugin")],
            layer_assignments={"high.Node": "Business Logic"},
            entry_points=[],
            warnings=[],
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[LayerRule(pattern="Controller", layer="Presentation")])


class MediumConfidencePlugin(FrameworkPlugin):
    name = "medium-plugin"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = []

    def detect(self, context):
        return PluginDetectionResult(confidence=Confidence.MEDIUM, reason="annotations found")

    async def extract(self, context) -> PluginResult:
        return PluginResult(
            nodes=[GraphNode(fqn="med.Node", name="Node", kind=NodeKind.CLASS, language="java")],
            edges=[],
            layer_assignments={},
            entry_points=[],
            warnings=["Medium confidence — results may be incomplete"],
        )


class LowConfidencePlugin(FrameworkPlugin):
    name = "low-plugin"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = []

    def detect(self, context):
        return PluginDetectionResult(confidence=Confidence.LOW, reason="heuristic only")

    async def extract(self, context) -> PluginResult:
        raise AssertionError("Should never be called — LOW confidence plugins are skipped")


class NotDetectedPlugin(FrameworkPlugin):
    name = "absent-plugin"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context):
        return PluginDetectionResult.not_detected()

    async def extract(self, context) -> PluginResult:
        raise AssertionError("Should never be called — not detected")


class DependentPluginB(FrameworkPlugin):
    """Depends on DependentPluginA."""
    name = "plugin-b"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on = ["plugin-a"]

    def detect(self, context):
        return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

    async def extract(self, context) -> PluginResult:
        return PluginResult(
            nodes=[GraphNode(fqn="b.Node", name="Node", kind=NodeKind.CLASS)],
            edges=[],
            layer_assignments={},
            entry_points=[],
            warnings=[],
        )


class DependentPluginA(FrameworkPlugin):
    """No dependencies — should run before B."""
    name = "plugin-a"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = []

    def detect(self, context):
        return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

    async def extract(self, context) -> PluginResult:
        return PluginResult(
            nodes=[GraphNode(fqn="a.Node", name="Node", kind=NodeKind.CLASS)],
            edges=[],
            layer_assignments={},
            entry_points=[],
            warnings=[],
        )


class DependentPluginC(FrameworkPlugin):
    """Depends on both A and B."""
    name = "plugin-c"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on = ["plugin-a", "plugin-b"]

    def detect(self, context):
        return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

    async def extract(self, context) -> PluginResult:
        return PluginResult.empty()


class FailingPlugin(FrameworkPlugin):
    name = "failing-plugin"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = []

    def detect(self, context):
        return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

    async def extract(self, context) -> PluginResult:
        raise RuntimeError("Plugin crashed!")


class DependsOnFailingPlugin(FrameworkPlugin):
    name = "depends-on-failing"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on = ["failing-plugin"]

    def detect(self, context):
        return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

    async def extract(self, context) -> PluginResult:
        raise AssertionError("Should be skipped because dependency failed")


class TrackingPlugin(FrameworkPlugin):
    """Records the order it was called for concurrency testing."""
    name = "tracking"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = []
    execution_log: list[str] = []  # class-level shared log

    def detect(self, context):
        return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

    async def extract(self, context) -> PluginResult:
        TrackingPlugin.execution_log.append(self.name)
        return PluginResult.empty()


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestPluginRegistry:
    def test_register_and_list_plugins(self):
        registry = PluginRegistry()
        registry.register(HighConfidencePlugin)
        registry.register(MediumConfidencePlugin)
        assert len(registry.plugin_classes) == 2

    def test_register_duplicate_warns(self):
        registry = PluginRegistry()
        registry.register(HighConfidencePlugin)
        registry.register(HighConfidencePlugin)
        # Second registration replaces the first, not duplicated
        assert len(registry.plugin_classes) == 1

    def test_register_decorator(self):
        registry = PluginRegistry()

        @registry.register
        class SomePlugin(FrameworkPlugin):
            name = "decorated"
            version = "1.0.0"
            supported_languages = {"java"}
            depends_on: list[str] = []

            def detect(self, context):
                return PluginDetectionResult.not_detected()

            async def extract(self, context):
                return PluginResult.empty()

        assert len(registry.plugin_classes) == 1
        assert registry.plugin_classes[0] is SomePlugin

    def test_instantiate_plugins(self):
        registry = PluginRegistry()
        registry.register(HighConfidencePlugin)
        plugins = registry.instantiate()
        assert len(plugins) == 1
        assert isinstance(plugins[0], HighConfidencePlugin)


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestDetectPlugins:
    def test_high_and_medium_are_active(self):
        plugins = [HighConfidencePlugin(), MediumConfidencePlugin(), LowConfidencePlugin(), NotDetectedPlugin()]
        context = MagicMock()  # AnalysisContext mock
        active = _detect_plugins(context, plugins)
        names = {p.name for p in active}
        assert names == {"high-plugin", "medium-plugin"}

    def test_low_confidence_excluded(self):
        plugins = [LowConfidencePlugin()]
        context = MagicMock()
        active = _detect_plugins(context, plugins)
        assert active == []

    def test_not_detected_excluded(self):
        plugins = [NotDetectedPlugin()]
        context = MagicMock()
        active = _detect_plugins(context, plugins)
        assert active == []

    def test_detection_exception_skips_plugin(self):
        """If detect() raises, the plugin is skipped (not crashed)."""

        class BrokenDetectPlugin(FrameworkPlugin):
            name = "broken-detect"
            version = "1.0.0"
            supported_languages = {"java"}
            depends_on: list[str] = []

            def detect(self, context):
                raise ValueError("Detection crashed")

            async def extract(self, context):
                return PluginResult.empty()

        plugins = [BrokenDetectPlugin(), HighConfidencePlugin()]
        context = MagicMock()
        active = _detect_plugins(context, plugins)
        assert len(active) == 1
        assert active[0].name == "high-plugin"


# ---------------------------------------------------------------------------
# Topological sort tests
# ---------------------------------------------------------------------------

class TestTopologicalSort:
    def test_no_dependencies_single_layer(self):
        plugins = [HighConfidencePlugin(), MediumConfidencePlugin()]
        layers = _topological_sort(plugins)
        # All independent plugins in one layer
        assert len(layers) == 1
        names = {p.name for p in layers[0]}
        assert names == {"high-plugin", "medium-plugin"}

    def test_linear_dependency_chain(self):
        """A -> B -> C means 3 layers: [A], [B], [C]."""
        a = DependentPluginA()  # no deps
        b = DependentPluginB()  # depends on plugin-a
        c = DependentPluginC()  # depends on plugin-a, plugin-b
        layers = _topological_sort([c, b, a])  # deliberate scrambled order
        assert len(layers) == 3
        assert layers[0][0].name == "plugin-a"
        assert layers[1][0].name == "plugin-b"
        assert layers[2][0].name == "plugin-c"

    def test_independent_plugins_in_same_layer(self):
        """Two plugins with no deps are in the same concurrent layer."""
        a = DependentPluginA()  # no deps
        h = HighConfidencePlugin()  # no deps
        layers = _topological_sort([a, h])
        assert len(layers) == 1
        names = {p.name for p in layers[0]}
        assert names == {"plugin-a", "high-plugin"}

    def test_mixed_deps_and_independent(self):
        """A (no deps), H (no deps), B (depends A) -> [[A, H], [B]]."""
        a = DependentPluginA()
        h = HighConfidencePlugin()
        b = DependentPluginB()
        layers = _topological_sort([b, h, a])
        assert len(layers) == 2
        layer0_names = {p.name for p in layers[0]}
        layer1_names = {p.name for p in layers[1]}
        assert layer0_names == {"plugin-a", "high-plugin"}
        assert layer1_names == {"plugin-b"}

    def test_circular_dependency_raises(self):
        """Circular deps should raise ValueError."""

        class CircA(FrameworkPlugin):
            name = "circ-a"
            version = "1.0.0"
            supported_languages = {"java"}
            depends_on = ["circ-b"]

            def detect(self, context):
                return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

            async def extract(self, context):
                return PluginResult.empty()

        class CircB(FrameworkPlugin):
            name = "circ-b"
            version = "1.0.0"
            supported_languages = {"java"}
            depends_on = ["circ-a"]

            def detect(self, context):
                return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

            async def extract(self, context):
                return PluginResult.empty()

        with pytest.raises(ValueError, match="[Cc]ircular"):
            _topological_sort([CircA(), CircB()])

    def test_missing_dependency_warns_and_excludes(self):
        """Plugin depending on unregistered plugin is excluded."""
        b = DependentPluginB()  # depends on plugin-a, but A is not in the list
        layers = _topological_sort([b])
        # B should be excluded — its dependency is missing
        total_plugins = sum(len(layer) for layer in layers)
        assert total_plugins == 0

    def test_empty_input(self):
        layers = _topological_sort([])
        assert layers == []


# ---------------------------------------------------------------------------
# Error handling: failed plugins skip dependents
# ---------------------------------------------------------------------------

class TestFailedPluginSkipsDependents:
    @pytest.mark.asyncio
    async def test_failed_plugin_skips_dependents(self):
        """FailingPlugin crashes -> DependsOnFailingPlugin is skipped."""
        registry = PluginRegistry()
        registry.register(FailingPlugin)
        registry.register(DependsOnFailingPlugin)

        # Build a minimal context mock
        context = MagicMock()
        context.graph = SymbolGraph()
        context.plugin_new_nodes = 0
        context.plugin_new_edges = 0
        context.entry_points = []
        context.warnings = []

        await run_framework_plugins(context, registry=registry)

        # DependsOnFailingPlugin should NOT have been called (would raise AssertionError)
        # FailingPlugin's error should be in warnings
        assert any("failing-plugin" in w.lower() for w in context.warnings)


# ---------------------------------------------------------------------------
# Full integration: run_framework_plugins
# ---------------------------------------------------------------------------

class TestRunFrameworkPlugins:
    @pytest.mark.asyncio
    async def test_full_run_with_mock_plugins(self):
        registry = PluginRegistry()
        registry.register(HighConfidencePlugin)
        registry.register(MediumConfidencePlugin)
        registry.register(LowConfidencePlugin)  # Should be skipped
        registry.register(NotDetectedPlugin)  # Should be skipped

        context = MagicMock()
        context.graph = SymbolGraph()
        context.plugin_new_nodes = 0
        context.plugin_new_edges = 0
        context.entry_points = []
        context.warnings = []

        await run_framework_plugins(context, registry=registry)

        # HighConfidencePlugin adds 1 node + 1 edge
        # MediumConfidencePlugin adds 1 node + 0 edges
        assert context.plugin_new_nodes == 2
        assert context.plugin_new_edges == 1
        # Nodes should be in the graph
        assert context.graph.get_node("high.Node") is not None
        assert context.graph.get_node("med.Node") is not None

    @pytest.mark.asyncio
    async def test_layer_assignments_collected(self):
        registry = PluginRegistry()
        registry.register(HighConfidencePlugin)

        context = MagicMock()
        context.graph = SymbolGraph()
        context.plugin_new_nodes = 0
        context.plugin_new_edges = 0
        context.entry_points = []
        context.warnings = []
        context.layer_assignments = {}

        await run_framework_plugins(context, registry=registry)

        assert context.layer_assignments.get("high.Node") == "Business Logic"

    @pytest.mark.asyncio
    async def test_entry_points_collected(self):
        class EntryPointPlugin(FrameworkPlugin):
            name = "ep-plugin"
            version = "1.0.0"
            supported_languages = {"java"}
            depends_on: list[str] = []

            def detect(self, context):
                return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

            async def extract(self, context) -> PluginResult:
                return PluginResult(
                    nodes=[],
                    edges=[],
                    layer_assignments={},
                    entry_points=[
                        EntryPoint(fqn="com.example.UserController.getUser", kind="http_endpoint", metadata={"method": "GET", "path": "/api/users/:id"}),
                    ],
                    warnings=[],
                )

        registry = PluginRegistry()
        registry.register(EntryPointPlugin)

        context = MagicMock()
        context.graph = SymbolGraph()
        context.plugin_new_nodes = 0
        context.plugin_new_edges = 0
        context.entry_points = []
        context.warnings = []
        context.layer_assignments = {}

        await run_framework_plugins(context, registry=registry)

        assert len(context.entry_points) == 1
        assert context.entry_points[0].kind == "http_endpoint"

    @pytest.mark.asyncio
    async def test_warnings_collected(self):
        registry = PluginRegistry()
        registry.register(MediumConfidencePlugin)  # Produces a warning

        context = MagicMock()
        context.graph = SymbolGraph()
        context.plugin_new_nodes = 0
        context.plugin_new_edges = 0
        context.entry_points = []
        context.warnings = []
        context.layer_assignments = {}

        await run_framework_plugins(context, registry=registry)

        assert any("incomplete" in w.lower() for w in context.warnings)

    @pytest.mark.asyncio
    async def test_dependency_order_respected(self):
        """Plugins run in dependency order: A first, then B."""
        execution_order: list[str] = []

        class OrderedA(FrameworkPlugin):
            name = "ordered-a"
            version = "1.0.0"
            supported_languages = {"java"}
            depends_on: list[str] = []

            def detect(self, context):
                return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

            async def extract(self, context) -> PluginResult:
                execution_order.append("ordered-a")
                return PluginResult.empty()

        class OrderedB(FrameworkPlugin):
            name = "ordered-b"
            version = "1.0.0"
            supported_languages = {"java"}
            depends_on = ["ordered-a"]

            def detect(self, context):
                return PluginDetectionResult(confidence=Confidence.HIGH, reason="test")

            async def extract(self, context) -> PluginResult:
                execution_order.append("ordered-b")
                return PluginResult.empty()

        registry = PluginRegistry()
        registry.register(OrderedB)
        registry.register(OrderedA)

        context = MagicMock()
        context.graph = SymbolGraph()
        context.plugin_new_nodes = 0
        context.plugin_new_edges = 0
        context.entry_points = []
        context.warnings = []
        context.layer_assignments = {}

        await run_framework_plugins(context, registry=registry)

        assert execution_order == ["ordered-a", "ordered-b"]

    @pytest.mark.asyncio
    async def test_no_plugins_is_noop(self):
        registry = PluginRegistry()

        context = MagicMock()
        context.graph = SymbolGraph()
        context.plugin_new_nodes = 0
        context.plugin_new_edges = 0
        context.entry_points = []
        context.warnings = []
        context.layer_assignments = {}

        # Should complete without error
        await run_framework_plugins(context, registry=registry)
        assert context.plugin_new_nodes == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_registry.py -v`
Expected: FAIL (ImportError — `app.stages.plugins.registry` doesn't exist)

- [ ] **Step 3: Implement `registry.py`**

```python
# app/stages/plugins/registry.py
"""Plugin registry: discovery, detection, topological sort, and execution.

The registry manages the full plugin lifecycle:
1. Registration — plugins register via decorator or explicit call
2. Detection — each plugin's detect() determines relevance (HIGH/MEDIUM activate)
3. Ordering — topological sort on depends_on; independent plugins form concurrent layers
4. Execution — plugins run in dependency order; concurrent within each layer
5. Merging — results are merged into AnalysisContext
6. Error handling — failed plugins skip themselves AND all dependents

Usage:
    # Option 1: Module-level global registry (for production)
    from app.stages.plugins.registry import global_registry, run_framework_plugins

    @global_registry.register
    class MyPlugin(FrameworkPlugin): ...

    await run_framework_plugins(context)  # uses global_registry by default

    # Option 2: Explicit registry (for testing)
    registry = PluginRegistry()
    registry.register(MyPlugin)
    await run_framework_plugins(context, registry=registry)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any

import structlog

from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Plugin Registry
# ---------------------------------------------------------------------------

class PluginRegistry:
    """Stores registered plugin classes and instantiates them on demand."""

    def __init__(self) -> None:
        self._plugin_classes: list[type[FrameworkPlugin]] = []
        self._by_name: dict[str, type[FrameworkPlugin]] = {}

    @property
    def plugin_classes(self) -> list[type[FrameworkPlugin]]:
        return list(self._plugin_classes)

    def register(self, plugin_class: type[FrameworkPlugin]) -> type[FrameworkPlugin]:
        """Register a plugin class. Can be used as a decorator or called directly.

        If a plugin with the same name is already registered, the old one is replaced.

        Returns:
            The plugin class (unchanged), so this works as a decorator.
        """
        name = plugin_class.name
        if name in self._by_name:
            # Replace existing registration
            self._plugin_classes = [
                cls for cls in self._plugin_classes if cls.name != name
            ]
            logger.warning("plugin_replaced", plugin_name=name)
        self._plugin_classes.append(plugin_class)
        self._by_name[name] = plugin_class
        logger.debug("plugin_registered", plugin_name=name, version=plugin_class.version)
        return plugin_class

    def instantiate(self) -> list[FrameworkPlugin]:
        """Create instances of all registered plugin classes."""
        return [cls() for cls in self._plugin_classes]


# Module-level global registry for production use
global_registry = PluginRegistry()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _detect_plugins(
    context: Any,
    plugins: list[FrameworkPlugin],
) -> list[FrameworkPlugin]:
    """Run detect() on each plugin and return those that are active (HIGH or MEDIUM).

    If a plugin's detect() raises, it is skipped with a warning.
    LOW confidence and not-detected plugins are excluded.
    """
    active: list[FrameworkPlugin] = []
    for plugin in plugins:
        try:
            result: PluginDetectionResult = plugin.detect(context)
            if result.is_active:
                log_level = "info" if result.confidence is not None else "debug"
                logger.info(
                    "plugin_detected",
                    plugin_name=plugin.name,
                    confidence=result.confidence.name if result.confidence else "NONE",
                    reason=result.reason,
                )
                active.append(plugin)
            else:
                logger.debug(
                    "plugin_skipped",
                    plugin_name=plugin.name,
                    confidence=result.confidence.name if result.confidence else "NONE",
                    reason=result.reason,
                )
        except Exception:
            logger.exception("plugin_detect_failed", plugin_name=plugin.name)
    return active


# ---------------------------------------------------------------------------
# Topological Sort
# ---------------------------------------------------------------------------

def _topological_sort(
    plugins: list[FrameworkPlugin],
) -> list[list[FrameworkPlugin]]:
    """Sort plugins into layers by dependency order using Kahn's algorithm.

    Returns a list of layers. Each layer contains plugins that can run
    concurrently (all their dependencies are in earlier layers).

    Plugins with missing dependencies are excluded with a warning.
    Raises ValueError if a circular dependency is detected.
    """
    if not plugins:
        return []

    # Build lookup
    by_name: dict[str, FrameworkPlugin] = {p.name: p for p in plugins}
    available_names = set(by_name.keys())

    # Exclude plugins with missing dependencies
    excluded: set[str] = set()

    def _find_excluded() -> bool:
        """One pass: find plugins whose deps are missing or excluded. Returns True if any found."""
        found = False
        for p in plugins:
            if p.name in excluded:
                continue
            for dep in p.depends_on:
                if dep not in available_names or dep in excluded:
                    logger.warning(
                        "plugin_excluded_missing_dep",
                        plugin_name=p.name,
                        missing_dependency=dep,
                    )
                    excluded.add(p.name)
                    found = True
                    break
        return found

    # Iterate until stable (cascading exclusions)
    while _find_excluded():
        pass

    remaining = [p for p in plugins if p.name not in excluded]
    if not remaining:
        return []

    # Kahn's algorithm with layering
    in_degree: dict[str, int] = {p.name: 0 for p in remaining}
    dependents: dict[str, list[str]] = defaultdict(list)

    for p in remaining:
        for dep in p.depends_on:
            if dep not in excluded:
                in_degree[p.name] += 1
                dependents[dep].append(p.name)

    # Initial layer: all plugins with in_degree 0
    current_layer_names = deque(name for name, deg in in_degree.items() if deg == 0)
    layers: list[list[FrameworkPlugin]] = []
    processed = 0

    while current_layer_names:
        layer: list[FrameworkPlugin] = []
        next_layer_names: list[str] = []

        while current_layer_names:
            name = current_layer_names.popleft()
            layer.append(by_name[name])
            processed += 1

            for dependent_name in dependents[name]:
                in_degree[dependent_name] -= 1
                if in_degree[dependent_name] == 0:
                    next_layer_names.append(dependent_name)

        layers.append(layer)
        current_layer_names = deque(next_layer_names)

    if processed < len(remaining):
        cycle_members = [p.name for p in remaining if in_degree.get(p.name, 0) > 0]
        raise ValueError(
            f"Circular dependency detected among plugins: {cycle_members}"
        )

    return layers


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

async def _execute_plugin(
    plugin: FrameworkPlugin,
    context: Any,
) -> tuple[str, PluginResult | None, Exception | None]:
    """Execute a single plugin's extract() with error handling.

    Returns:
        (plugin_name, result_or_none, exception_or_none)
    """
    try:
        logger.info("plugin_extract_start", plugin_name=plugin.name)
        result = await plugin.extract(context)
        logger.info(
            "plugin_extract_complete",
            plugin_name=plugin.name,
            nodes=result.node_count,
            edges=result.edge_count,
            warnings=len(result.warnings),
        )
        return (plugin.name, result, None)
    except Exception as exc:
        logger.exception("plugin_extract_failed", plugin_name=plugin.name)
        return (plugin.name, None, exc)


def _merge_result(context: Any, result: PluginResult) -> None:
    """Merge a single PluginResult into the AnalysisContext.

    Adds nodes and edges to context.graph, updates counters, collects
    entry points, layer assignments, and warnings.
    """
    for node in result.nodes:
        context.graph.add_node(node)
    for edge in result.edges:
        context.graph.add_edge(edge)

    context.plugin_new_nodes += result.node_count
    context.plugin_new_edges += result.edge_count
    context.entry_points.extend(result.entry_points)
    context.warnings.extend(result.warnings)

    # Layer assignments: stored on context if the attribute exists
    if hasattr(context, "layer_assignments"):
        context.layer_assignments.update(result.layer_assignments)


async def run_framework_plugins(
    context: Any,
    *,
    registry: PluginRegistry | None = None,
) -> None:
    """Main entry point: discover, detect, order, execute, and merge all plugins.

    This is Stage 5 of the analysis pipeline.

    Args:
        context: AnalysisContext for the current project.
        registry: Optional explicit registry. Defaults to global_registry.
    """
    reg = registry or global_registry
    logger.info("plugin_stage_start", registered_count=len(reg.plugin_classes))

    # 1. Instantiate all registered plugins
    all_plugins = reg.instantiate()
    if not all_plugins:
        logger.info("plugin_stage_complete", message="no plugins registered")
        return

    # 2. Detection: filter to active plugins
    active_plugins = _detect_plugins(context, all_plugins)
    if not active_plugins:
        logger.info("plugin_stage_complete", message="no plugins detected for this project")
        return

    logger.info(
        "plugins_detected",
        active=[p.name for p in active_plugins],
        skipped=[p.name for p in all_plugins if p not in active_plugins],
    )

    # 3. Topological sort into dependency layers
    try:
        layers = _topological_sort(active_plugins)
    except ValueError as exc:
        context.warnings.append(f"Plugin ordering failed: {exc}")
        logger.error("plugin_topological_sort_failed", error=str(exc))
        return

    # 4. Execute layer by layer
    failed_plugins: set[str] = set()

    for layer_idx, layer in enumerate(layers):
        # Filter out plugins whose dependencies failed
        runnable = [
            p for p in layer
            if not any(dep in failed_plugins for dep in p.depends_on)
        ]
        skipped = [p for p in layer if p not in runnable]

        for p in skipped:
            failed_plugins.add(p.name)
            msg = f"Plugin {p.name!r} skipped: dependency failed"
            context.warnings.append(msg)
            logger.warning("plugin_skipped_dep_failed", plugin_name=p.name)

        if not runnable:
            continue

        logger.info(
            "plugin_layer_start",
            layer=layer_idx,
            plugins=[p.name for p in runnable],
        )

        # Run all plugins in this layer concurrently
        tasks = [_execute_plugin(p, context) for p in runnable]
        results = await asyncio.gather(*tasks)

        # Process results
        for plugin_name, result, exc in results:
            if exc is not None:
                failed_plugins.add(plugin_name)
                msg = f"Plugin {plugin_name!r} failed: {exc}"
                context.warnings.append(msg)
            elif result is not None:
                _merge_result(context, result)

    logger.info(
        "plugin_stage_complete",
        total_new_nodes=context.plugin_new_nodes,
        total_new_edges=context.plugin_new_edges,
        failed_plugins=list(failed_plugins),
    )
```

- [ ] **Step 4: Update `__init__.py` to re-export registry types**

```python
# app/stages/plugins/__init__.py
"""Framework plugin system for extracting invisible connections from code.

Plugins detect framework usage, extract hidden relationships (DI wiring,
ORM mappings, endpoint routes), and produce new graph nodes and edges.
"""

from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)
from app.stages.plugins.registry import (
    PluginRegistry,
    global_registry,
    run_framework_plugins,
)

__all__ = [
    "FrameworkPlugin",
    "LayerRule",
    "LayerRules",
    "PluginDetectionResult",
    "PluginRegistry",
    "PluginResult",
    "global_registry",
    "run_framework_plugins",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_registry.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Run ALL plugin tests together**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_base.py tests/unit/test_plugin_registry.py -v`
Expected: PASS (all tests from both files)

- [ ] **Step 7: Lint**

Run: `cd cast-clone-backend && uv run ruff check app/stages/ tests/unit/test_plugin_base.py tests/unit/test_plugin_registry.py && uv run ruff format --check app/stages/ tests/unit/test_plugin_base.py tests/unit/test_plugin_registry.py`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
cd cast-clone-backend && git add app/stages/ tests/unit/test_plugin_registry.py && git commit -m "feat(plugins): add PluginRegistry with detection, topological sort, concurrent execution, and error handling"
```

---

## Task 3: Verify Full Test Suite & Final Commit

- [ ] **Step 1: Run all existing tests to confirm nothing is broken**

Run: `cd cast-clone-backend && uv run pytest tests/ -v`
Expected: All tests pass (including any existing M1 tests plus new plugin tests)

- [ ] **Step 2: Run type checking (if mypy is configured)**

Run: `cd cast-clone-backend && uv run mypy app/stages/plugins/`
Expected: No type errors (or only pre-existing ones from stub dependencies)

- [ ] **Step 3: Final commit if any cleanup was needed**

```bash
cd cast-clone-backend && git add -A && git status
# Only commit if there are changes
```

---

## Summary of Deliverables

| File | Purpose |
|------|---------|
| `app/stages/__init__.py` | Package init for stages |
| `app/stages/plugins/__init__.py` | Re-exports all public types |
| `app/stages/plugins/base.py` | `FrameworkPlugin` ABC, `PluginResult`, `PluginDetectionResult`, `LayerRules`, `LayerRule` |
| `app/stages/plugins/registry.py` | `PluginRegistry`, `_detect_plugins`, `_topological_sort`, `run_framework_plugins`, `global_registry` |
| `tests/unit/test_plugin_base.py` | 16 tests: PluginResult, LayerRules, PluginDetectionResult, FrameworkPlugin contract |
| `tests/unit/test_plugin_registry.py` | 18 tests: registry CRUD, detection, topo sort, error handling, full integration |

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| `detect()` returns `PluginDetectionResult` (not raw `Confidence`) | Includes `reason` string for logging/debugging; `is_active` property encapsulates the HIGH/MEDIUM threshold | Better observability than a bare enum |
| `extract()` is `async` | Plugins may do I/O (read files, query graph DB) | Consistent with pipeline's async-first design |
| `_topological_sort` returns `list[list[Plugin]]` (layers) | Each layer is a set of independent plugins that can run concurrently via `asyncio.gather` | Maximizes parallelism while respecting ordering |
| Missing dependency excludes plugin (not crash) | Cascading exclusion with warning | Graceful degradation per CLAUDE.md: only Stage 1 and Stage 8 are fatal |
| Circular dependency raises `ValueError` | This is a developer bug, not a runtime condition | Fail fast during development |
| `PluginRegistry` is a class (not just module-level functions) | Testable: tests create isolated registries | Global registry available for production via `global_registry` |
| `register()` works as both decorator and direct call | `@registry.register` for inline definition; `registry.register(PluginClass)` for explicit | Flexible registration patterns |
| Failed plugin marks all dependents as skipped | Tracked via `failed_plugins` set, checked before each layer | Prevents cascading failures from running plugins with missing upstream data |
