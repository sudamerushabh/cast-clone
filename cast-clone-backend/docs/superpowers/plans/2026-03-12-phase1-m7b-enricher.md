# M7b: Graph Enricher (Stage 7) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Stage 7 of the analysis pipeline — the Graph Enricher. This stage computes derived metrics (fan-in/fan-out), aggregates class-level DEPENDS_ON and module-level IMPORTS edges, assigns architectural layers with Layer/Component nodes, and runs in-memory community detection. It operates entirely on the in-memory SymbolGraph before data is written to Neo4j in Stage 8.

**Architecture:** Pure in-memory graph transformation on the shared `AnalysisContext.graph`. No I/O, no database access. This stage is non-critical — if it fails, the pipeline continues with a warning (metrics/layers/communities just won't be present). Community detection uses a simple Python label propagation algorithm since Neo4j GDS is not available until after Stage 8 writes data.

**Tech Stack:** Python 3.12, dataclasses, structlog, collections (defaultdict, deque), pytest + pytest-asyncio

**Dependencies from M1:** `GraphNode`, `GraphEdge`, `SymbolGraph`, `AnalysisContext`, `NodeKind`, `EdgeKind`, `Confidence`

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       ├── __init__.py              # MODIFY — add enricher import
│       └── enricher.py              # CREATE — Stage 7: Graph Enricher
├── tests/
│   └── unit/
│       └── test_enricher.py         # CREATE
```

---

## Task 1: Write the Failing Tests

**Files:**
- Create: `tests/unit/test_enricher.py`

- [ ] **Step 1: Write the full test file**

```python
# tests/unit/test_enricher.py
"""Tests for Stage 7: Graph Enricher."""

import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext
from app.stages.enricher import (
    enrich_graph,
    compute_fan_metrics,
    aggregate_class_depends_on,
    aggregate_module_imports,
    assign_architectural_layers,
    detect_communities,
)


# ── Helpers ──────────────────────────────────────────────


def _make_context(graph: SymbolGraph | None = None) -> AnalysisContext:
    ctx = AnalysisContext(project_id="test-project")
    if graph is not None:
        ctx.graph = graph
    return ctx


def _make_class(fqn: str, module_fqn: str | None = None) -> GraphNode:
    node = GraphNode(fqn=fqn, name=fqn.split(".")[-1], kind=NodeKind.CLASS)
    if module_fqn is not None:
        node.properties["module_fqn"] = module_fqn
    return node


def _make_function(fqn: str) -> GraphNode:
    return GraphNode(fqn=fqn, name=fqn.split(".")[-1], kind=NodeKind.FUNCTION)


def _make_module(fqn: str) -> GraphNode:
    return GraphNode(fqn=fqn, name=fqn.split(".")[-1], kind=NodeKind.MODULE)


def _calls_edge(src: str, tgt: str) -> GraphEdge:
    return GraphEdge(source_fqn=src, target_fqn=tgt, kind=EdgeKind.CALLS)


def _contains_edge(src: str, tgt: str) -> GraphEdge:
    return GraphEdge(source_fqn=src, target_fqn=tgt, kind=EdgeKind.CONTAINS)


def _injects_edge(src: str, tgt: str) -> GraphEdge:
    return GraphEdge(source_fqn=src, target_fqn=tgt, kind=EdgeKind.INJECTS)


# ── Test 1: Fan-in / Fan-out ────────────────────────────


class TestFanMetrics:
    def test_fan_in_fan_out_basic(self):
        """Graph with known CALLS edges: verify correct counts on CLASS nodes."""
        g = SymbolGraph()

        # Classes
        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_class("com.app.B"))
        g.add_node(_make_class("com.app.C"))

        # Methods
        g.add_node(_make_function("com.app.A.m1"))
        g.add_node(_make_function("com.app.A.m2"))
        g.add_node(_make_function("com.app.B.m1"))
        g.add_node(_make_function("com.app.C.m1"))

        # Containment: class -> method
        g.add_edge(_contains_edge("com.app.A", "com.app.A.m1"))
        g.add_edge(_contains_edge("com.app.A", "com.app.A.m2"))
        g.add_edge(_contains_edge("com.app.B", "com.app.B.m1"))
        g.add_edge(_contains_edge("com.app.C", "com.app.C.m1"))

        # Calls: A.m1 -> B.m1, A.m2 -> B.m1, B.m1 -> C.m1
        g.add_edge(_calls_edge("com.app.A.m1", "com.app.B.m1"))
        g.add_edge(_calls_edge("com.app.A.m2", "com.app.B.m1"))
        g.add_edge(_calls_edge("com.app.B.m1", "com.app.C.m1"))

        compute_fan_metrics(g)

        # A: fan_in=0 (nobody calls A's methods), fan_out=2 (A.m1->B.m1, A.m2->B.m1)
        assert g.get_node("com.app.A").properties["fan_in"] == 0
        assert g.get_node("com.app.A").properties["fan_out"] == 2

        # B: fan_in=2 (A.m1->B.m1, A.m2->B.m1), fan_out=1 (B.m1->C.m1)
        assert g.get_node("com.app.B").properties["fan_in"] == 2
        assert g.get_node("com.app.B").properties["fan_out"] == 1

        # C: fan_in=1 (B.m1->C.m1), fan_out=0
        assert g.get_node("com.app.C").properties["fan_in"] == 1
        assert g.get_node("com.app.C").properties["fan_out"] == 0

    def test_fan_in_includes_injects_edges(self):
        """INJECTS edges should also count toward fan_in."""
        g = SymbolGraph()
        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_class("com.app.B"))

        # A injects B (DI)
        g.add_edge(_injects_edge("com.app.A", "com.app.B"))

        compute_fan_metrics(g)

        assert g.get_node("com.app.B").properties["fan_in"] == 1


