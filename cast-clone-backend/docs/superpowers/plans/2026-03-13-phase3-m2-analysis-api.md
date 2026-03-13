# Phase 3 M2: Analysis API Endpoints — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 7 API endpoints for impact analysis, path finding, community listing, circular dependency detection, dead code candidates, metrics dashboard, and enhanced node details — all backed by Cypher queries against Neo4j.

**Architecture:** New router `app/api/analysis_views.py` with prefix `/api/v1/analysis`. New Pydantic schemas in `app/schemas/analysis_views.py`. Each endpoint executes 1-2 Cypher queries via the existing `Neo4jGraphStore.query()` method. Follows the patterns in `app/api/graph_views.py`.

**Tech Stack:** FastAPI, Pydantic v2, Neo4j async driver (via existing GraphStore), pytest + pytest-asyncio

**Dependencies:** Phase 1 M1 (foundation), Phase 1 M7c (Neo4j writer), Phase 2 M1 (graph_views pattern)

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── api/
│   │   ├── __init__.py              # MODIFY — export analysis_views_router
│   │   └── analysis_views.py        # CREATE — 7 new endpoints
│   ├── schemas/
│   │   └── analysis_views.py        # CREATE — Pydantic response schemas
│   └── main.py                      # MODIFY — register analysis_views_router
└── tests/
    └── unit/
        └── test_analysis_views_api.py  # CREATE — unit tests
```

---

## Task 1: Create Pydantic Schemas

**Files:**
- Create: `cast-clone-backend/app/schemas/analysis_views.py`

- [ ] **Step 1: Create the schemas file**

```python
# app/schemas/analysis_views.py
"""Pydantic v2 schemas for Phase 3 analysis API endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Impact Analysis ──────────────────────────────────────


class AffectedNode(BaseModel):
    """A node affected by a change to the start node."""

    fqn: str
    name: str
    type: str
    file: str | None = None
    depth: int


class ImpactSummary(BaseModel):
    """Summary statistics for impact analysis."""

    total: int
    by_type: dict[str, int] = Field(default_factory=dict)
    by_depth: dict[str, int] = Field(default_factory=dict)


class ImpactAnalysisResponse(BaseModel):
    """Response for impact analysis endpoint."""

    node: str
    direction: str
    max_depth: int
    summary: ImpactSummary
    affected: list[AffectedNode]


# ── Path Finder ──────────────────────────────────────────


class PathNode(BaseModel):
    """A node in a shortest path."""

    fqn: str
    name: str
    type: str


class PathEdge(BaseModel):
    """An edge in a shortest path."""

    type: str
    source: str
    target: str


class PathFinderResponse(BaseModel):
    """Response for path finder endpoint."""

    from_fqn: str
    to_fqn: str
    nodes: list[PathNode]
    edges: list[PathEdge]
    path_length: int


# ── Communities ──────────────────────────────────────────


class CommunityInfo(BaseModel):
    """A detected community cluster."""

    community_id: int
    size: int
    members: list[str]


class CommunitiesResponse(BaseModel):
    """Response for communities listing endpoint."""

    communities: list[CommunityInfo]
    total: int
    modularity: float | None = None


# ── Circular Dependencies ────────────────────────────────


class CircularDependency(BaseModel):
    """A circular dependency cycle."""

    cycle: list[str]
    cycle_length: int


class CircularDependenciesResponse(BaseModel):
    """Response for circular dependency detection endpoint."""

    cycles: list[CircularDependency]
    total: int
    level: str


# ── Dead Code ────────────────────────────────────────────


class DeadCodeCandidate(BaseModel):
    """A dead code candidate (unreferenced function/class)."""

    fqn: str
    name: str
    path: str | None = None
    line: int | None = None
    loc: int | None = None


class DeadCodeResponse(BaseModel):
    """Response for dead code candidates endpoint."""

    candidates: list[DeadCodeCandidate]
    total: int
    type_filter: str


# ── Metrics Dashboard ────────────────────────────────────


class OverviewStats(BaseModel):
    """High-level codebase statistics."""

    modules: int = 0
    classes: int = 0
    functions: int = 0
    total_loc: int = 0


class RankedItem(BaseModel):
    """An item in a top-10 ranking list."""

    fqn: str
    name: str
    value: int


class MetricsResponse(BaseModel):
    """Response for metrics dashboard endpoint."""

    overview: OverviewStats
    most_complex: list[RankedItem]
    highest_fan_in: list[RankedItem]
    highest_fan_out: list[RankedItem]
    community_count: int = 0
    circular_dependency_count: int = 0
    dead_code_count: int = 0


# ── Enhanced Node Details ────────────────────────────────


class NodeDetailResponse(BaseModel):
    """Enhanced node details with analysis data."""

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
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend
git add app/schemas/analysis_views.py
git commit -m "feat(phase3): add Pydantic schemas for analysis API endpoints"
```

---

## Task 2: Write Failing Tests

**Files:**
- Create: `cast-clone-backend/tests/unit/test_analysis_views_api.py`

- [ ] **Step 1: Write the test file**

```python
# tests/unit/test_analysis_views_api.py
"""Tests for Phase 3 analysis API endpoints.

