"""Framework plugin base class and result types.

Every framework plugin (Spring, Hibernate, React, Express, etc.) extends
FrameworkPlugin and implements detect() + extract(). The registry discovers,
detects, orders, and executes plugins automatically.

Internal models use dataclasses (not Pydantic) for performance -- plugins
create many nodes/edges during extraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.models.context import EntryPoint
from app.models.enums import Confidence
from app.models.graph import GraphEdge, GraphNode

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
    """Result of plugin.detect() -- whether the plugin is relevant to the project.

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
    """Output of plugin.extract() -- new nodes, edges, and metadata to merge.

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
        return cls(
            nodes=[],
            edges=[],
            layer_assignments={},
            entry_points=[],
            warnings=[],
        )

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
        1. detect(context)  -- Is this framework present? Returns PluginDetectionResult.
        2. extract(context) -- Parse code, produce nodes/edges. Only called if detect()
                              returned HIGH or MEDIUM confidence.
        3. get_layer_classification() -- Optional: how to classify nodes into layers.
        4. get_entry_points(context) -- Optional: transaction starting points.
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
        return (
            f"{self.__class__.__name__}(name={self.name!r}, version={self.version!r})"
        )