# ── Test 2: Class-level DEPENDS_ON Aggregation ──────────


class TestClassDependsOn:
    def test_methods_calling_across_classes_create_depends_on(self):
        """Methods calling across classes -> DEPENDS_ON edges with correct weights."""
        g = SymbolGraph()

        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_class("com.app.B"))
        g.add_node(_make_function("com.app.A.m1"))
        g.add_node(_make_function("com.app.A.m2"))
        g.add_node(_make_function("com.app.B.m1"))
        g.add_node(_make_function("com.app.B.m2"))

        g.add_edge(_contains_edge("com.app.A", "com.app.A.m1"))
        g.add_edge(_contains_edge("com.app.A", "com.app.A.m2"))
        g.add_edge(_contains_edge("com.app.B", "com.app.B.m1"))
        g.add_edge(_contains_edge("com.app.B", "com.app.B.m2"))

        # A.m1 -> B.m1, A.m1 -> B.m2, A.m2 -> B.m1
        g.add_edge(_calls_edge("com.app.A.m1", "com.app.B.m1"))
        g.add_edge(_calls_edge("com.app.A.m1", "com.app.B.m2"))
        g.add_edge(_calls_edge("com.app.A.m2", "com.app.B.m1"))

        aggregate_class_depends_on(g)

        depends_on = [
            e for e in g.edges
            if e.kind == EdgeKind.DEPENDS_ON
            and e.source_fqn == "com.app.A"
            and e.target_fqn == "com.app.B"
        ]
        assert len(depends_on) == 1
        assert depends_on[0].properties["weight"] == 3

    def test_no_duplicate_depends_on(self):
        """If DEPENDS_ON already exists between two classes, don't add another."""
        g = SymbolGraph()

        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_class("com.app.B"))
        g.add_node(_make_function("com.app.A.m1"))
        g.add_node(_make_function("com.app.B.m1"))

        g.add_edge(_contains_edge("com.app.A", "com.app.A.m1"))
        g.add_edge(_contains_edge("com.app.B", "com.app.B.m1"))
        g.add_edge(_calls_edge("com.app.A.m1", "com.app.B.m1"))

        # Pre-existing DEPENDS_ON edge
        existing = GraphEdge(
            source_fqn="com.app.A",
            target_fqn="com.app.B",
            kind=EdgeKind.DEPENDS_ON,
            properties={"weight": 99},
        )
        g.add_edge(existing)

        aggregate_class_depends_on(g)

        depends_on = [
            e for e in g.edges
            if e.kind == EdgeKind.DEPENDS_ON
            and e.source_fqn == "com.app.A"
            and e.target_fqn == "com.app.B"
        ]
        # Should still be exactly 1 (the pre-existing one is left as-is)
        assert len(depends_on) == 1


# ── Test 3: Module-level IMPORTS Aggregation ─────────────


class TestModuleImports:
    def test_classes_across_modules_create_imports(self):
        """Classes across modules -> module-level IMPORTS edges."""
        g = SymbolGraph()

        # Modules
        g.add_node(_make_module("com.app.user"))
        g.add_node(_make_module("com.app.order"))

        # Classes with module_fqn property
        g.add_node(_make_class("com.app.user.UserService", module_fqn="com.app.user"))
        g.add_node(_make_class("com.app.order.OrderService", module_fqn="com.app.order"))

        # Module containment
        g.add_edge(_contains_edge("com.app.user", "com.app.user.UserService"))
        g.add_edge(_contains_edge("com.app.order", "com.app.order.OrderService"))

        # Class-level DEPENDS_ON
        g.add_edge(GraphEdge(
            source_fqn="com.app.user.UserService",
            target_fqn="com.app.order.OrderService",
            kind=EdgeKind.DEPENDS_ON,
            properties={"weight": 5},
        ))

        aggregate_module_imports(g)

        imports = [
            e for e in g.edges
            if e.kind == EdgeKind.IMPORTS
            and e.source_fqn == "com.app.user"
            and e.target_fqn == "com.app.order"
        ]
        assert len(imports) == 1
        assert imports[0].properties["weight"] == 5

    def test_multiple_classes_sum_weights(self):
        """Multiple class-level DEPENDS_ON between modules -> sum weights."""
        g = SymbolGraph()

        g.add_node(_make_module("mod.A"))
        g.add_node(_make_module("mod.B"))
        g.add_node(_make_class("mod.A.C1", module_fqn="mod.A"))
        g.add_node(_make_class("mod.A.C2", module_fqn="mod.A"))
        g.add_node(_make_class("mod.B.C1", module_fqn="mod.B"))

        g.add_edge(_contains_edge("mod.A", "mod.A.C1"))
        g.add_edge(_contains_edge("mod.A", "mod.A.C2"))
        g.add_edge(_contains_edge("mod.B", "mod.B.C1"))

        g.add_edge(GraphEdge(
            source_fqn="mod.A.C1",
            target_fqn="mod.B.C1",
            kind=EdgeKind.DEPENDS_ON,
            properties={"weight": 3},
        ))
        g.add_edge(GraphEdge(
            source_fqn="mod.A.C2",
            target_fqn="mod.B.C1",
            kind=EdgeKind.DEPENDS_ON,
            properties={"weight": 2},
        ))

        aggregate_module_imports(g)

        imports = [
            e for e in g.edges
            if e.kind == EdgeKind.IMPORTS
            and e.source_fqn == "mod.A"
            and e.target_fqn == "mod.B"
        ]
        assert len(imports) == 1
        assert imports[0].properties["weight"] == 5


