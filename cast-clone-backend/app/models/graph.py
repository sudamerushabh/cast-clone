"""In-memory graph representation: GraphNode, GraphEdge, SymbolGraph.

These are internal dataclasses used throughout the pipeline. NOT Pydantic
models -- we use dataclasses for performance since these are created in bulk
during parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import Confidence, EdgeKind, NodeKind

# Map NodeKind -> Neo4j label (PascalCase, no underscores)
_KIND_TO_LABEL: dict[NodeKind, str] = {
    NodeKind.APPLICATION: "Application",
    NodeKind.MODULE: "Module",
    NodeKind.CLASS: "Class",
    NodeKind.INTERFACE: "Interface",
    NodeKind.FUNCTION: "Function",
    NodeKind.FIELD: "Field",
    NodeKind.TABLE: "Table",
    NodeKind.COLUMN: "Column",
    NodeKind.VIEW: "View",
    NodeKind.STORED_PROCEDURE: "StoredProcedure",
    NodeKind.API_ENDPOINT: "APIEndpoint",
    NodeKind.ROUTE: "Route",
    NodeKind.MESSAGE_TOPIC: "MessageTopic",
    NodeKind.CONFIG_FILE: "ConfigFile",
    NodeKind.CONFIG_ENTRY: "ConfigEntry",
    NodeKind.LAYER: "Layer",
    NodeKind.COMPONENT: "Component",
    NodeKind.COMMUNITY: "Community",
    NodeKind.TRANSACTION: "Transaction",
}


@dataclass
class GraphNode:
    """A node in the code graph (class, function, table, endpoint, etc.)."""

    fqn: str
    name: str
    kind: NodeKind
    language: str | None = None
    path: str | None = None
    line: int | None = None
    end_line: int | None = None
    loc: int | None = None
    complexity: int | None = None
    visibility: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Neo4j node label derived from kind."""
        return _KIND_TO_LABEL[self.kind]


@dataclass
class GraphEdge:
    """A directed edge in the code graph (CALLS, CONTAINS, INJECTS, etc.)."""

    source_fqn: str
    target_fqn: str
    kind: EdgeKind
    confidence: Confidence = Confidence.HIGH
    evidence: str = "tree-sitter"
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class SymbolGraph:
    """Mutable in-memory graph accumulating nodes and edges through the pipeline."""

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    # Lazily-built reverse indexes (invalidated on mutation)
    _edges_from: dict[str, list[GraphEdge]] = field(
        default_factory=dict, repr=False
    )
    _edges_to: dict[str, list[GraphEdge]] = field(
        default_factory=dict, repr=False
    )
    _index_dirty: bool = field(default=True, repr=False)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.fqn] = node

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)
        self._index_dirty = True

    def get_node(self, fqn: str) -> GraphNode | None:
        return self.nodes.get(fqn)

    def _rebuild_index(self) -> None:
        self._edges_from.clear()
        self._edges_to.clear()
        for e in self.edges:
            self._edges_from.setdefault(e.source_fqn, []).append(e)
            self._edges_to.setdefault(e.target_fqn, []).append(e)
        self._index_dirty = False

    def get_edges_from(self, fqn: str) -> list[GraphEdge]:
        if self._index_dirty:
            self._rebuild_index()
        return self._edges_from.get(fqn, [])

    def get_edges_to(self, fqn: str) -> list[GraphEdge]:
        if self._index_dirty:
            self._rebuild_index()
        return self._edges_to.get(fqn, [])

    def merge(self, other: SymbolGraph) -> None:
        for node in other.nodes.values():
            self.add_node(node)
        for edge in other.edges:
            self.add_edge(edge)
