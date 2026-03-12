# M7d: Transaction Discovery (Stage 9) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Stage 9 of the analysis pipeline -- discover end-to-end transaction flows by BFS from entry points (HTTP endpoints, message consumers, scheduled tasks, main methods) through CALLS edges to terminal nodes (TABLE writes/reads, MESSAGE produces, external API calls). Each discovered flow becomes a `Transaction` node with `STARTS_AT`, `ENDS_AT`, and `INCLUDES` edges added to the `SymbolGraph`.

**Architecture:** Pure in-memory graph transformation operating on `AnalysisContext.graph` (SymbolGraph). Entry points come from `context.entry_points` (populated by framework plugins in Stage 5). BFS traversal with cycle detection and configurable max depth. Non-critical stage -- failures degrade gracefully with warnings, never abort the pipeline.

**Tech Stack:** Python 3.12, dataclasses, collections.deque, structlog, pytest + pytest-asyncio

**Dependencies from M1:** `GraphNode`, `GraphEdge`, `SymbolGraph`, `AnalysisContext`, `NodeKind`, `EdgeKind`, `Confidence`, `EntryPoint`

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       └── transactions.py          # CREATE — Stage 9: Transaction Discovery
├── tests/
│   └── unit/
│       └── test_transactions.py     # CREATE — 10 tests covering all cases
```

---

## Key Interfaces (from M1 foundation)

```python
@dataclass
class AnalysisContext:
    project_id: str
    manifest: ProjectManifest
    graph: SymbolGraph          # populated by stages 3-7
    entry_points: list[dict]    # populated by framework plugins (stage 5)
    transaction_count: int = 0
    warnings: list[str] = field(default_factory=list)

@dataclass
class SymbolGraph:
    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]
    def get_node(fqn: str) -> GraphNode | None
    def get_edges_from(fqn: str) -> list[GraphEdge]
    def add_node(node: GraphNode) -> None
    def add_edge(edge: GraphEdge) -> None

@dataclass
class GraphNode:
    fqn: str; name: str; kind: NodeKind
    language: str = ""; path: str = ""; line: int = 0
    properties: dict[str, Any] = field(default_factory=dict)

@dataclass
class GraphEdge:
    source_fqn: str; target_fqn: str; kind: EdgeKind
    confidence: Confidence = Confidence.HIGH
    evidence: str = ""; properties: dict[str, Any] = field(default_factory=dict)

# Enum values used:
# NodeKind.TRANSACTION, NodeKind.FUNCTION, NodeKind.TABLE, NodeKind.MESSAGE_TOPIC, NodeKind.API_ENDPOINT
# EdgeKind.CALLS, EdgeKind.WRITES, EdgeKind.READS, EdgeKind.PRODUCES, EdgeKind.CALLS_API
# EdgeKind.STARTS_AT, EdgeKind.ENDS_AT, EdgeKind.INCLUDES
```

### Entry Point Dict Format (from framework plugins)

```python
# HTTP entry point (from Spring Web, Express, etc.)
{"fqn": "com.UserCtrl.getUsers", "type": "http", "method": "GET", "path": "/api/users"}

# Message consumer entry point (from Kafka/RabbitMQ plugins)
{"fqn": "com.OrderHandler.onEvent", "type": "message", "topic": "order-events"}

# Scheduled task entry point
{"fqn": "com.BatchJob.run", "type": "scheduled", "cron": "0 0 * * *"}

# Main method entry point
{"fqn": "com.App.main", "type": "main"}
```

### Neo4j Schema (target output after Stage 8 writes these nodes)

```cypher
(:Transaction {
  name: String,           // "GET /api/users -> getUsers"
  entry_point_fqn: String,
  end_point_types: [String],  // ["TABLE_WRITE", "MESSAGE_PUBLISH"]
  node_count: Integer,
  depth: Integer,
  http_method: String,    // nullable
  url_path: String        // nullable
})

(:Transaction)-[:STARTS_AT]->(:Function)
(:Transaction)-[:ENDS_AT]->(:Function)
(:Transaction)-[:INCLUDES {position: Integer}]->(:Function)
```

---

## Algorithm

```
discover_transactions(context):
  1. Read entry_points from context.entry_points
  2. If empty, set transaction_count = 0, return
  3. For each entry_point:
     a. Extract fqn from entry_point dict
     b. Verify fqn exists in context.graph → skip with warning if not
     c. Call trace_transaction_flow(fqn, graph, max_depth)
        → BFS from entry fqn following CALLS edges
        → Cycle detection via visited set
        → Stop at max_depth (default 15)
        → At each visited node, check classify_terminal_node()
        → Returns TransactionFlow dataclass
     d. Build transaction name from entry_point metadata
     e. Create Transaction GraphNode with properties
     f. Add STARTS_AT edge: transaction → entry function
     g. Add ENDS_AT edges: transaction → each terminal function
     h. Add INCLUDES edges: transaction → each function, with position property
     i. Add all to context.graph
  4. Set context.transaction_count