# ── Test 4: No Self-Edges ───────────────────────────────


class TestNoSelfEdges:
    def test_class_does_not_depend_on_itself(self):
        """Internal method calls within the same class must NOT produce a DEPENDS_ON self-edge."""
        g = SymbolGraph()

        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_function("com.app.A.m1"))
        g.add_node(_make_function("com.app.A.m2"))

        g.add_edge(_contains_edge("com.app.A", "com.app.A.m1"))
        g.add_edge(_contains_edge("com.app.A", "com.app.A.m2"))
        g.add_edge(_calls_edge("com.app.A.m1", "com.app.A.m2"))

        aggregate_class_depends_on(g)

        self_edges = [
            e for e in g.edges
            if e.kind == EdgeKind.DEPENDS_ON
            and e.source_fqn == "com.app.A"
            and e.target_fqn == "com.app.A"
        ]
        assert len(self_edges) == 0

    def test_module_does_not_import_itself(self):
        """Classes in the same module depending on each other must NOT produce a module self-IMPORTS."""
        g = SymbolGraph()

        g.add_node(_make_module("com.app"))
        g.add_node(_make_class("com.app.A", module_fqn="com.app"))
        g.add_node(_make_class("com.app.B", module_fqn="com.app"))

        g.add_edge(_contains_edge("com.app", "com.app.A"))
        g.add_edge(_contains_edge("com.app", "com.app.B"))
        g.add_edge(GraphEdge(
            source_fqn="com.app.A",
            target_fqn="com.app.B",
            kind=EdgeKind.DEPENDS_ON,
            properties={"weight": 2},
        ))

        aggregate_module_imports(g)

        self_imports = [
            e for e in g.edges
            if e.kind == EdgeKind.IMPORTS
            and e.source_fqn == "com.app"
            and e.target_fqn == "com.app"
        ]
        assert len(self_imports) == 0


# ── Test 5: Layer Assignment ─────────────────────────────


class TestLayerAssignment:
    def test_layer_nodes_created_from_assignments(self):
        """Nodes with layer_assignments produce Layer + Component nodes with CONTAINS edges."""
        g = SymbolGraph()

        # Classes with layer hints (set by framework plugins)
        svc = _make_class("com.app.UserService")
        svc.properties["layer"] = "Business Logic"
        g.add_node(svc)

        ctrl = _make_class("com.app.UserController")
        ctrl.properties["layer"] = "Presentation"
        g.add_node(ctrl)

        repo = _make_class("com.app.UserRepository")
        repo.properties["layer"] = "Data Access"
        g.add_node(repo)

        assign_architectural_layers(g, app_name="test-app")

        # Layer nodes should exist
        layer_nodes = [n for n in g.nodes.values() if n.kind == NodeKind.LAYER]
        layer_names = {n.name for n in layer_nodes}
        assert "Business Logic" in layer_names
        assert "Presentation" in layer_names
        assert "Data Access" in layer_names

        # Each layer should have a CONTAINS edge to the class
        contains_from_layers = [
            e for e in g.edges
            if e.kind == EdgeKind.CONTAINS
            and g.get_node(e.source_fqn) is not None
            and g.get_node(e.source_fqn).kind == NodeKind.LAYER
        ]
        assert len(contains_from_layers) == 3

    def test_layer_node_count_property(self):
        """Layer nodes should have node_count reflecting member count."""
        g = SymbolGraph()

        c1 = _make_class("com.app.A")
        c1.properties["layer"] = "Business Logic"
        g.add_node(c1)

        c2 = _make_class("com.app.B")
        c2.properties["layer"] = "Business Logic"
        g.add_node(c2)

        assign_architectural_layers(g, app_name="test-app")

        bl_layer = g.get_node("layer:test-app:Business Logic")
        assert bl_layer is not None
        assert bl_layer.properties["node_count"] == 2


# ── Test 6: Empty Graph ─────────────────────────────────


class TestEmptyGraph:
    @pytest.mark.asyncio
    async def test_empty_graph_no_crash(self):
        """Enriching an empty graph should not crash."""
        ctx = _make_context(SymbolGraph())
        await enrich_graph(ctx)
        assert ctx.community_count == 0
        assert ctx.warnings == [] or all(isinstance(w, str) for w in ctx.warnings)


