"""Pydantic v2 schemas for Graph Query API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphNodeResponse(BaseModel):
    """Single graph node in API responses."""

    fqn: str
    name: str
    kind: str
    language: str | None = None
    path: str | None = None
    line: int | None = None
    end_line: int | None = None
    loc: int | None = None
    complexity: int | None = None
    visibility: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeResponse(BaseModel):
    """Single graph edge in API responses."""

    source_fqn: str
    target_fqn: str
    kind: str
    confidence: str = "HIGH"
    evidence: str = "tree-sitter"
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphNodeListResponse(BaseModel):
    """Paginated list of graph nodes."""

    nodes: list[GraphNodeResponse]
    total: int
    offset: int
    limit: int


class GraphEdgeListResponse(BaseModel):
    """Paginated list of graph edges."""

    edges: list[GraphEdgeResponse]
    total: int
    offset: int
    limit: int


class NodeWithNeighborsResponse(BaseModel):
    """Single node with its incoming/outgoing edges and neighbor nodes."""

    node: GraphNodeResponse
    incoming_edges: list[GraphEdgeResponse]
    outgoing_edges: list[GraphEdgeResponse]
    neighbors: list[GraphNodeResponse]


class GraphSearchHit(BaseModel):
    """A single search result."""

    fqn: str
    name: str
    kind: str
    language: str | None = None
    score: float = 0.0


class GraphSearchResponse(BaseModel):
    """Full-text search response."""

    query: str
    hits: list[GraphSearchHit]
    total: int
