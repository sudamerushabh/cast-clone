import pytest

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
                EntryPoint(
                    fqn="a.handle",
                    kind="http_endpoint",
                    metadata={"method": "GET"},
                ),
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
        rules = LayerRules(
            rules=[
                LayerRule(pattern="@RestController", layer="Presentation"),
                LayerRule(pattern="@Service", layer="Business Logic"),
                LayerRule(pattern="@Repository", layer="Data Access"),
            ]
        )
        assert len(rules.rules) == 3
        assert rules.rules[0].layer == "Presentation"

    def test_layer_rule_fields(self):
        rule = LayerRule(pattern="@Controller", layer="Presentation")
        assert rule.pattern == "@Controller"
        assert rule.layer == "Presentation"

    def test_classify_fqn_matches_first_rule(self):
        rules = LayerRules(
            rules=[
                LayerRule(pattern="Controller", layer="Presentation"),
                LayerRule(pattern="Service", layer="Business Logic"),
            ]
        )
        # classify checks if pattern appears in the fqn
        assert rules.classify("com.example.UserController") == "Presentation"
        assert rules.classify("com.example.UserService") == "Business Logic"
        assert rules.classify("com.example.SomeUtil") is None


# ---------------------------------------------------------------------------
# PluginDetectionResult tests
# ---------------------------------------------------------------------------


class TestPluginDetectionResult:
    def test_detection_result_fields(self):
        result = PluginDetectionResult(
            confidence=Confidence.HIGH,
            reason="pom.xml contains spring-boot",
        )
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
    """Missing required abstract methods -- cannot be instantiated."""

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