trace_transaction_flow(entry_fqn, graph, max_depth):
  BFS using deque[(fqn, depth)]
  visited: set[str] for cycle detection
  Only follow EdgeKind.CALLS to NodeKind.FUNCTION nodes
  At each node: classify_terminal_node() to detect terminals
  Returns TransactionFlow(entry_fqn, visited_fqns, end_point_types, terminal_fqns, depth)

classify_terminal_node(fqn, graph):
  Check outgoing edges for terminal kinds:
    WRITES → "TABLE_WRITE"
    READS  → "TABLE_READ"
    PRODUCES → "MESSAGE_PUBLISH"
    CALLS_API → "EXTERNAL_API_CALL"
  Returns first match or None
```

---

## Task 1: Write Failing Tests

**File:** `tests/unit/test_transactions.py`

- [ ] **Step 1: Write the complete test file**

```python
# tests/unit/test_transactions.py
"""Tests for Stage 9: Transaction Discovery."""

import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest
from app.stages.transactions import (
    discover_transactions,
    trace_transaction_flow,
    classify_terminal_node,
    DEFAULT_MAX_DEPTH,
)


def _make_context(graph: SymbolGraph) -> AnalysisContext:
    """Helper to build an AnalysisContext with a pre-populated graph."""
    manifest = ProjectManifest(
        root_path="/fake",
        detected_languages=[],
        detected_frameworks=[],
        source_files=[],
        total_files=0,
        total_loc=0,
    )
    ctx = AnalysisContext(project_id="test", manifest=manifest)
    ctx.graph = graph
    return ctx


# ── Terminal Node Classification ───────────────────────────


class TestClassifyTerminalNode:
    """Tests for classify_terminal_node()."""

    def test_table_write_is_terminal(self):
        """WRITES -> Table edge makes a node terminal with TABLE_WRITE."""
        g = SymbolGraph()
        fn = GraphNode(fqn="com.A.save", name="save", kind=NodeKind.FUNCTION)
        table = GraphNode(fqn="users", name="users", kind=NodeKind.TABLE)
        g.add_node(fn)
        g.add_node(table)
        g.add_edge(GraphEdge(source_fqn="com.A.save", target_fqn="users", kind=EdgeKind.WRITES))

        result = classify_terminal_node("com.A.save", g)
        assert result == "TABLE_WRITE"

    def test_table_read_is_terminal(self):
        """READS -> Table edge makes a node terminal with TABLE_READ."""
        g = SymbolGraph()
        fn = GraphNode(fqn="com.A.find", name="find", kind=NodeKind.FUNCTION)
        table = GraphNode(fqn="users", name="users", kind=NodeKind.TABLE)
        g.add_node(fn)
        g.add_node(table)
        g.add_edge(GraphEdge(source_fqn="com.A.find", target_fqn="users", kind=EdgeKind.READS))

        result = classify_terminal_node("com.A.find", g)
        assert result == "TABLE_READ"

    def test_message_produce_is_terminal(self):
        """PRODUCES -> MessageTopic edge makes a node terminal with MESSAGE_PUBLISH."""
        g = SymbolGraph()
        fn = GraphNode(fqn="com.A.send", name="send", kind=NodeKind.FUNCTION)
        topic = GraphNode(fqn="topic:events", name="events", kind=NodeKind.MESSAGE_TOPIC)
        g.add_node(fn)
        g.add_node(topic)
        g.add_edge(GraphEdge(source_fqn="com.A.send", target_fqn="topic:events", kind=EdgeKind.PRODUCES))

        result = classify_terminal_node("com.A.send", g)
        assert result == "MESSAGE_PUBLISH"

    def test_api_call_is_terminal(self):
        """CALLS_API -> APIEndpoint edge makes a node terminal with EXTERNAL_API_CALL."""
        g = SymbolGraph()
        fn = GraphNode(fqn="src.api.call", name="call", kind=NodeKind.FUNCTION)
        ep = GraphNode(fqn="GET:/ext/api", name="GET /ext/api", kind=NodeKind.API_ENDPOINT)
        g.add_node(fn)
        g.add_node(ep)
        g.add_edge(GraphEdge(source_fqn="src.api.call", target_fqn="GET:/ext/api", kind=EdgeKind.CALLS_API))

        result = classify_terminal_node("src.api.call", g)
        assert result == "EXTERNAL_API_CALL"

    def test_non_terminal_returns_none(self):
        """Function with only CALLS edges is not terminal."""
        g = SymbolGraph()
        fn = GraphNode(fqn="com.A.process", name="process", kind=NodeKind.FUNCTION)
        fn2 = GraphNode(fqn="com.B.helper", name="helper", kind=NodeKind.FUNCTION)
        g.add_node(fn)
        g.add_node(fn2)
        g.add_edge(GraphEdge(source_fqn="com.A.process", target_fqn="com.B.helper", kind=EdgeKind.CALLS))

        result = classify_terminal_node("com.A.process", g)
        assert result is None

    def test_node_with_no_edges_returns_none(self):
        """Function with no outgoing edges is not terminal (just a leaf)."""
        g = SymbolGraph()
        fn = GraphNode(fqn="com.A.leaf", name="leaf", kind=NodeKind.FUNCTION)
        g.add_node(fn)

        result = classify_terminal_node("com.A.leaf", g)
        assert result is None