# ── Test 7: Single Class ────────────────────────────────


class TestSingleClass:
    def test_single_class_zero_metrics(self):
        """One class with no calls: fan_in=0, fan_out=0."""
        g = SymbolGraph()
        g.add_node(_make_class("com.app.Lonely"))
        g.add_node(_make_function("com.app.Lonely.doNothing"))
        g.add_edge(_contains_edge("com.app.Lonely", "com.app.Lonely.doNothing"))

        compute_fan_metrics(g)

        assert g.get_node("com.app.Lonely").properties["fan_in"] == 0
        assert g.get_node("com.app.Lonely").properties["fan_out"] == 0


# ── Test 8: Community Detection ──────────────────────────


class TestCommunityDetection:
    def test_two_disconnected_components(self):
        """Two disconnected clusters should yield 2 communities."""
        g = SymbolGraph()

        # Cluster 1: A -> B
        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_class("com.app.B"))
        g.add_edge(GraphEdge(
            source_fqn="com.app.A",
            target_fqn="com.app.B",
            kind=EdgeKind.DEPENDS_ON,
            properties={"weight": 1},
        ))

        # Cluster 2: X -> Y
        g.add_node(_make_class("com.app.X"))
        g.add_node(_make_class("com.app.Y"))
        g.add_edge(GraphEdge(
            source_fqn="com.app.X",
            target_fqn="com.app.Y",
            kind=EdgeKind.DEPENDS_ON,
            properties={"weight": 1},
        ))

        count = detect_communities(g, app_name="test-app")

        assert count == 2

        # Community nodes should exist
        community_nodes = [n for n in g.nodes.values() if n.kind == NodeKind.COMMUNITY]
        assert len(community_nodes) == 2

        # Each class should have a community_id property
        for fqn in ["com.app.A", "com.app.B", "com.app.X", "com.app.Y"]:
            node = g.get_node(fqn)
            assert "community_id" in node.properties

        # A and B should be in the same community
        assert (
            g.get_node("com.app.A").properties["community_id"]
            == g.get_node("com.app.B").properties["community_id"]
        )

        # X and Y should be in the same community
        assert (
            g.get_node("com.app.X").properties["community_id"]
            == g.get_node("com.app.Y").properties["community_id"]
        )

        # But different from A/B's community
        assert (
            g.get_node("com.app.A").properties["community_id"]
            != g.get_node("com.app.X").properties["community_id"]
        )

    def test_single_connected_component(self):
        """Fully connected graph -> 1 community."""
        g = SymbolGraph()

        g.add_node(_make_class("a.A"))
        g.add_node(_make_class("a.B"))
        g.add_node(_make_class("a.C"))
        g.add_edge(GraphEdge(
            source_fqn="a.A", target_fqn="a.B",
            kind=EdgeKind.DEPENDS_ON, properties={"weight": 1},
        ))
        g.add_edge(GraphEdge(
            source_fqn="a.B", target_fqn="a.C",
            kind=EdgeKind.DEPENDS_ON, properties={"weight": 1},
        ))

        count = detect_communities(g, app_name="test-app")
        assert count == 1

    def test_community_includes_edges(self):
        """Community nodes should have INCLUDES edges to their member classes."""
        g = SymbolGraph()
        g.add_node(_make_class("a.A"))
        g.add_node(_make_class("a.B"))
        g.add_edge(GraphEdge(
            source_fqn="a.A", target_fqn="a.B",
            kind=EdgeKind.DEPENDS_ON, properties={"weight": 1},
        ))

        detect_communities(g, app_name="test-app")

        includes_edges = [e for e in g.edges if e.kind == EdgeKind.INCLUDES]
        assert len(includes_edges) == 2  # One for each class


# ── Test 9: Full Integration ─────────────────────────────