Uses FastAPI TestClient with a mocked Neo4jGraphStore.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_graph_store():
    """Mock the graph store dependency for all tests."""
    mock_store = AsyncMock()
    mock_store.query = AsyncMock(return_value=[])
    mock_store.query_single = AsyncMock(return_value=None)

    with patch("app.api.analysis_views.get_graph_store", return_value=mock_store):
        yield mock_store


# ── Impact Analysis ──────────────────────────────────────


class TestImpactAnalysis:
    def test_downstream_impact_returns_affected_nodes(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {"fqn": "com.app.Repo.save", "name": "save", "type": "Function", "file": "Repo.java", "depth": 1},
            {"fqn": "com.app.users", "name": "users", "type": "Table", "file": None, "depth": 2},
        ]

        resp = client.get(
            "/api/v1/analysis/test-project/impact/com.app.Service.create",
            params={"direction": "downstream", "max_depth": 5},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["node"] == "com.app.Service.create"
        assert data["direction"] == "downstream"
        assert data["summary"]["total"] == 2
        assert data["summary"]["by_type"]["Function"] == 1
        assert data["summary"]["by_type"]["Table"] == 1
        assert len(data["affected"]) == 2

    def test_upstream_impact(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {"fqn": "com.app.Controller.handle", "name": "handle", "type": "Function", "file": "Controller.java", "depth": 1},
        ]

        resp = client.get(
            "/api/v1/analysis/test-project/impact/com.app.Service.create",
            params={"direction": "upstream"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["direction"] == "upstream"
        assert data["summary"]["total"] == 1

    def test_impact_default_direction_is_downstream(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []

        resp = client.get("/api/v1/analysis/test-project/impact/com.app.X")
        assert resp.status_code == 200
        assert resp.json()["direction"] == "downstream"

    def test_impact_max_depth_default_is_5(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []

        resp = client.get("/api/v1/analysis/test-project/impact/com.app.X")
        assert resp.status_code == 200
        assert resp.json()["max_depth"] == 5


# ── Path Finder ──────────────────────────────────────────


class TestPathFinder:
    def test_shortest_path_between_nodes(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {
                "nodes": [
                    {"fqn": "com.A", "name": "A", "type": "Class"},
                    {"fqn": "com.B", "name": "B", "type": "Class"},
                    {"fqn": "com.C", "name": "C", "type": "Class"},
                ],
                "edges": [
                    {"type": "CALLS", "source": "com.A", "target": "com.B"},
                    {"type": "DEPENDS_ON", "source": "com.B", "target": "com.C"},
                ],
                "pathLength": 2,
            }
        ]

        resp = client.get(
            "/api/v1/analysis/test-project/path",
            params={"from_fqn": "com.A", "to_fqn": "com.C"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["path_length"] == 2
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2

    def test_path_no_connection(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []

        resp = client.get(
            "/api/v1/analysis/test-project/path",
            params={"from_fqn": "com.A", "to_fqn": "com.Z"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["path_length"] == 0
        assert data["nodes"] == []

    def test_path_requires_both_fqns(self, client, mock_graph_store):
        resp = client.get(
            "/api/v1/analysis/test-project/path",
            params={"from_fqn": "com.A"},
        )
        assert resp.status_code == 422  # Missing required param


# ── Communities ──────────────────────────────────────────


class TestCommunities:
    def test_list_communities(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {"communityId": 0, "size": 5, "members": ["A", "B", "C", "D", "E"]},
            {"communityId": 1, "size": 3, "members": ["X", "Y", "Z"]},
        ]

        resp = client.get("/api/v1/analysis/test-project/communities")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["communities"]) == 2
        assert data["communities"][0]["size"] == 5

    def test_communities_empty(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []

        resp = client.get("/api/v1/analysis/test-project/communities")

        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ── Circular Dependencies ────────────────────────────────


class TestCircularDependencies:
    def test_module_level_cycles(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {"cycle": ["mod.A", "mod.B", "mod.A"], "cycleLength": 2},
        ]

        resp = client.get(
            "/api/v1/analysis/test-project/circular-dependencies",
            params={"level": "module"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["level"] == "module"
        assert data["cycles"][0]["cycle_length"] == 2

    def test_class_level_cycles(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []

        resp = client.get(
            "/api/v1/analysis/test-project/circular-dependencies",
            params={"level": "class"},
        )

        assert resp.status_code == 200
        assert resp.json()["level"] == "class"

    def test_default_level_is_module(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []

        resp = client.get("/api/v1/analysis/test-project/circular-dependencies")
        assert resp.json()["level"] == "module"


# ── Dead Code ────────────────────────────────────────────


class TestDeadCode:
    def test_dead_functions(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {"fqn": "com.app.Util.unused", "name": "unused", "path": "Util.java", "line": 42, "loc": 15},
        ]

        resp = client.get(
            "/api/v1/analysis/test-project/dead-code",
            params={"type": "function"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["candidates"][0]["fqn"] == "com.app.Util.unused"

    def test_dead_code_default_type_is_function(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []

        resp = client.get("/api/v1/analysis/test-project/dead-code")
        assert resp.json()["type_filter"] == "function"


# ── Metrics ──────────────────────────────────────────────


class TestMetrics:
    def test_metrics_overview(self, client, mock_graph_store):
        # The endpoint calls query multiple times; mock them in sequence
        mock_graph_store.query_single.return_value = {
            "modules": 5, "classes": 30, "functions": 120, "totalLoc": 5000,
        }
        mock_graph_store.query.side_effect = [
            # most complex
            [{"fqn": "com.Complex", "name": "Complex", "value": 50}],
            # highest fan-in
            [{"fqn": "com.Popular", "name": "Popular", "value": 20}],
            # highest fan-out
            [{"fqn": "com.God", "name": "God", "value": 30}],
            # community count
            [{"count": 4}],
            # circular dep count
            [{"count": 2}],
            # dead code count
            [{"count": 8}],
        ]

        resp = client.get("/api/v1/analysis/test-project/metrics")

        assert resp.status_code == 200
        data = resp.json()
        assert data["overview"]["modules"] == 5
        assert data["overview"]["classes"] == 30
        assert len(data["most_complex"]) == 1
        assert data["community_count"] == 4


# ── Node Details ─────────────────────────────────────────


class TestNodeDetails:
    def test_node_details_with_callers_callees(self, client, mock_graph_store):
        mock_graph_store.query_single.return_value = {
            "fqn": "com.app.Service", "name": "Service", "type": "Class",
            "language": "java", "path": "Service.java", "line": 10,
            "loc": 100, "complexity": 15, "fan_in": 5, "fan_out": 8,
            "communityId": 2,
        }
        mock_graph_store.query.side_effect = [
            # callers
            [{"fqn": "com.app.Controller", "name": "Controller", "type": "Class"}],
            # callees
            [{"fqn": "com.app.Repository", "name": "Repository", "type": "Class"}],
        ]

        resp = client.get("/api/v1/analysis/test-project/node/com.app.Service/details")

        assert resp.status_code == 200
        data = resp.json()
        assert data["fqn"] == "com.app.Service"
        assert data["fan_in"] == 5
        assert data["community_id"] == 2
        assert len(data["callers"]) == 1
        assert len(data["callees"]) == 1

    def test_node_not_found(self, client, mock_graph_store):
        mock_graph_store.query_single.return_value = None

        resp = client.get("/api/v1/analysis/test-project/node/nonexistent/details")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_analysis_views_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.analysis_views'`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add tests/unit/test_analysis_views_api.py
git commit -m "test: add failing tests for Phase 3 analysis API endpoints"
```

---

## Task 3: Implement Analysis API Router

**Files:**
- Create: `cast-clone-backend/app/api/analysis_views.py`

- [ ] **Step 1: Write the router with all 7 endpoints**

```python
# app/api/analysis_views.py
"""Phase 3 analysis API endpoints.

All endpoints are backed by Cypher queries against Neo4j.
No complex backend logic — just query, shape, return.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.schemas.analysis_views import (
    AffectedNode,
    CircularDependenciesResponse,
    CircularDependency,
    CommunitiesResponse,
    CommunityInfo,
    DeadCodeCandidate,
    DeadCodeResponse,
    ImpactAnalysisResponse,
    ImpactSummary,
    MetricsResponse,
    NodeDetailResponse,
    OverviewStats,
    PathEdge,
    PathFinderResponse,
    PathNode,
    RankedItem,
)
from app.services.neo4j import Neo4jGraphStore, get_driver

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis-views"])


def get_graph_store() -> Neo4jGraphStore:
    return Neo4jGraphStore(get_driver())


# ── 1. Impact Analysis ──────────────────────────────────


@router.get(
    "/{project_id}/impact/{node_fqn:path}",
    response_model=ImpactAnalysisResponse,
)
async def get_impact_analysis(
    project_id: str,
    node_fqn: str,
    direction: str = Query("downstream", regex="^(downstream|upstream|both)$"),
    max_depth: int = Query(5, ge=1, le=10),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> ImpactAnalysisResponse:
    """Get blast radius for a node — what's affected if it changes."""
    affected_rows: list[dict[str, Any]] = []

    # NOTE: Cypher does not support parameterized variable-length path bounds,
    # so we use string concatenation for maxDepth. The value is validated as
    # an int (1-10) by FastAPI's Query() before reaching here.
    if direction in ("downstream", "both"):
        rows = await store.query(
            """
            MATCH path = (start {fqn: $startFqn})-[:CALLS|INJECTS|PRODUCES|WRITES*1.."""
            + str(max_depth)
            + """]->(affected)
            WHERE start.app_name = $appName
            WITH affected, min(length(path)) AS depth
            RETURN affected.fqn AS fqn,
                   affected.name AS name,
                   labels(affected)[0] AS type,
                   affected.path AS file,
                   depth
            ORDER BY depth, name
            """,
            {"startFqn": node_fqn, "appName": project_id},
        )
        affected_rows.extend(rows)

    if direction in ("upstream", "both"):
        rows = await store.query(
            """
            MATCH path = (dependent)-[:CALLS|INJECTS|CONSUMES|READS*1.."""
            + str(max_depth)
            + """]->(start {fqn: $startFqn})
            WHERE start.app_name = $appName
            WITH dependent, min(length(path)) AS depth
            RETURN dependent.fqn AS fqn,
                   dependent.name AS name,
                   labels(dependent)[0] AS type,
                   dependent.path AS file,
                   depth
            ORDER BY depth, name
            """,
            {"startFqn": node_fqn, "appName": project_id},
        )
        affected_rows.extend(rows)

    # Deduplicate by fqn (for "both" direction)
    seen: set[str] = set()
    unique_rows: list[dict[str, Any]] = []
    for row in affected_rows:
        if row["fqn"] not in seen:
            seen.add(row["fqn"])
            unique_rows.append(row)

    # Build summary
    by_type: dict[str, int] = {}
    by_depth: dict[str, int] = {}
    for row in unique_rows:
        t = row.get("type", "Unknown")
        by_type[t] = by_type.get(t, 0) + 1
        d = str(row.get("depth", 0))
        by_depth[d] = by_depth.get(d, 0) + 1

    affected = [
        AffectedNode(
            fqn=r["fqn"],
            name=r.get("name", ""),
            type=r.get("type", "Unknown"),
            file=r.get("file"),
            depth=r.get("depth", 0),
        )
        for r in unique_rows
    ]

    return ImpactAnalysisResponse(
        node=node_fqn,
        direction=direction,
        max_depth=max_depth,
        summary=ImpactSummary(
            total=len(affected),
            by_type=by_type,
            by_depth=by_depth,
        ),
        affected=affected,
    )


# ── 2. Path Finder ──────────────────────────────────────


@router.get(
    "/{project_id}/path",
    response_model=PathFinderResponse,
)
async def get_shortest_path(
    project_id: str,
    from_fqn: str = Query(...),
    to_fqn: str = Query(...),
    max_depth: int = Query(10, ge=1, le=20),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> PathFinderResponse:
    """Find shortest path between two nodes."""
    rows = await store.query(
        """
        MATCH path = shortestPath(
          (a {fqn: $fromFqn})-[*..""" + str(max_depth) + """]-(b {fqn: $toFqn})
        )
        WHERE a.app_name = $appName
        RETURN [n IN nodes(path) | {fqn: n.fqn, name: n.name, type: labels(n)[0]}] AS nodes,
               [r IN relationships(path) | {type: type(r), source: startNode(r).fqn, target: endNode(r).fqn}] AS edges,
               length(path) AS pathLength
        """,
        {"fromFqn": from_fqn, "toFqn": to_fqn, "appName": project_id},
    )

    if not rows:
        return PathFinderResponse(
            from_fqn=from_fqn,
            to_fqn=to_fqn,
            nodes=[],
            edges=[],
            path_length=0,
        )

    row = rows[0]
    return PathFinderResponse(
        from_fqn=from_fqn,
        to_fqn=to_fqn,
        nodes=[PathNode(**n) for n in row["nodes"]],
        edges=[PathEdge(**e) for e in row["edges"]],
        path_length=row["pathLength"],
    )


# ── 3. Communities ───────────────────────────────────────


@router.get(
    "/{project_id}/communities",
    response_model=CommunitiesResponse,
)
async def get_communities(
    project_id: str,
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> CommunitiesResponse:
    """List all detected communities with member counts."""
    rows = await store.query(
        """
        MATCH (c:Class {app_name: $appName})
        WHERE c.communityId IS NOT NULL
        WITH c.communityId AS communityId, collect(c.name) AS members, count(*) AS size
        RETURN communityId, size, members
        ORDER BY size DESC
        """,
        {"appName": project_id},
    )

    communities = [
        CommunityInfo(
            community_id=r["communityId"],
            size=r["size"],
            members=r["members"],
        )
        for r in rows
    ]

    return CommunitiesResponse(
        communities=communities,
        total=len(communities),
    )


# ── 4. Circular Dependencies ────────────────────────────


@router.get(
    "/{project_id}/circular-dependencies",
    response_model=CircularDependenciesResponse,
)
async def get_circular_dependencies(
    project_id: str,
    level: str = Query("module", regex="^(module|class)$"),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> CircularDependenciesResponse:
    """Detect circular dependency cycles at module or class level."""
    if level == "module":
        rows = await store.query(
            """
            MATCH path = (m:Module {app_name: $appName})-[:IMPORTS*2..6]->(m)
            WITH [n IN nodes(path) | n.name] AS cycle, length(path) AS cycleLength
            RETURN DISTINCT cycle, cycleLength
            ORDER BY cycleLength
            LIMIT 50
            """,
            {"appName": project_id},
        )
    else:
        rows = await store.query(
            """
            MATCH path = (c:Class {app_name: $appName})-[:DEPENDS_ON*2..4]->(c)
            WITH [n IN nodes(path) | n.fqn] AS cycle, length(path) AS cycleLength
            RETURN DISTINCT cycle, cycleLength
            ORDER BY cycleLength
            LIMIT 50
            """,
            {"appName": project_id},
        )

    cycles = [
        CircularDependency(cycle=r["cycle"], cycle_length=r["cycleLength"])
        for r in rows
    ]

    return CircularDependenciesResponse(
        cycles=cycles,
        total=len(cycles),
        level=level,
    )


# ── 5. Dead Code Candidates ─────────────────────────────


@router.get(
    "/{project_id}/dead-code",
    response_model=DeadCodeResponse,
)
async def get_dead_code(
    project_id: str,
    node_type: str = Query("function", alias="type", regex="^(function|class)$"),
    min_loc: int = Query(5, ge=0),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> DeadCodeResponse:
    """Find dead code candidates — functions/classes with no callers."""
    if node_type == "function":
        rows = await store.query(
            """
            MATCH (f:Function {app_name: $appName})
            WHERE NOT (f)<-[:CALLS]-()
              AND NOT (f)<-[:HANDLES]-(:APIEndpoint)
              AND NOT (f)<-[:CONSUMES]-(:MessageTopic)
              AND NOT f.is_constructor
              AND NOT any(ann IN coalesce(f.annotations, [])
                    WHERE ann IN ['PostConstruct', 'EventListener', 'Scheduled', 'Bean', 'Test'])
              AND coalesce(f.loc, 0) >= $minLoc
            RETURN f.fqn AS fqn, f.name AS name, f.path AS path, f.line AS line, f.loc AS loc
            ORDER BY f.loc DESC
            LIMIT 100
            """,
            {"appName": project_id, "minLoc": min_loc},
        )
    else:
        rows = await store.query(
            """
            MATCH (c:Class {app_name: $appName})
            WHERE NOT (c)<-[:DEPENDS_ON]-()
              AND NOT (c)<-[:INHERITS]-()
              AND NOT (c)<-[:IMPLEMENTS]-()
              AND NOT (c)<-[:INJECTS]-()
              AND coalesce(c.loc, 0) >= $minLoc
            RETURN c.fqn AS fqn, c.name AS name, c.path AS path, c.line AS line, c.loc AS loc
            ORDER BY c.loc DESC
            LIMIT 100
            """,
            {"appName": project_id, "minLoc": min_loc},
        )

    candidates = [
        DeadCodeCandidate(
            fqn=r["fqn"],
            name=r.get("name", ""),
            path=r.get("path"),
            line=r.get("line"),
            loc=r.get("loc"),
        )
        for r in rows
    ]

    return DeadCodeResponse(
        candidates=candidates,
        total=len(candidates),
        type_filter=node_type,
    )


# ── 6. Metrics Dashboard ────────────────────────────────


@router.get(
    "/{project_id}/metrics",
    response_model=MetricsResponse,
)
async def get_metrics(
    project_id: str,
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> MetricsResponse:
    """Get overview dashboard data — stats, top-10 lists, counts."""
    # Overview stats
    overview_row = await store.query_single(
        """
        MATCH (app:Application {name: $appName})
        OPTIONAL MATCH (app)-[:CONTAINS*1..2]->(m:Module)
        OPTIONAL MATCH (m)-[:CONTAINS]->(c:Class)
        OPTIONAL MATCH (c)-[:CONTAINS]->(f:Function)
        RETURN count(DISTINCT m) AS modules,
               count(DISTINCT c) AS classes,
               count(DISTINCT f) AS functions,
               sum(DISTINCT c.loc) AS totalLoc
        """,
        {"appName": project_id},
    )

    overview = OverviewStats()
    if overview_row:
        overview = OverviewStats(
            modules=overview_row.get("modules", 0) or 0,
            classes=overview_row.get("classes", 0) or 0,
            functions=overview_row.get("functions", 0) or 0,
            total_loc=overview_row.get("totalLoc", 0) or 0,
        )

    # Most complex classes (top 10)
    complex_rows = await store.query(
        """
        MATCH (c:Class {app_name: $appName})
        WHERE c.complexity IS NOT NULL
        RETURN c.fqn AS fqn, c.name AS name, c.complexity AS value
        ORDER BY c.complexity DESC
        LIMIT 10
        """,
        {"appName": project_id},
    )

    # Highest fan-in
    fan_in_rows = await store.query(
        """
        MATCH (caller)-[:CALLS]->(target:Function {app_name: $appName})
        WITH target, count(DISTINCT caller) AS fanIn
        RETURN target.fqn AS fqn, target.name AS name, fanIn AS value
        ORDER BY fanIn DESC
        LIMIT 10
        """,
        {"appName": project_id},
    )

    # Highest fan-out
    fan_out_rows = await store.query(
        """
        MATCH (source:Function {app_name: $appName})-[:CALLS]->(callee)
        WITH source, count(DISTINCT callee) AS fanOut
        RETURN source.fqn AS fqn, source.name AS name, fanOut AS value
        ORDER BY fanOut DESC
        LIMIT 10
        """,
        {"appName": project_id},
    )

    # Community count
    community_rows = await store.query(
        """
        MATCH (c:Class {app_name: $appName})
        WHERE c.communityId IS NOT NULL
        RETURN count(DISTINCT c.communityId) AS count
        """,
        {"appName": project_id},
    )
    community_count = community_rows[0]["count"] if community_rows else 0

    # Circular dependency count
    cycle_rows = await store.query(
        """
        MATCH path = (m:Module {app_name: $appName})-[:IMPORTS*2..6]->(m)
        WITH [n IN nodes(path) | n.name] AS cycle
        RETURN count(DISTINCT cycle) AS count
        """,
        {"appName": project_id},
    )
    cycle_count = cycle_rows[0]["count"] if cycle_rows else 0

    # Dead code count
    dead_rows = await store.query(
        """
        MATCH (f:Function {app_name: $appName})
        WHERE NOT (f)<-[:CALLS]-()
          AND NOT (f)<-[:HANDLES]-(:APIEndpoint)
          AND NOT f.is_constructor
          AND coalesce(f.loc, 0) >= 5
        RETURN count(f) AS count
        """,
        {"appName": project_id},
    )
    dead_count = dead_rows[0]["count"] if dead_rows else 0

    def _to_ranked(rows: list[dict]) -> list[RankedItem]:
        return [RankedItem(fqn=r["fqn"], name=r["name"], value=r["value"]) for r in rows]

    return MetricsResponse(
        overview=overview,
        most_complex=_to_ranked(complex_rows),
        highest_fan_in=_to_ranked(fan_in_rows),
        highest_fan_out=_to_ranked(fan_out_rows),
        community_count=community_count,
        circular_dependency_count=cycle_count,
        dead_code_count=dead_count,
    )


# ── 7. Enhanced Node Details ─────────────────────────────


@router.get(
    "/{project_id}/node/{node_fqn:path}/details",
    response_model=NodeDetailResponse,
)
async def get_node_details(
    project_id: str,
    node_fqn: str,
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> NodeDetailResponse:
    """Get enhanced node details with fan-in, fan-out, community, callers, callees."""
    # Fetch the node
    node_row = await store.query_single(
        """
        MATCH (n {fqn: $fqn, app_name: $appName})
        RETURN n.fqn AS fqn, n.name AS name, labels(n)[0] AS type,
               n.language AS language, n.path AS path, n.line AS line,
               n.loc AS loc, n.complexity AS complexity,
               n.fan_in AS fan_in, n.fan_out AS fan_out,
               n.communityId AS communityId
        """,
        {"fqn": node_fqn, "appName": project_id},
    )

    if not node_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node {node_fqn} not found in project {project_id}",
        )

    # Callers (who calls this node?)
    caller_rows = await store.query(
        """
        MATCH (caller)-[:CALLS]->(n {fqn: $fqn, app_name: $appName})
        RETURN DISTINCT caller.fqn AS fqn, caller.name AS name, labels(caller)[0] AS type
        ORDER BY name
        LIMIT 50
        """,
        {"fqn": node_fqn, "appName": project_id},
    )

    # Callees (what does this node call?)
    callee_rows = await store.query(
        """
        MATCH (n {fqn: $fqn, app_name: $appName})-[:CALLS]->(callee)
        RETURN DISTINCT callee.fqn AS fqn, callee.name AS name, labels(callee)[0] AS type
        ORDER BY name
        LIMIT 50
        """,
        {"fqn": node_fqn, "appName": project_id},
    )

    return NodeDetailResponse(
        fqn=node_row["fqn"],
        name=node_row.get("name", ""),
        type=node_row.get("type", "Unknown"),
        language=node_row.get("language"),
        path=node_row.get("path"),
        line=node_row.get("line"),
        loc=node_row.get("loc"),
        complexity=node_row.get("complexity"),
        fan_in=node_row.get("fan_in", 0) or 0,
        fan_out=node_row.get("fan_out", 0) or 0,
        community_id=node_row.get("communityId"),
        callers=[PathNode(**r) for r in caller_rows],
        callees=[PathNode(**r) for r in callee_rows],
    )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_analysis_views_api.py -v`
Expected: FAIL — router not yet registered in main.py

- [ ] **Step 3: Commit the router file**

```bash
cd cast-clone-backend
git add app/api/analysis_views.py
git commit -m "feat(phase3): implement 7 analysis API endpoints"
```

---

## Task 4: Register Router in Main App

**Files:**
- Modify: `cast-clone-backend/app/api/__init__.py`
- Modify: `cast-clone-backend/app/main.py`

- [ ] **Step 1: Export the new router from api/__init__.py**

Add to `app/api/__init__.py`:

```python
from app.api.analysis_views import router as analysis_views_router
```

And add `analysis_views_router` to the `__all__` list if one exists.

- [ ] **Step 2: Register in main.py**

Add to `app/main.py` alongside the other router registrations:

```python
from app.api.analysis_views import router as analysis_views_router

# In the router registration section:
app.include_router(analysis_views_router)
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_analysis_views_api.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend
git add app/api/__init__.py app/main.py
git commit -m "feat(phase3): register analysis_views router in FastAPI app"
```

---

## Task 5: Run Full Test Suite + Lint

- [ ] **Step 1: Run all unit tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run linting**

Run: `cd cast-clone-backend && uv run ruff check app/api/analysis_views.py app/schemas/analysis_views.py`
Expected: No errors

- [ ] **Step 3: Fix any issues and commit**

```bash
cd cast-clone-backend
git add -A
git commit -m "fix: address lint issues from Phase 3 M2"
```