# ── Transaction Flow Tracing ───────────────────────────────


class TestTraceTransactionFlow:
    """Tests for trace_transaction_flow() BFS traversal."""

    def test_simple_linear_chain(self):
        """A -> B -> C(writes TABLE) produces a flow with 3 nodes."""
        g = SymbolGraph()
        g.add_node(GraphNode(fqn="A.handle", name="handle", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="B.process", name="process", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="C.save", name="save", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))

        g.add_edge(GraphEdge(source_fqn="A.handle", target_fqn="B.process", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="B.process", target_fqn="C.save", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="C.save", target_fqn="users", kind=EdgeKind.WRITES))

        flow = trace_transaction_flow("A.handle", g, max_depth=15)

        assert len(flow.visited_fqns) == 3
        assert flow.visited_fqns == ["A.handle", "B.process", "C.save"]
        assert "TABLE_WRITE" in flow.end_point_types
        assert flow.depth == 2  # 2 hops from entry to terminal
        assert "C.save" in flow.terminal_fqns

    def test_branching_chain(self):
        """A -> B, A -> C covers both branches."""
        g = SymbolGraph()
        g.add_node(GraphNode(fqn="A.handle", name="handle", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="B.save", name="save", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="C.notify", name="notify", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))
        g.add_node(GraphNode(fqn="topic:events", name="events", kind=NodeKind.MESSAGE_TOPIC))

        g.add_edge(GraphEdge(source_fqn="A.handle", target_fqn="B.save", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="A.handle", target_fqn="C.notify", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="B.save", target_fqn="users", kind=EdgeKind.WRITES))
        g.add_edge(GraphEdge(source_fqn="C.notify", target_fqn="topic:events", kind=EdgeKind.PRODUCES))

        flow = trace_transaction_flow("A.handle", g, max_depth=15)

        assert len(flow.visited_fqns) == 3
        assert set(flow.end_point_types) == {"TABLE_WRITE", "MESSAGE_PUBLISH"}
        assert len(flow.terminal_fqns) == 2

    def test_cycle_detection(self):
        """Cycles don't cause infinite loops -- BFS stops at visited nodes."""
        g = SymbolGraph()
        g.add_node(GraphNode(fqn="A.fn", name="fn", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="B.fn", name="fn", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="C.fn", name="fn", kind=NodeKind.FUNCTION))
        g.add_edge(GraphEdge(source_fqn="A.fn", target_fqn="B.fn", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="B.fn", target_fqn="C.fn", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="C.fn", target_fqn="A.fn", kind=EdgeKind.CALLS))

        flow = trace_transaction_flow("A.fn", g, max_depth=15)

        # Visits all 3, but does not loop
        assert len(flow.visited_fqns) == 3
        assert flow.depth == 2

    def test_max_depth_limits_traversal(self):
        """Flow stops at max_depth even without terminal nodes."""
        g = SymbolGraph()
        # Create a chain of 20 nodes: N0 -> N1 -> ... -> N19
        for i in range(20):
            g.add_node(GraphNode(fqn=f"N{i}.fn", name="fn", kind=NodeKind.FUNCTION))
        for i in range(19):
            g.add_edge(GraphEdge(source_fqn=f"N{i}.fn", target_fqn=f"N{i+1}.fn", kind=EdgeKind.CALLS))

        flow = trace_transaction_flow("N0.fn", g, max_depth=5)

        # Should visit N0..N5 (depth 0 through 5) = 6 nodes
        assert len(flow.visited_fqns) == 6
        assert flow.visited_fqns[-1] == "N5.fn"
        assert "N6.fn" not in flow.visited_fqns
        assert flow.depth == 5

    def test_single_node_no_calls(self):
        """Entry point with no outgoing CALLS produces a single-node flow."""
        g = SymbolGraph()
        g.add_node(GraphNode(fqn="A.fn", name="fn", kind=NodeKind.FUNCTION))

        flow = trace_transaction_flow("A.fn", g, max_depth=15)

        assert flow.visited_fqns == ["A.fn"]
        assert flow.depth == 0
        assert flow.end_point_types == []
        assert flow.terminal_fqns == []

    def test_only_follows_calls_edges(self):
        """BFS only follows CALLS edges, not CONTAINS/INHERITS/etc."""
        g = SymbolGraph()
        g.add_node(GraphNode(fqn="A.fn", name="fn", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="B.fn", name="fn", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="C.fn", name="fn", kind=NodeKind.FUNCTION))
        # CALLS edge to B
        g.add_edge(GraphEdge(source_fqn="A.fn", target_fqn="B.fn", kind=EdgeKind.CALLS))
        # CONTAINS edge to C (should NOT be followed)
        g.add_edge(GraphEdge(source_fqn="A.fn", target_fqn="C.fn", kind=EdgeKind.CONTAINS))

        flow = trace_transaction_flow("A.fn", g, max_depth=15)

        assert len(flow.visited_fqns) == 2
        assert "C.fn" not in flow.visited_fqns

    def test_terminal_node_still_continues_bfs(self):
        """BFS continues past terminal nodes to find the full flow."""
        g = SymbolGraph()
        g.add_node(GraphNode(fqn="A.fn", name="fn", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="B.fn", name="fn", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="C.fn", name="fn", kind=NodeKind.FUNCTION))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))

        # B writes to table (terminal) but also calls C
        g.add_edge(GraphEdge(source_fqn="A.fn", target_fqn="B.fn", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="B.fn", target_fqn="users", kind=EdgeKind.WRITES))
        g.add_edge(GraphEdge(source_fqn="B.fn", target_fqn="C.fn", kind=EdgeKind.CALLS))

        flow = trace_transaction_flow("A.fn", g, max_depth=15)

        # All 3 functions visited, B is terminal but C is still included
        assert len(flow.visited_fqns) == 3
        assert "B.fn" in flow.terminal_fqns
        assert "C.fn" in flow.visited_fqns