class TestEnrichGraphIntegration:
    @pytest.mark.asyncio
    async def test_realistic_graph_all_enrichments(self):
        """Realistic graph with multiple classes across modules — all enrichments applied."""
        g = SymbolGraph()

        # Modules
        g.add_node(_make_module("com.app.web"))
        g.add_node(_make_module("com.app.service"))
        g.add_node(_make_module("com.app.data"))

        # Classes with layer assignments
        ctrl = _make_class("com.app.web.UserController", module_fqn="com.app.web")
        ctrl.properties["layer"] = "Presentation"
        g.add_node(ctrl)

        svc = _make_class("com.app.service.UserService", module_fqn="com.app.service")
        svc.properties["layer"] = "Business Logic"
        g.add_node(svc)

        repo = _make_class("com.app.data.UserRepository", module_fqn="com.app.data")
        repo.properties["layer"] = "Data Access"
        g.add_node(repo)

        # Methods
        g.add_node(_make_function("com.app.web.UserController.getUser"))
        g.add_node(_make_function("com.app.service.UserService.findUser"))
        g.add_node(_make_function("com.app.data.UserRepository.findById"))

        # Containment: module -> class
        g.add_edge(_contains_edge("com.app.web", "com.app.web.UserController"))
        g.add_edge(_contains_edge("com.app.service", "com.app.service.UserService"))
        g.add_edge(_contains_edge("com.app.data", "com.app.data.UserRepository"))

        # Containment: class -> method
        g.add_edge(_contains_edge("com.app.web.UserController", "com.app.web.UserController.getUser"))
        g.add_edge(_contains_edge("com.app.service.UserService", "com.app.service.UserService.findUser"))
        g.add_edge(_contains_edge("com.app.data.UserRepository", "com.app.data.UserRepository.findById"))

        # Call chain: controller -> service -> repository
        g.add_edge(_calls_edge("com.app.web.UserController.getUser", "com.app.service.UserService.findUser"))
        g.add_edge(_calls_edge("com.app.service.UserService.findUser", "com.app.data.UserRepository.findById"))

        ctx = _make_context(g)
        await enrich_graph(ctx)

        # 1. Fan metrics computed
        assert g.get_node("com.app.web.UserController").properties["fan_in"] == 0
        assert g.get_node("com.app.web.UserController").properties["fan_out"] == 1
        assert g.get_node("com.app.service.UserService").properties["fan_in"] == 1
        assert g.get_node("com.app.service.UserService").properties["fan_out"] == 1
        assert g.get_node("com.app.data.UserRepository").properties["fan_in"] == 1
        assert g.get_node("com.app.data.UserRepository").properties["fan_out"] == 0

        # 2. Class-level DEPENDS_ON edges created
        depends_on_edges = [e for e in g.edges if e.kind == EdgeKind.DEPENDS_ON]
        assert len(depends_on_edges) >= 2  # ctrl->svc, svc->repo

        # 3. Module-level IMPORTS edges created
        import_edges = [e for e in g.edges if e.kind == EdgeKind.IMPORTS]
        assert len(import_edges) >= 2  # web->service, service->data

        # 4. Layer nodes created
        layer_nodes = [n for n in g.nodes.values() if n.kind == NodeKind.LAYER]
        assert len(layer_nodes) == 3

        # 5. Community detection ran
        assert ctx.community_count >= 1
        community_nodes = [n for n in g.nodes.values() if n.kind == NodeKind.COMMUNITY]
        assert len(community_nodes) >= 1


# ── Test 10: Isolated Class in Community Detection ───────


