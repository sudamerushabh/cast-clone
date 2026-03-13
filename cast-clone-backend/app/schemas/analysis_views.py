# app/schemas/analysis_views.py
"""Pydantic v2 schemas for Phase 3 analysis API endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Impact Analysis ──────────────────────────────────────

class AffectedNode(BaseModel):
    fqn: str
    name: str
    type: str
    file: str | None = None
    depth: int

class ImpactSummary(BaseModel):
    total: int
    by_type: dict[str, int] = Field(default_factory=dict)
    by_depth: dict[str, int] = Field(default_factory=dict)

class ImpactAnalysisResponse(BaseModel):
    node: str
    direction: str
    max_depth: int
    summary: ImpactSummary
    affected: list[AffectedNode]

# ── Path Finder ──────────────────────────────────────────

class PathNode(BaseModel):
    fqn: str
    name: str
    type: str

class PathEdge(BaseModel):
    type: str
    source: str
    target: str

class PathFinderResponse(BaseModel):
    from_fqn: str
    to_fqn: str
    nodes: list[PathNode]
    edges: list[PathEdge]
    path_length: int

# ── Communities ──────────────────────────────────────────

class CommunityInfo(BaseModel):
    community_id: int
    size: int
    members: list[str]

class CommunitiesResponse(BaseModel):
    communities: list[CommunityInfo]
    total: int
    modularity: float | None = None

# ── Circular Dependencies ────────────────────────────────

class CircularDependency(BaseModel):
    cycle: list[str]
    cycle_length: int

class CircularDependenciesResponse(BaseModel):
    cycles: list[CircularDependency]
    total: int
    level: str

# ── Dead Code ────────────────────────────────────────────

class DeadCodeCandidate(BaseModel):
    fqn: str
    name: str
    path: str | None = None
    line: int | None = None
    loc: int | None = None

class DeadCodeResponse(BaseModel):
    candidates: list[DeadCodeCandidate]
    total: int
    type_filter: str

# ── Metrics Dashboard ────────────────────────────────────

class OverviewStats(BaseModel):
    modules: int = 0
    classes: int = 0
    functions: int = 0
    total_loc: int = 0

class RankedItem(BaseModel):
    fqn: str
    name: str
    value: int

class MetricsResponse(BaseModel):
    overview: OverviewStats
    most_complex: list[RankedItem]
    highest_fan_in: list[RankedItem]
    highest_fan_out: list[RankedItem]
    community_count: int = 0
    circular_dependency_count: int = 0
    dead_code_count: int = 0

# ── Enhanced Node Details ────────────────────────────────

class NodeDetailResponse(BaseModel):
    fqn: str
    name: str
    type: str
    language: str | None = None
    path: str | None = None
    line: int | None = None
    loc: int | None = None
    complexity: int | None = None
    fan_in: int = 0
    fan_out: int = 0
    community_id: int | None = None
    callers: list[PathNode] = Field(default_factory=list)
    callees: list[PathNode] = Field(default_factory=list)