# ── Integration: discover_transactions ─────────────────────


class TestDiscoverTransactions:
    """Tests for the main discover_transactions() async entry point."""

    @pytest.mark.asyncio
    async def test_http_entry_point_creates_transaction(self):
        """HTTP entry point produces a Transaction node with correct naming."""
        g = SymbolGraph()

        handler = GraphNode(fqn="com.UserCtrl.getUsers", name="getUsers", kind=NodeKind.FUNCTION, language="java")
        repo_fn = GraphNode(fqn="com.UserRepo.findAll", name="findAll", kind=NodeKind.FUNCTION, language="java")
        table = GraphNode(fqn="users", name="users", kind=NodeKind.TABLE)

        g.add_node(handler)
        g.add_node(repo_fn)
        g.add_node(table)

        g.add_edge(GraphEdge(source_fqn="com.UserCtrl.getUsers", target_fqn="com.UserRepo.findAll", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="com.UserRepo.findAll", target_fqn="users", kind=EdgeKind.READS))

        ctx = _make_context(g)
        ctx.entry_points = [
            {"fqn": "com.UserCtrl.getUsers", "type": "http", "method": "GET", "path": "/api/users"}
        ]

        await discover_transactions(ctx)

        assert ctx.transaction_count == 1

        # Verify Transaction node
        txn_nodes = [n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION]
        assert len(txn_nodes) == 1
        txn = txn_nodes[0]
        assert "GET" in txn.name
        assert "/api/users" in txn.name
        assert txn.properties["entry_point_fqn"] == "com.UserCtrl.getUsers"
        assert txn.properties["node_count"] == 2
        assert "TABLE_READ" in txn.properties["end_point_types"]
        assert txn.properties["http_method"] == "GET"
        assert txn.properties["url_path"] == "/api/users"

        # Verify STARTS_AT edge
        starts_at = [e for e in ctx.graph.edges if e.kind == EdgeKind.STARTS_AT]
        assert len(starts_at) == 1
        assert starts_at[0].target_fqn == "com.UserCtrl.getUsers"

        # Verify ENDS_AT edge (repo_fn reads table, so it's terminal)
        ends_at = [e for e in ctx.graph.edges if e.kind == EdgeKind.ENDS_AT]
        assert len(ends_at) == 1
        assert ends_at[0].target_fqn == "com.UserRepo.findAll"

        # Verify INCLUDES edges with positions
        includes = [e for e in ctx.graph.edges if e.kind == EdgeKind.INCLUDES]
        assert len(includes) == 2
        positions = sorted([e.properties["position"] for e in includes])
        assert positions == [0, 1]

    @pytest.mark.asyncio
    async def test_message_consumer_entry_point(self):
        """Message consumer entry point produces a correctly named transaction."""
        g = SymbolGraph()

        consumer = GraphNode(fqn="com.OrderHandler.onEvent", name="onEvent", kind=NodeKind.FUNCTION)
        save_fn = GraphNode(fqn="com.OrderRepo.save", name="save", kind=NodeKind.FUNCTION)
        table = GraphNode(fqn="orders", name="orders", kind=NodeKind.TABLE)

        g.add_node(consumer)
        g.add_node(save_fn)
        g.add_node(table)

        g.add_edge(GraphEdge(source_fqn="com.OrderHandler.onEvent", target_fqn="com.OrderRepo.save", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="com.OrderRepo.save", target_fqn="orders", kind=EdgeKind.WRITES))

        ctx = _make_context(g)
        ctx.entry_points = [
            {"fqn": "com.OrderHandler.onEvent", "type": "message", "topic": "order-events"}
        ]

        await discover_transactions(ctx)

        assert ctx.transaction_count == 1
        txn_nodes = [n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION]
        assert len(txn_nodes) == 1
        assert "order-events" in txn_nodes[0].name

    @pytest.mark.asyncio
    async def test_no_entry_points_no_transactions(self):
        """Empty entry_points list produces 0 transactions, no errors."""
        g = SymbolGraph()
        ctx = _make_context(g)
        ctx.entry_points = []

        await discover_transactions(ctx)

        assert ctx.transaction_count == 0
        txn_nodes = [n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION]
        assert len(txn_nodes) == 0

    @pytest.mark.asyncio
    async def test_entry_point_not_in_graph_skips_with_warning(self):
        """Entry point FQN not found in graph -> skip with warning, don't crash."""
        g = SymbolGraph()
        ctx = _make_context(g)
        ctx.entry_points = [
            {"fqn": "com.Missing.handler", "type": "http", "method": "GET", "path": "/missing"}
        ]

        await discover_transactions(ctx)

        assert ctx.transaction_count == 0
        assert any("com.Missing.handler" in w for w in ctx.warnings)

    @pytest.mark.asyncio
    async def test_multiple_entry_points_create_multiple_transactions(self):
        """3 entry points produce 3 Transaction nodes."""
        g = SymbolGraph()

        for name in ["A", "B", "C"]:
            g.add_node(GraphNode(fqn=f"com.{name}.handle", name="handle", kind=NodeKind.FUNCTION))

        ctx = _make_context(g)
        ctx.entry_points = [
            {"fqn": "com.A.handle", "type": "http", "method": "GET", "path": "/a"},
            {"fqn": "com.B.handle", "type": "http", "method": "POST", "path": "/b"},
            {"fqn": "com.C.handle", "type": "http", "method": "DELETE", "path": "/c"},
        ]

        await discover_transactions(ctx)

        assert ctx.transaction_count == 3
        txn_nodes = [n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION]
        assert len(txn_nodes) == 3

    @pytest.mark.asyncio
    async def test_default_max_depth_is_15(self):
        """DEFAULT_MAX_DEPTH constant is 15."""
        assert DEFAULT_MAX_DEPTH == 15
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_transactions.py -v`
Expected: FAIL (ImportError -- `app.stages.transactions` module does not exist)

---

## Task 2: Implement Transaction Discovery

**File:** `app/stages/transactions.py`

- [ ] **Step 1: Create the implementation**

```python
# app/stages/transactions.py
"""Stage 9: Transaction Discovery.

Discovers end-to-end transaction flows by BFS from entry points through
CALLS edges to terminal nodes (TABLE writes, MESSAGE produces, external
API calls).

Each flow becomes a Transaction node with STARTS_AT, ENDS_AT, INCLUDES edges.

This stage is non-critical. Failures degrade gracefully with warnings.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph

logger = structlog.get_logger(__name__)

DEFAULT_MAX_DEPTH = 15

# Terminal edge kinds and their classification labels
_TERMINAL_EDGE_MAP: dict[EdgeKind, str] = {
    EdgeKind.WRITES: "TABLE_WRITE",
    EdgeKind.READS: "TABLE_READ",
    EdgeKind.PRODUCES: "MESSAGE_PUBLISH",
    EdgeKind.CALLS_API: "EXTERNAL_API_CALL",
}


# ── Terminal Node Classification ───────────────────────────


def classify_terminal_node(fqn: str, graph: SymbolGraph) -> str | None:
    """Check if a function node is a terminal node in a transaction flow.

    A terminal node is one that has an outgoing edge to a TABLE (WRITES/READS),
    MessageTopic (PRODUCES), or external APIEndpoint (CALLS_API).

    Returns a classification string ("TABLE_WRITE", "TABLE_READ",
    "MESSAGE_PUBLISH", "EXTERNAL_API_CALL") or None if not terminal.
    """
    for edge in graph.get_edges_from(fqn):
        if edge.kind in _TERMINAL_EDGE_MAP:
            return _TERMINAL_EDGE_MAP[edge.kind]
    return None


# ── Transaction Flow Tracing ───────────────────────────────


@dataclass
class TransactionFlow:
    """Result of tracing a single transaction flow via BFS.

    Attributes:
        entry_fqn: FQN of the entry point function.
        visited_fqns: Ordered list of function FQNs visited during BFS.
        end_point_types: List of terminal type labels found (e.g., "TABLE_WRITE").
        terminal_fqns: List of FQNs that are terminal nodes.
        depth: Maximum BFS depth reached.
    """

    entry_fqn: str
    visited_fqns: list[str] = field(default_factory=list)
    end_point_types: list[str] = field(default_factory=list)
    terminal_fqns: list[str] = field(default_factory=list)
    depth: int = 0


def trace_transaction_flow(
    entry_fqn: str,
    graph: SymbolGraph,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> TransactionFlow:
    """Trace a transaction flow via BFS from an entry point.

    Follows CALLS edges from the entry function. Stops at:
    - max_depth (configurable, default 15)
    - Already-visited nodes (cycle detection)

    Terminal nodes (WRITES, PRODUCES, CALLS_API) are recorded but BFS
    continues past them to capture the full flow.

    Only follows CALLS edges to Function nodes.
    """
    flow = TransactionFlow(entry_fqn=entry_fqn)
    visited: set[str] = set()

    # BFS queue: (fqn, current_depth)
    queue: deque[tuple[str, int]] = deque()
    queue.append((entry_fqn, 0))

    while queue:
        current_fqn, current_depth = queue.popleft()

        if current_fqn in visited:
            continue

        # Only include Function nodes in the flow
        node = graph.get_node(current_fqn)
        if node is None or node.kind != NodeKind.FUNCTION:
            continue

        visited.add(current_fqn)
        flow.visited_fqns.append(current_fqn)
        flow.depth = max(flow.depth, current_depth)

        # Check if this is a terminal node
        terminal_type = classify_terminal_node(current_fqn, graph)
        if terminal_type is not None:
            if terminal_type not in flow.end_point_types:
                flow.end_point_types.append(terminal_type)
            flow.terminal_fqns.append(current_fqn)

        # Continue BFS if within depth limit
        if current_depth < max_depth:
            for edge in graph.get_edges_from(current_fqn):
                if edge.kind == EdgeKind.CALLS and edge.target_fqn not in visited:
                    queue.append((edge.target_fqn, current_depth + 1))

    return flow


# ── Transaction Node Builder ───────────────────────────────


def _build_transaction_name(entry_point: dict[str, Any]) -> str:
    """Build a human-readable transaction name from an entry point definition.

    Naming conventions:
    - HTTP:      "GET /api/users -> getUsers"
    - Message:   "MSG order-events -> onEvent"
    - Scheduled: "SCHED 0 0 * * * -> run"
    - Other:     "TXN -> com.App.main"
    """
    ep_type = entry_point.get("type", "unknown")
    fqn = entry_point.get("fqn", "")
    # Extract short method name from FQN (last segment after .)
    parts = fqn.rsplit(".", 1)
    handler = parts[-1] if parts else fqn

    if ep_type == "http":
        method = entry_point.get("method", "?")
        path = entry_point.get("path", "?")
        return f"{method} {path} -> {handler}"

    elif ep_type == "message":
        topic = entry_point.get("topic", "?")
        return f"MSG {topic} -> {handler}"

    elif ep_type == "scheduled":
        cron = entry_point.get("cron", "?")
        return f"SCHED {cron} -> {handler}"

    else:
        return f"TXN -> {fqn}"


# ── Main Entry Point ───────────────────────────────────────


async def discover_transactions(
    context: AnalysisContext,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> None:
    """Stage 9: Discover transaction flows from entry points.

    For each entry point in context.entry_points:
    1. Trace the flow via BFS through CALLS edges
    2. Create a Transaction node with metadata
    3. Add STARTS_AT, ENDS_AT, INCLUDES edges to context.graph

    Modifies context.graph in place. Sets context.transaction_count.
    Non-critical -- failures logged as warnings, never abort.
    """
    logger.info("transaction_discovery.start", project_id=context.project_id)
    graph = context.graph
    entry_points: list[dict[str, Any]] = getattr(context, "entry_points", [])

    if not entry_points:
        context.transaction_count = 0
        logger.info("transaction_discovery.complete", transactions=0, reason="no_entry_points")
        return

    transaction_count = 0

    for ep in entry_points:
        try:
            # Extract FQN from entry point (supports dict or object with .fqn)
            entry_fqn: str | None
            if isinstance(ep, dict):
                entry_fqn = ep.get("fqn")
            else:
                entry_fqn = getattr(ep, "fqn", None)

            if not entry_fqn:
                logger.warning("transaction_discovery.skip_no_fqn", entry_point=str(ep))
                continue

            # Verify entry point exists in graph
            if graph.get_node(entry_fqn) is None:
                context.warnings.append(f"Entry point not found in graph: {entry_fqn}")
                logger.warning("transaction_discovery.entry_not_in_graph", fqn=entry_fqn)
                continue

            # Trace the flow via BFS
            flow = trace_transaction_flow(entry_fqn, graph, max_depth)

            if len(flow.visited_fqns) < 1:
                continue

            # Build transaction name and FQN
            ep_dict = ep if isinstance(ep, dict) else {"fqn": entry_fqn}
            txn_name = _build_transaction_name(ep_dict)
            txn_fqn = f"txn:{txn_name}"

            # Create Transaction node
            txn_node = GraphNode(
                fqn=txn_fqn,
                name=txn_name,
                kind=NodeKind.TRANSACTION,
                properties={
                    "entry_point_fqn": entry_fqn,
                    "end_point_types": flow.end_point_types,
                    "node_count": len(flow.visited_fqns),
                    "depth": flow.depth,
                    "http_method": ep_dict.get("method") if isinstance(ep_dict, dict) else None,
                    "url_path": ep_dict.get("path") if isinstance(ep_dict, dict) else None,
                },
            )
            graph.add_node(txn_node)

            # STARTS_AT edge: transaction -> entry function
            graph.add_edge(GraphEdge(
                source_fqn=txn_fqn,
                target_fqn=entry_fqn,
                kind=EdgeKind.STARTS_AT,
                confidence=Confidence.HIGH,
                evidence="transaction-discovery",
            ))

            # ENDS_AT edges: transaction -> each terminal function
            for terminal_fqn in flow.terminal_fqns:
                graph.add_edge(GraphEdge(
                    source_fqn=txn_fqn,
                    target_fqn=terminal_fqn,
                    kind=EdgeKind.ENDS_AT,
                    confidence=Confidence.HIGH,
                    evidence="transaction-discovery",
                ))

            # INCLUDES edges with position: transaction -> each function in flow
            for position, fn_fqn in enumerate(flow.visited_fqns):
                graph.add_edge(GraphEdge(
                    source_fqn=txn_fqn,
                    target_fqn=fn_fqn,
                    kind=EdgeKind.INCLUDES,
                    confidence=Confidence.HIGH,
                    evidence="transaction-discovery",
                    properties={"position": position},
                ))

            transaction_count += 1
            logger.debug(
                "transaction_discovery.created",
                name=txn_name,
                node_count=len(flow.visited_fqns),
                depth=flow.depth,
                terminals=flow.end_point_types,
            )

        except Exception as e:
            ep_fqn = ep.get("fqn", "?") if isinstance(ep, dict) else str(ep)
            context.warnings.append(f"Transaction discovery failed for {ep_fqn}: {e}")
            logger.warning("transaction_discovery.entry_failed", entry=ep_fqn, error=str(e))

    context.transaction_count = transaction_count
    logger.info(
        "transaction_discovery.complete",
        project_id=context.project_id,
        transactions=transaction_count,
        entry_points_scanned=len(entry_points),
    )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_transactions.py -v`
Expected: PASS (all 17 tests)

- [ ] **Step 3: Run linting**

```bash
cd cast-clone-backend && uv run ruff check app/stages/transactions.py tests/unit/test_transactions.py
cd cast-clone-backend && uv run ruff format app/stages/transactions.py tests/unit/test_transactions.py
```

Expected: No errors. If any, fix and re-run.

- [ ] **Step 4: Run type checking**

```bash
cd cast-clone-backend && uv run mypy app/stages/transactions.py
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/transactions.py tests/unit/test_transactions.py && git commit -m "feat(stages): add Stage 9 transaction discovery with BFS flow tracing"
```

---

## Task 3: Wire into Stages Package

**File:** Modify `app/stages/__init__.py`

- [ ] **Step 1: Update stages __init__.py to export discover_transactions**

Add to `app/stages/__init__.py`:

```python
from app.stages.transactions import discover_transactions
```

And add `"discover_transactions"` to the `__all__` list (create `__all__` if it doesn't exist).

- [ ] **Step 2: Run full test suite to verify no regressions**

```bash
cd cast-clone-backend && uv run pytest tests/unit/ -v
```

Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add app/stages/__init__.py && git commit -m "feat(stages): export discover_transactions from stages package"
```

---

## Test Coverage Summary

| # | Test | What It Verifies |
|---|------|------------------|
| 1 | `test_table_write_is_terminal` | WRITES edge classified as TABLE_WRITE |
| 2 | `test_table_read_is_terminal` | READS edge classified as TABLE_READ |
| 3 | `test_message_produce_is_terminal` | PRODUCES edge classified as MESSAGE_PUBLISH |
| 4 | `test_api_call_is_terminal` | CALLS_API edge classified as EXTERNAL_API_CALL |
| 5 | `test_non_terminal_returns_none` | Node with only CALLS edges is not terminal |
| 6 | `test_node_with_no_edges_returns_none` | Node with zero edges is not terminal |
| 7 | `test_simple_linear_chain` | A->B->C(writes) = 3 nodes, depth 2, TABLE_WRITE |
| 8 | `test_branching_chain` | A->B, A->C finds both branches and both terminal types |
| 9 | `test_cycle_detection` | A->B->C->A cycle doesn't infinite loop |
| 10 | `test_max_depth_limits_traversal` | Chain of 20, max_depth=5 stops at 6 nodes |
| 11 | `test_single_node_no_calls` | Entry with no CALLS = 1-node flow, depth 0 |
| 12 | `test_only_follows_calls_edges` | BFS ignores CONTAINS/INHERITS/etc. |
| 13 | `test_terminal_node_still_continues_bfs` | Terminal node doesn't stop BFS |
| 14 | `test_http_entry_point_creates_transaction` | Full integration: Transaction node, STARTS_AT, ENDS_AT, INCLUDES |
| 15 | `test_message_consumer_entry_point` | MSG naming convention for message consumers |
| 16 | `test_no_entry_points_no_transactions` | Empty list -> 0 transactions, no crash |
| 17 | `test_entry_point_not_in_graph_skips_with_warning` | Missing FQN -> warning, not crash |
| 18 | `test_multiple_entry_points_create_multiple_transactions` | 3 entry points -> 3 transactions |
| 19 | `test_default_max_depth_is_15` | Constant check |

---

## Edge Cases Handled

| Case | Behavior |
|------|----------|
| No entry points | `transaction_count = 0`, no error |
| Entry point FQN not in graph | Skip, add warning to `context.warnings` |
| Circular call chain (A->B->C->A) | Visited set prevents infinite loop |
| Very deep chain (>max_depth) | BFS stops at max_depth |
| Entry point is a non-FUNCTION node | Skipped by BFS (only FUNCTION nodes included) |
| Terminal node with further calls | BFS continues past terminal to capture full flow |
| Entry point has no outgoing CALLS | Single-node transaction created |
| Duplicate terminal types in branching | Deduplicated in `end_point_types` list |
| Exception during single entry point | Caught, warning added, other entry points still processed |
| Entry point dict missing "fqn" key | Skipped with log warning |

---

## Neo4j Transaction View Query (verification reference)

After Stage 8 writes the graph to Neo4j, the transaction view (Phase 2) queries:

```cypher
-- List all transactions
MATCH (t:Transaction)
RETURN t.name, t.http_method, t.url_path, t.node_count, t.depth
ORDER BY t.name

-- Get full transaction call graph for visualization
MATCH (t:Transaction {name: $txnName})-[:INCLUDES]->(fn:Function)
WITH t, fn
ORDER BY fn.fqn
WITH t, collect(fn) AS functions
MATCH (f1:Function)-[r:CALLS]->(f2:Function)
WHERE f1 IN functions AND f2 IN functions
RETURN t, functions, collect({source: f1.fqn, target: f2.fqn, type: type(r)}) AS edges
```

---

## Relationship to Other Milestones

| Milestone | Relationship |
|-----------|-------------|
| **M1 (Foundation)** | Provides GraphNode, GraphEdge, SymbolGraph, AnalysisContext, enums |
| **M6a (Plugin Base)** | Framework plugins populate `context.entry_points` |
| **M6b (Spring Plugins)** | Spring Web plugin adds HTTP entry points |
| **M7a (Cross-Tech Linker)** | Runs before transactions; adds CALLS_API edges that become terminals |
| **M7b (Graph Enricher)** | Runs before transactions; adds metrics used by transaction nodes |
| **M7c (Neo4j Writer)** | Runs before transactions in pipeline order; writes Transaction nodes to Neo4j |
| **M2 (API/Orchestrator)** | Pipeline orchestrator calls `discover_transactions(context)` as Stage 9 |
| **Phase 2 Visualization** | Transaction view renders these Transaction nodes with dagre LR layout |
