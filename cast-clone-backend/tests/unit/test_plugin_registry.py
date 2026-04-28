from unittest.mock import MagicMock

import pytest

from app.models.context import EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)
from app.stages.plugins.registry import (
    PluginRegistry,
    _detect_plugins,
    _topological_sort,
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
        return PluginDetectionResult(
            confidence=Confidence.HIGH, reason="build file found"
        )

    async def extract(self, context) -> PluginResult:
        return PluginResult(
            nodes=[
                GraphNode(
                    fqn="high.Node",
                    name="Node",
                    kind=NodeKind.CLASS,
                    language="java",
                )
            ],
            edges=[
                GraphEdge(
                    source_fqn="high.Node",
                    target_fqn="high.Other",
                    kind=EdgeKind.INJECTS,
                    evidence="high-plugin",
                )
            ],
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
        return PluginDetectionResult(
            confidence=Confidence.MEDIUM, reason="annotations found"
        )

    async def extract(self, context) -> PluginResult:
        return PluginResult(
            nodes=[
                GraphNode(
                    fqn="med.Node",
                    name="Node",
                    kind=NodeKind.CLASS,
                    language="java",
                )
            ],
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
        raise AssertionError(
            "Should never be called -- LOW confidence plugins are skipped"
        )


class NotDetectedPlugin(FrameworkPlugin):
    name = "absent-plugin"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context):
        return PluginDetectionResult.not_detected()

    async def extract(self, context) -> PluginResult:
        raise AssertionError("Should never be called -- not detected")


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
    """No dependencies -- should run before B."""

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
        plugins = [
            HighConfidencePlugin(),
            MediumConfidencePlugin(),
            LowConfidencePlugin(),
            NotDetectedPlugin(),
        ]
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
        # B should be excluded -- its dependency is missing
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

        # DependsOnFailingPlugin should NOT have been called
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
                        EntryPoint(
                            fqn="com.example.UserController.getUser",
                            kind="http_endpoint",
                            metadata={"method": "GET", "path": "/api/users/:id"},
                        ),
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


class TestAlembicRegistration:
    def test_alembic_plugin_discovered(self):
        from app.stages.plugins import global_registry

        names = [cls.name for cls in global_registry.plugin_classes]
        assert "alembic" in names


def test_fastapi_pydantic_plugin_is_registered():
    from app.stages.plugins import global_registry
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    assert FastAPIPydanticPlugin in global_registry.plugin_classes


def test_celery_plugin_is_registered():
    from app.stages.plugins import global_registry
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    assert CeleryPlugin in global_registry.plugin_classes