class TestIsolatedCommunity:
    def test_isolated_class_gets_own_community(self):
        """A class with no DEPENDS_ON edges should still get a community assignment."""
        g = SymbolGraph()
        g.add_node(_make_class("com.app.Isolated"))

        count = detect_communities(g, app_name="test-app")

        assert count == 1
        assert "community_id" in g.get_node("com.app.Isolated").properties
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_enricher.py -v`
Expected: FAIL (ImportError — `app.stages.enricher` does not exist)

---

## Task 2: Implement the Graph Enricher

**Files:**
- Create: `app/stages/enricher.py`

- [ ] **Step 3: Implement the enricher module**

```python
# app/stages/enricher.py
"""Stage 7: Graph Enricher.

Computes derived metrics, aggregates class-level DEPENDS_ON and module-level
IMPORTS edges, assigns architectural layers, and runs community detection.

This stage operates entirely in-memory on the SymbolGraph. It is non-critical:
if it fails, the pipeline continues with a warning.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import TYPE_CHECKING

import structlog

from app.models.enums import EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode

if TYPE_CHECKING:
    from app.models.context import AnalysisContext
    from app.models.graph import SymbolGraph

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ── Public API ───────────────────────────────────────────


async def enrich_graph(context: AnalysisContext) -> None:
    """Run all enrichment steps on the analysis context's graph.

    Steps (in order):
    1. Compute fan-in/fan-out metrics on CLASS nodes
    2. Aggregate class-level DEPENDS_ON edges from method CALLS
    3. Aggregate module-level IMPORTS edges from class DEPENDS_ON
    4. Assign architectural layers (create Layer nodes + CONTAINS edges)
    5. Detect communities (create Community nodes + INCLUDES edges)

    Non-critical: catches exceptions per step, logs warnings, continues.
    """
    graph = context.graph
    app_name = context.project_id

    logger.info("enricher.start", node_count=graph.node_count, edge_count=graph.edge_count)

    # Step 1: Fan metrics
    try:
        compute_fan_metrics(graph)
        logger.info("enricher.fan_metrics.done")
    except Exception as exc:
        msg = f"Fan metrics computation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.fan_metrics.failed", error=str(exc))

    # Step 2: Class-level DEPENDS_ON
    try:
        depends_on_count = aggregate_class_depends_on(graph)
        logger.info("enricher.depends_on.done", edges_created=depends_on_count)
    except Exception as exc:
        msg = f"Class DEPENDS_ON aggregation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.depends_on.failed", error=str(exc))

    # Step 3: Module-level IMPORTS
    try:
        imports_count = aggregate_module_imports(graph)
        logger.info("enricher.imports.done", edges_created=imports_count)
    except Exception as exc:
        msg = f"Module IMPORTS aggregation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.imports.failed", error=str(exc))

    # Step 4: Architectural layers
    try:
        layer_count = assign_architectural_layers(graph, app_name=app_name)
        logger.info("enricher.layers.done", layers_created=layer_count)
    except Exception as exc:
        msg = f"Layer assignment failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.layers.failed", error=str(exc))

    # Step 5: Community detection
    try:
        community_count = detect_communities(graph, app_name=app_name)
        context.community_count = community_count
        logger.info("enricher.communities.done", community_count=community_count)
    except Exception as exc:
        msg = f"Community detection failed: {exc}"
        context.warnings.append(msg)
        context.community_count = 0
        logger.warning("enricher.communities.failed", error=str(exc))

    logger.info(
        "enricher.done",
        node_count=graph.node_count,
        edge_count=graph.edge_count,
        community_count=context.community_count,
    )


# ── Step 1: Fan-In / Fan-Out Metrics ────────────────────


def compute_fan_metrics(graph: SymbolGraph) -> None:
    """Compute fan-in and fan-out for each CLASS node.

    Fan-in:  count of incoming CALLS edges to this class's methods
             + incoming INJECTS edges to this class.
    Fan-out: count of outgoing CALLS edges from this class's methods.

    Results stored in ``node.properties["fan_in"]`` and ``node.properties["fan_out"]``.
    """
    class_nodes = {
        fqn: node for fqn, node in graph.nodes.items()
        if node.kind == NodeKind.CLASS
    }

    if not class_nodes:
        return

    # Build method -> owning class lookup from CONTAINS edges
    method_to_class: dict[str, str] = {}
    for edge in graph.edges:
        if edge.kind == EdgeKind.CONTAINS:
            source_node = graph.get_node(edge.source_fqn)
            target_node = graph.get_node(edge.target_fqn)
            if (
                source_node is not None
                and source_node.kind == NodeKind.CLASS
                and target_node is not None
                and target_node.kind == NodeKind.FUNCTION
            ):
                method_to_class[edge.target_fqn] = edge.source_fqn

    # Count fan-in and fan-out per class
    fan_in: dict[str, int] = defaultdict(int)
    fan_out: dict[str, int] = defaultdict(int)

    for edge in graph.edges:
        if edge.kind == EdgeKind.CALLS:
            src_class = method_to_class.get(edge.source_fqn)
            tgt_class = method_to_class.get(edge.target_fqn)

            if tgt_class is not None and tgt_class in class_nodes:
                fan_in[tgt_class] += 1
            if src_class is not None and src_class in class_nodes:
                fan_out[src_class] += 1

        elif edge.kind == EdgeKind.INJECTS:
            # INJECTS is class-to-class, counts as fan_in for target
            if edge.target_fqn in class_nodes:
                fan_in[edge.target_fqn] += 1

    # Write metrics to node properties
    for fqn in class_nodes:
        class_nodes[fqn].properties["fan_in"] = fan_in.get(fqn, 0)
        class_nodes[fqn].properties["fan_out"] = fan_out.get(fqn, 0)


# ── Step 2: Aggregate Class-Level DEPENDS_ON ─────────────


def aggregate_class_depends_on(graph: SymbolGraph) -> int:
    """Aggregate method-level CALLS edges into class-level DEPENDS_ON edges.

    If class A has methods that CALL methods in class B (A != B),
    creates ``A -[:DEPENDS_ON {weight: N}]-> B`` where N is the number
    of distinct method-to-method CALLS edges between the two classes.

    Skips pairs where a DEPENDS_ON edge already exists.

    Returns the number of new DEPENDS_ON edges created.
    """
    class_nodes = {
        fqn for fqn, node in graph.nodes.items()
        if node.kind == NodeKind.CLASS
    }

    if not class_nodes:
        return 0

    # Build method -> owning class lookup
    method_to_class: dict[str, str] = {}
    for edge in graph.edges:
        if edge.kind == EdgeKind.CONTAINS:
            source_node = graph.get_node(edge.source_fqn)
            target_node = graph.get_node(edge.target_fqn)
            if (
                source_node is not None
                and source_node.kind == NodeKind.CLASS
                and target_node is not None
                and target_node.kind == NodeKind.FUNCTION
            ):
                method_to_class[edge.target_fqn] = edge.source_fqn

    # Count cross-class calls
    cross_class_calls: dict[tuple[str, str], int] = defaultdict(int)
    for edge in graph.edges:
        if edge.kind == EdgeKind.CALLS:
            src_class = method_to_class.get(edge.source_fqn)
            tgt_class = method_to_class.get(edge.target_fqn)
            if (
                src_class is not None
                and tgt_class is not None
                and src_class != tgt_class
                and src_class in class_nodes
                and tgt_class in class_nodes
            ):
                cross_class_calls[(src_class, tgt_class)] += 1

    # Find existing DEPENDS_ON pairs to avoid duplicates
    existing_depends: set[tuple[str, str]] = set()
    for edge in graph.edges:
        if edge.kind == EdgeKind.DEPENDS_ON:
            existing_depends.add((edge.source_fqn, edge.target_fqn))

    # Create new DEPENDS_ON edges
    created = 0
    for (src, tgt), weight in cross_class_calls.items():
        if (src, tgt) not in existing_depends:
            graph.add_edge(GraphEdge(
                source_fqn=src,
                target_fqn=tgt,
                kind=EdgeKind.DEPENDS_ON,
                properties={"weight": weight},
            ))
            created += 1

    return created


# ── Step 3: Aggregate Module-Level IMPORTS ───────────────


def aggregate_module_imports(graph: SymbolGraph) -> int:
    """Aggregate class-level DEPENDS_ON edges into module-level IMPORTS edges.

    If module M1 contains classes that DEPEND_ON classes in module M2 (M1 != M2),
    creates ``M1 -[:IMPORTS {weight: N}]-> M2`` where N is the sum of
    class-level DEPENDS_ON weights between the two modules.

    Returns the number of new IMPORTS edges created.
    """
    module_nodes = {
        fqn for fqn, node in graph.nodes.items()
        if node.kind == NodeKind.MODULE
    }

    if not module_nodes:
        return 0

    # Build class -> module lookup
    class_to_module: dict[str, str] = _build_class_to_module_map(graph)

    # Aggregate DEPENDS_ON weights by module pair
    module_weights: dict[tuple[str, str], int] = defaultdict(int)
    for edge in graph.edges:
        if edge.kind == EdgeKind.DEPENDS_ON:
            src_mod = class_to_module.get(edge.source_fqn)
            tgt_mod = class_to_module.get(edge.target_fqn)
            if (
                src_mod is not None
                and tgt_mod is not None
                and src_mod != tgt_mod
                and src_mod in module_nodes
                and tgt_mod in module_nodes
            ):
                weight = edge.properties.get("weight", 1)
                module_weights[(src_mod, tgt_mod)] += weight

    # Find existing IMPORTS to avoid duplicates
    existing_imports: set[tuple[str, str]] = set()
    for edge in graph.edges:
        if edge.kind == EdgeKind.IMPORTS:
            existing_imports.add((edge.source_fqn, edge.target_fqn))

    # Create IMPORTS edges
    created = 0
    for (src, tgt), weight in module_weights.items():
        if (src, tgt) not in existing_imports:
            graph.add_edge(GraphEdge(
                source_fqn=src,
                target_fqn=tgt,
                kind=EdgeKind.IMPORTS,
                properties={"weight": weight},
            ))
            created += 1

    return created


# ── Step 4: Architectural Layer Assignment ───────────────


def assign_architectural_layers(graph: SymbolGraph, app_name: str) -> int:
    """Create Layer nodes and CONTAINS edges from class layer assignments.

    Framework plugins set ``node.properties["layer"]`` on CLASS nodes during
    Stage 5. This function:
    1. Groups classes by their layer name
    2. Creates a Layer node per unique layer
    3. Creates CONTAINS edges: Layer -> Class

    Returns the number of Layer nodes created.
    """
    # Group classes by layer
    layer_members: dict[str, list[str]] = defaultdict(list)
    for fqn, node in graph.nodes.items():
        if node.kind == NodeKind.CLASS:
            layer_name = node.properties.get("layer")
            if layer_name:
                layer_members[layer_name].append(fqn)

    if not layer_members:
        return 0

    # Create Layer nodes and CONTAINS edges
    for layer_name, member_fqns in layer_members.items():
        layer_fqn = f"layer:{app_name}:{layer_name}"

        layer_node = GraphNode(
            fqn=layer_fqn,
            name=layer_name,
            kind=NodeKind.LAYER,
            properties={
                "type": "architectural_layer",
                "app_name": app_name,
                "node_count": len(member_fqns),
            },
        )
        graph.add_node(layer_node)

        for class_fqn in member_fqns:
            graph.add_edge(GraphEdge(
                source_fqn=layer_fqn,
                target_fqn=class_fqn,
                kind=EdgeKind.CONTAINS,
            ))

    return len(layer_members)


# ── Step 5: Community Detection ──────────────────────────


def detect_communities(graph: SymbolGraph, app_name: str) -> int:
    """Detect communities among CLASS nodes using connected components via BFS.

    Uses DEPENDS_ON edges (undirected) to find connected components. This is a
    simple Python-based approach suitable for Phase 1 since Neo4j GDS is not
    available at this stage (data has not been written to Neo4j yet).

    For each community:
    - Creates a Community node with member count
    - Creates INCLUDES edges: Community -> Class
    - Sets ``community_id`` property on each member class

    Returns the number of communities detected.
    """
    # Collect class nodes
    class_fqns = [
        fqn for fqn, node in graph.nodes.items()
        if node.kind == NodeKind.CLASS
    ]

    if not class_fqns:
        return 0

    # Build undirected adjacency list from DEPENDS_ON edges
    adjacency: dict[str, set[str]] = defaultdict(set)
    class_set = set(class_fqns)

    for edge in graph.edges:
        if edge.kind == EdgeKind.DEPENDS_ON:
            if edge.source_fqn in class_set and edge.target_fqn in class_set:
                adjacency[edge.source_fqn].add(edge.target_fqn)
                adjacency[edge.target_fqn].add(edge.source_fqn)

    # BFS to find connected components
    visited: set[str] = set()
    communities: list[list[str]] = []

    for fqn in class_fqns:
        if fqn in visited:
            continue

        # BFS from this node
        component: list[str] = []
        queue: deque[str] = deque([fqn])
        visited.add(fqn)

        while queue:
            current = queue.popleft()
            component.append(current)

            for neighbor in adjacency.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        communities.append(component)

    # Create Community nodes and assign community_id to classes
    for idx, members in enumerate(communities):
        community_fqn = f"community:{app_name}:{idx}"

        community_node = GraphNode(
            fqn=community_fqn,
            name=f"Community {idx}",
            kind=NodeKind.COMMUNITY,
            properties={
                "algorithm": "connected_components",
                "node_count": len(members),
                "app_name": app_name,
            },
        )
        graph.add_node(community_node)

        for class_fqn in members:
            # Set community_id on the class node
            node = graph.get_node(class_fqn)
            if node is not None:
                node.properties["community_id"] = idx

            # Create INCLUDES edge
            graph.add_edge(GraphEdge(
                source_fqn=community_fqn,
                target_fqn=class_fqn,
                kind=EdgeKind.INCLUDES,
            ))

    return len(communities)


# ── Internal Helpers ─────────────────────────────────────


def _build_class_to_module_map(graph: SymbolGraph) -> dict[str, str]:
    """Build a mapping of class FQN -> module FQN.

    Uses two strategies:
    1. Module CONTAINS Class edges
    2. Class ``module_fqn`` property (fallback)
    """
    class_to_module: dict[str, str] = {}

    # Strategy 1: CONTAINS edges from Module -> Class
    for edge in graph.edges:
        if edge.kind == EdgeKind.CONTAINS:
            source_node = graph.get_node(edge.source_fqn)
            target_node = graph.get_node(edge.target_fqn)
            if (
                source_node is not None
                and source_node.kind == NodeKind.MODULE
                and target_node is not None
                and target_node.kind == NodeKind.CLASS
            ):
                class_to_module[edge.target_fqn] = edge.source_fqn

    # Strategy 2: Fallback to module_fqn property
    for fqn, node in graph.nodes.items():
        if node.kind == NodeKind.CLASS and fqn not in class_to_module:
            module_fqn = node.properties.get("module_fqn")
            if module_fqn:
                class_to_module[fqn] = module_fqn

    return class_to_module
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_enricher.py -v`
Expected: PASS (all tests green)

- [ ] **Step 5: Verify with ruff**

Run: `cd cast-clone-backend && uv run ruff check app/stages/enricher.py tests/unit/test_enricher.py`
Expected: No errors

Run: `cd cast-clone-backend && uv run ruff format app/stages/enricher.py tests/unit/test_enricher.py`

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/stages/enricher.py tests/unit/test_enricher.py && git commit -m "feat(stages): add Stage 7 Graph Enricher — fan metrics, DEPENDS_ON/IMPORTS aggregation, layers, communities"
```

---

## Task 3: Wire Enricher into Stage Init

**Files:**
- Modify: `app/stages/__init__.py`

- [ ] **Step 7: Add enricher export**

Add to `app/stages/__init__.py`:

```python
from app.stages.enricher import enrich_graph
```

This ensures `enrich_graph` is importable from `app.stages` for the pipeline orchestrator.

- [ ] **Step 8: Commit**

```bash
cd cast-clone-backend && git add app/stages/__init__.py && git commit -m "feat(stages): export enrich_graph from stages package"
```

---

## Design Decisions & Rationale

### Why Connected Components Instead of Label Propagation?

Connected components via BFS is deterministic and trivially correct for Phase 1. Label propagation would give better results on dense graphs (splitting large connected components into subcommunities), but introduces non-determinism and complexity. The plan is to upgrade to GDS Louvain post-Stage 8 in Phase 3 — this Phase 1 implementation just needs to produce reasonable community structure for the visualization layer.

### Why Build method_to_class Lookup Twice?

`compute_fan_metrics` and `aggregate_class_depends_on` both build a `method_to_class` map by scanning CONTAINS edges. This is intentional — each function is independently testable and callable. The full graph scan is O(E) and runs in milliseconds even for 100K+ edges. If profiling shows this matters, extract into a shared helper.

### Layer Assignment Strategy

Framework plugins (Stage 5) are responsible for setting `node.properties["layer"]` on CLASS nodes. Common patterns:
- `@Controller` / `@RestController` -> "Presentation"
- `@Service` -> "Business Logic"
- `@Repository` -> "Data Access"
- `@Configuration` -> "Configuration"
- Classes not tagged by any plugin -> no layer assignment (they don't get a Layer parent)

The enricher does not infer layers — it only materializes the assignments that plugins have already made.

### Edge Deduplication

Both `aggregate_class_depends_on` and `aggregate_module_imports` check for existing edges before creating new ones. This handles the case where a previous pipeline run or plugin has already created these edges. The existing edge is left as-is (its weight is not updated) — this is a deliberate simplicity trade-off for Phase 1.

---

## Verification Checklist

After implementation, verify:

- [ ] `uv run pytest tests/unit/test_enricher.py -v` — all 10+ tests pass
- [ ] `uv run ruff check app/stages/enricher.py` — no lint errors
- [ ] `uv run ruff format --check app/stages/enricher.py` — properly formatted
- [ ] `uv run mypy app/stages/enricher.py` — no type errors
- [ ] `from app.stages.enricher import enrich_graph` works in Python REPL
- [ ] The function signature matches the pipeline contract: `async def enrich_graph(context: AnalysisContext) -> None`
