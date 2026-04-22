# tests/unit/test_transactions.py
"""Tests for Stage 9: Transaction Discovery."""

import pytest

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.manifest import ProjectManifest
from app.stages.transactions import (
    DEFAULT_MAX_DEPTH,
    classify_terminal_node,
    discover_transactions,
    trace_transaction_flow,
)


def _make_context(graph: SymbolGraph) -> AnalysisContext:
    """Build an AnalysisContext with a pre-populated graph."""
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


def _fn(fqn: str, name: str = "") -> GraphNode:
    """Shorthand for creating a FUNCTION node."""
    return GraphNode(
        fqn=fqn,
        name=name or fqn.rsplit(".", 1)[-1],
        kind=NodeKind.FUNCTION,
    )


def _fn_lang(fqn: str, name: str, lang: str) -> GraphNode:
    """Shorthand for a FUNCTION node with language."""
    return GraphNode(fqn=fqn, name=name, kind=NodeKind.FUNCTION, language=lang)


def _edge(src: str, tgt: str, kind: EdgeKind) -> GraphEdge:
    """Shorthand for creating a GraphEdge."""
    return GraphEdge(source_fqn=src, target_fqn=tgt, kind=kind)


# ── Terminal Node Classification ───────────────────────────


class TestClassifyTerminalNode:
    """Tests for classify_terminal_node()."""

    def test_table_write_is_terminal(self):
        """WRITES -> Table edge: TABLE_WRITE."""
        g = SymbolGraph()
        g.add_node(_fn("com.A.save", "save"))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))
        g.add_edge(_edge("com.A.save", "users", EdgeKind.WRITES))

        assert classify_terminal_node("com.A.save", g) == "TABLE_WRITE"

    def test_table_read_is_terminal(self):
        """READS -> Table edge: TABLE_READ."""
        g = SymbolGraph()
        g.add_node(_fn("com.A.find", "find"))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))
        g.add_edge(_edge("com.A.find", "users", EdgeKind.READS))

        assert classify_terminal_node("com.A.find", g) == "TABLE_READ"

    def test_message_produce_is_terminal(self):
        """PRODUCES -> MessageTopic: MESSAGE_PUBLISH."""
        g = SymbolGraph()
        g.add_node(_fn("com.A.send", "send"))
        g.add_node(
            GraphNode(
                fqn="topic:events",
                name="events",
                kind=NodeKind.MESSAGE_TOPIC,
            )
        )
        g.add_edge(_edge("com.A.send", "topic:events", EdgeKind.PRODUCES))

        assert classify_terminal_node("com.A.send", g) == "MESSAGE_PUBLISH"

    def test_api_call_is_terminal(self):
        """CALLS_API -> APIEndpoint: EXTERNAL_API_CALL."""
        g = SymbolGraph()
        g.add_node(_fn("src.api.call", "call"))
        g.add_node(
            GraphNode(
                fqn="GET:/ext/api",
                name="GET /ext/api",
                kind=NodeKind.API_ENDPOINT,
            )
        )
        g.add_edge(_edge("src.api.call", "GET:/ext/api", EdgeKind.CALLS_API))

        result = classify_terminal_node("src.api.call", g)
        assert result == "EXTERNAL_API_CALL"

    def test_non_terminal_returns_none(self):
        """Function with only CALLS edges is not terminal."""
        g = SymbolGraph()
        g.add_node(_fn("com.A.process", "process"))
        g.add_node(_fn("com.B.helper", "helper"))
        g.add_edge(_edge("com.A.process", "com.B.helper", EdgeKind.CALLS))

        assert classify_terminal_node("com.A.process", g) is None

    def test_node_with_no_edges_returns_none(self):
        """Function with no outgoing edges is not terminal."""
        g = SymbolGraph()
        g.add_node(_fn("com.A.leaf", "leaf"))

        assert classify_terminal_node("com.A.leaf", g) is None


# ── Transaction Flow Tracing ───────────────────────────────


class TestTraceTransactionFlow:
    """Tests for trace_transaction_flow() BFS traversal."""

    def test_simple_linear_chain(self):
        """A -> B -> C(writes TABLE) produces flow with 3 nodes."""
        g = SymbolGraph()
        g.add_node(_fn("A.handle", "handle"))
        g.add_node(_fn("B.process", "process"))
        g.add_node(_fn("C.save", "save"))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))

        g.add_edge(_edge("A.handle", "B.process", EdgeKind.CALLS))
        g.add_edge(_edge("B.process", "C.save", EdgeKind.CALLS))
        g.add_edge(_edge("C.save", "users", EdgeKind.WRITES))

        flow = trace_transaction_flow("A.handle", g, max_depth=15)

        assert len(flow.visited_fqns) == 3
        assert flow.visited_fqns == ["A.handle", "B.process", "C.save"]
        assert "TABLE_WRITE" in flow.end_point_types
        assert flow.depth == 2
        assert "C.save" in flow.terminal_fqns

    def test_branching_chain(self):
        """A -> B, A -> C covers both branches."""
        g = SymbolGraph()
        g.add_node(_fn("A.handle", "handle"))
        g.add_node(_fn("B.save", "save"))
        g.add_node(_fn("C.notify", "notify"))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))
        g.add_node(
            GraphNode(
                fqn="topic:events",
                name="events",
                kind=NodeKind.MESSAGE_TOPIC,
            )
        )

        g.add_edge(_edge("A.handle", "B.save", EdgeKind.CALLS))
        g.add_edge(_edge("A.handle", "C.notify", EdgeKind.CALLS))
        g.add_edge(_edge("B.save", "users", EdgeKind.WRITES))
        g.add_edge(_edge("C.notify", "topic:events", EdgeKind.PRODUCES))

        flow = trace_transaction_flow("A.handle", g, max_depth=15)

        assert len(flow.visited_fqns) == 3
        assert set(flow.end_point_types) == {
            "TABLE_WRITE",
            "MESSAGE_PUBLISH",
        }
        assert len(flow.terminal_fqns) == 2

    def test_cycle_detection(self):
        """Cycles don't cause infinite loops."""
        g = SymbolGraph()
        g.add_node(_fn("A.fn"))
        g.add_node(_fn("B.fn"))
        g.add_node(_fn("C.fn"))
        g.add_edge(_edge("A.fn", "B.fn", EdgeKind.CALLS))
        g.add_edge(_edge("B.fn", "C.fn", EdgeKind.CALLS))
        g.add_edge(_edge("C.fn", "A.fn", EdgeKind.CALLS))

        flow = trace_transaction_flow("A.fn", g, max_depth=15)

        assert len(flow.visited_fqns) == 3
        assert flow.depth == 2

    def test_max_depth_limits_traversal(self):
        """Flow stops at max_depth even without terminal nodes."""
        g = SymbolGraph()
        for i in range(20):
            g.add_node(_fn(f"N{i}.fn"))
        for i in range(19):
            g.add_edge(_edge(f"N{i}.fn", f"N{i + 1}.fn", EdgeKind.CALLS))

        flow = trace_transaction_flow("N0.fn", g, max_depth=5)

        # N0..N5 (depth 0 through 5) = 6 nodes
        assert len(flow.visited_fqns) == 6
        assert flow.visited_fqns[-1] == "N5.fn"
        assert "N6.fn" not in flow.visited_fqns
        assert flow.depth == 5

    def test_single_node_no_calls(self):
        """Entry with no outgoing CALLS: single-node flow."""
        g = SymbolGraph()
        g.add_node(_fn("A.fn"))

        flow = trace_transaction_flow("A.fn", g, max_depth=15)

        assert flow.visited_fqns == ["A.fn"]
        assert flow.depth == 0
        assert flow.end_point_types == []
        assert flow.terminal_fqns == []

    def test_does_not_follow_contains_edges(self):
        """BFS does not follow CONTAINS edges."""
        g = SymbolGraph()
        g.add_node(_fn("A.fn"))
        g.add_node(_fn("B.fn"))
        g.add_node(_fn("C.fn"))
        g.add_edge(_edge("A.fn", "B.fn", EdgeKind.CALLS))
        g.add_edge(_edge("A.fn", "C.fn", EdgeKind.CONTAINS))

        flow = trace_transaction_flow("A.fn", g, max_depth=15)

        assert len(flow.visited_fqns) == 2
        assert "C.fn" not in flow.visited_fqns

    def test_follows_injects_edges(self):
        """BFS follows INJECTS edges (Spring DI)."""
        g = SymbolGraph()
        g.add_node(_fn("A.fn"))
        g.add_node(_fn("B.fn"))
        g.add_node(_fn("C.fn"))
        g.add_edge(_edge("A.fn", "B.fn", EdgeKind.INJECTS))
        g.add_edge(_edge("B.fn", "C.fn", EdgeKind.CALLS))

        flow = trace_transaction_flow("A.fn", g, max_depth=15)

        assert len(flow.visited_fqns) == 3
        assert "B.fn" in flow.visited_fqns
        assert "C.fn" in flow.visited_fqns

    def test_follows_depends_on_edges(self):
        """BFS follows DEPENDS_ON edges."""
        g = SymbolGraph()
        g.add_node(_fn("A.fn"))
        g.add_node(_fn("B.fn"))
        g.add_edge(_edge("A.fn", "B.fn", EdgeKind.DEPENDS_ON))

        flow = trace_transaction_flow("A.fn", g, max_depth=15)

        assert len(flow.visited_fqns) == 2
        assert "B.fn" in flow.visited_fqns

    def test_follows_virtual_dispatch_calls(self):
        """BFS follows virtual dispatch CALLS edges (interface → impl)."""
        g = SymbolGraph()
        g.add_node(_fn("ctrl.addAccount"))
        g.add_node(_fn("svc.AccountService.createAccount"))
        g.add_node(_fn("svc.AccountServiceImpl.createAccount"))
        g.add_node(_fn("repo.AccountRepository.save"))

        g.add_edge(
            _edge("ctrl.addAccount", "svc.AccountService.createAccount", EdgeKind.CALLS)
        )
        # Virtual dispatch CALLS edge (created by enricher)
        g.add_edge(
            _edge(
                "svc.AccountService.createAccount",
                "svc.AccountServiceImpl.createAccount",
                EdgeKind.CALLS,
            )
        )
        g.add_edge(
            _edge(
                "svc.AccountServiceImpl.createAccount",
                "repo.AccountRepository.save",
                EdgeKind.CALLS,
            )
        )

        flow = trace_transaction_flow("ctrl.addAccount", g, max_depth=15)

        assert "svc.AccountServiceImpl.createAccount" in flow.visited_fqns
        assert "repo.AccountRepository.save" in flow.visited_fqns

    def test_does_not_follow_implements_edges(self):
        """BFS no longer follows IMPLEMENTS edges — virtual dispatch handles this."""
        g = SymbolGraph()
        g.add_node(_fn("ctrl.addAccount"))
        g.add_node(_fn("svc.AccountService.createAccount"))
        g.add_node(_fn("svc.AccountServiceImpl.createAccount"))

        g.add_edge(
            _edge("ctrl.addAccount", "svc.AccountService.createAccount", EdgeKind.CALLS)
        )
        # Only IMPLEMENTS edge (no virtual dispatch CALLS) — should NOT be followed
        g.add_edge(
            _edge(
                "svc.AccountServiceImpl.createAccount",
                "svc.AccountService.createAccount",
                EdgeKind.IMPLEMENTS,
            )
        )

        flow = trace_transaction_flow("ctrl.addAccount", g, max_depth=15)

        # Without virtual dispatch CALLS edge, impl should NOT be reached
        assert "svc.AccountServiceImpl.createAccount" not in flow.visited_fqns

    def test_skips_constructor_nodes(self):
        """BFS skips <init>, <clinit>, __init__ constructor nodes."""
        g = SymbolGraph()
        g.add_node(_fn("A.handle", "handle"))
        g.add_node(_fn("B.<init>", "<init>"))
        g.add_node(_fn("C.process", "process"))

        g.add_edge(_edge("A.handle", "B.<init>", EdgeKind.CALLS))
        g.add_edge(_edge("A.handle", "C.process", EdgeKind.CALLS))

        flow = trace_transaction_flow("A.handle", g, max_depth=15)

        assert "B.<init>" not in flow.visited_fqns
        assert "C.process" in flow.visited_fqns

    def test_filter_order_prevents_duplicate_transactions(self):
        """Dedupe before filter: the same constructor reachable from N callers
        must not be appended to the flow or re-processed N times.

        Graph shape:
            A -[:CALLS]-> X.<init>
            A -[:CALLS]-> B
            B -[:CALLS]-> X.<init>
            B -[:CALLS]-> C
            X.<init> -[:CALLS]-> D
            D -[:WRITES]-> users
        """
        g = SymbolGraph()
        g.add_node(_fn("A.handle", "handle"))
        g.add_node(_fn("B.step", "step"))
        g.add_node(_fn("C.leaf", "leaf"))
        g.add_node(_fn("D.persist", "persist"))
        g.add_node(_fn("X.<init>", "<init>"))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))

        g.add_edge(_edge("A.handle", "X.<init>", EdgeKind.CALLS))
        g.add_edge(_edge("A.handle", "B.step", EdgeKind.CALLS))
        g.add_edge(_edge("B.step", "X.<init>", EdgeKind.CALLS))
        g.add_edge(_edge("B.step", "C.leaf", EdgeKind.CALLS))
        g.add_edge(_edge("X.<init>", "D.persist", EdgeKind.CALLS))
        g.add_edge(_edge("D.persist", "users", EdgeKind.WRITES))

        flow = trace_transaction_flow("A.handle", g, max_depth=15)

        # Constructor is filtered out of the flow regardless of how many
        # callers reach it.
        assert "X.<init>" not in flow.visited_fqns
        # No duplicates in the flow list.
        assert len(flow.visited_fqns) == len(set(flow.visited_fqns))
        # Option A (CHAN-81): descendants reachable only via the constructor
        # (D.persist via X.<init>) are still walked and included in the flow.
        assert sorted(flow.visited_fqns) == [
            "A.handle",
            "B.step",
            "C.leaf",
            "D.persist",
        ]
        # Terminal classification still picks up the TABLE_WRITE past the
        # constructor subtree.
        assert "TABLE_WRITE" in flow.end_point_types
        assert "D.persist" in flow.terminal_fqns

    def test_constructor_subtree_traversed(self):
        """Option A (CHAN-81): a node reachable ONLY via a constructor is
        still walked and recorded in ``flow.visited_fqns``.

        Graph shape:
            A.handle -[:CALLS]-> X.<init>
            X.<init> -[:CALLS]-> D.persist
            D.persist -[:WRITES]-> users
        """
        g = SymbolGraph()
        g.add_node(_fn("A.handle", "handle"))
        g.add_node(_fn("X.<init>", "<init>"))
        g.add_node(_fn("D.persist", "persist"))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))

        g.add_edge(_edge("A.handle", "X.<init>", EdgeKind.CALLS))
        g.add_edge(_edge("X.<init>", "D.persist", EdgeKind.CALLS))
        g.add_edge(_edge("D.persist", "users", EdgeKind.WRITES))

        flow = trace_transaction_flow("A.handle", g, max_depth=15)

        # Constructor excluded from the flow...
        assert "X.<init>" not in flow.visited_fqns
        # ...but its descendants are still traversed.
        assert "D.persist" in flow.visited_fqns
        assert sorted(flow.visited_fqns) == ["A.handle", "D.persist"]
        # Terminal classification picks up the WRITE past the constructor.
        assert "TABLE_WRITE" in flow.end_point_types
        assert "D.persist" in flow.terminal_fqns

    def test_filter_applied_to_deduplicated_set(self, monkeypatch):
        """Filter predicate (`name in _CONSTRUCTOR_NAMES`) must run at most once
        per unique FQN — not once per incoming CALLS edge.

        Same graph as above; counts `frozenset.__contains__` calls on
        `_CONSTRUCTOR_NAMES` via a spy wrapper on `graph.get_node`.
        """
        g = SymbolGraph()
        g.add_node(_fn("A.handle", "handle"))
        g.add_node(_fn("B.step", "step"))
        g.add_node(_fn("X.<init>", "<init>"))

        g.add_edge(_edge("A.handle", "X.<init>", EdgeKind.CALLS))
        g.add_edge(_edge("A.handle", "B.step", EdgeKind.CALLS))
        g.add_edge(_edge("B.step", "X.<init>", EdgeKind.CALLS))

        # Spy on get_node: it is called once per unique FQN popped from
        # the queue after the dedupe guard. Constructor X.<init> is enqueued
        # twice (from A.handle and B.step), but should only trigger a
        # get_node + filter pass once.
        original_get_node = g.get_node
        calls: list[str] = []

        def spy_get_node(fqn: str):
            calls.append(fqn)
            return original_get_node(fqn)

        monkeypatch.setattr(g, "get_node", spy_get_node)

        flow = trace_transaction_flow("A.handle", g, max_depth=15)

        # Each unique FQN is inspected exactly once.
        assert calls.count("X.<init>") == 1
        assert calls.count("A.handle") == 1
        assert calls.count("B.step") == 1
        # Constructor excluded from flow.
        assert "X.<init>" not in flow.visited_fqns
        assert sorted(flow.visited_fqns) == ["A.handle", "B.step"]

    def test_terminal_node_still_continues_bfs(self):
        """BFS continues past terminal nodes."""
        g = SymbolGraph()
        g.add_node(_fn("A.fn"))
        g.add_node(_fn("B.fn"))
        g.add_node(_fn("C.fn"))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))

        g.add_edge(_edge("A.fn", "B.fn", EdgeKind.CALLS))
        g.add_edge(_edge("B.fn", "users", EdgeKind.WRITES))
        g.add_edge(_edge("B.fn", "C.fn", EdgeKind.CALLS))

        flow = trace_transaction_flow("A.fn", g, max_depth=15)

        assert len(flow.visited_fqns) == 3
        assert "B.fn" in flow.terminal_fqns
        assert "C.fn" in flow.visited_fqns


# ── Integration: discover_transactions ─────────────────────


class TestDiscoverTransactions:
    """Tests for the main discover_transactions() entry point."""

    @pytest.mark.asyncio
    async def test_http_entry_point_creates_transaction(self):
        """HTTP entry point produces a Transaction node."""
        g = SymbolGraph()

        g.add_node(_fn_lang("com.UserCtrl.getUsers", "getUsers", "java"))
        g.add_node(_fn_lang("com.UserRepo.findAll", "findAll", "java"))
        g.add_node(GraphNode(fqn="users", name="users", kind=NodeKind.TABLE))

        g.add_edge(
            _edge(
                "com.UserCtrl.getUsers",
                "com.UserRepo.findAll",
                EdgeKind.CALLS,
            )
        )
        g.add_edge(_edge("com.UserRepo.findAll", "users", EdgeKind.READS))

        ctx = _make_context(g)
        ctx.entry_points = [
            {
                "fqn": "com.UserCtrl.getUsers",
                "type": "http",
                "method": "GET",
                "path": "/api/users",
            }
        ]

        await discover_transactions(ctx)

        assert ctx.transaction_count == 1

        # Verify Transaction node
        txn_nodes = [
            n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION
        ]
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

        # Verify ENDS_AT edge
        ends_at = [e for e in ctx.graph.edges if e.kind == EdgeKind.ENDS_AT]
        assert len(ends_at) == 1
        assert ends_at[0].target_fqn == "com.UserRepo.findAll"

        # Verify INCLUDES edges with positions (2 functions + 1 table)
        includes = [e for e in ctx.graph.edges if e.kind == EdgeKind.INCLUDES]
        assert len(includes) == 3
        fn_includes = [e for e in includes if e.properties.get("position") is not None]
        positions = sorted([e.properties["position"] for e in fn_includes])
        assert positions == [0, 1]
        table_includes = [e for e in includes if e.target_fqn == "users"]
        assert len(table_includes) == 1

    @pytest.mark.asyncio
    async def test_message_consumer_entry_point(self):
        """Message consumer entry point naming."""
        g = SymbolGraph()

        g.add_node(_fn("com.OrderHandler.onEvent", "onEvent"))
        g.add_node(_fn("com.OrderRepo.save", "save"))
        g.add_node(GraphNode(fqn="orders", name="orders", kind=NodeKind.TABLE))

        g.add_edge(
            _edge(
                "com.OrderHandler.onEvent",
                "com.OrderRepo.save",
                EdgeKind.CALLS,
            )
        )
        g.add_edge(_edge("com.OrderRepo.save", "orders", EdgeKind.WRITES))

        ctx = _make_context(g)
        ctx.entry_points = [
            {
                "fqn": "com.OrderHandler.onEvent",
                "type": "message",
                "topic": "order-events",
            }
        ]

        await discover_transactions(ctx)

        assert ctx.transaction_count == 1
        txn_nodes = [
            n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION
        ]
        assert len(txn_nodes) == 1
        assert "order-events" in txn_nodes[0].name

    @pytest.mark.asyncio
    async def test_no_entry_points_no_transactions(self):
        """Empty entry_points -> 0 transactions, no errors."""
        g = SymbolGraph()
        ctx = _make_context(g)
        ctx.entry_points = []

        await discover_transactions(ctx)

        assert ctx.transaction_count == 0
        txn_nodes = [
            n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION
        ]
        assert len(txn_nodes) == 0

    @pytest.mark.asyncio
    async def test_entry_point_not_in_graph_skips_with_warning(self):
        """Missing FQN -> skip with warning, don't crash."""
        g = SymbolGraph()
        ctx = _make_context(g)
        ctx.entry_points = [
            {
                "fqn": "com.Missing.handler",
                "type": "http",
                "method": "GET",
                "path": "/missing",
            }
        ]

        await discover_transactions(ctx)

        assert ctx.transaction_count == 0
        assert any("com.Missing.handler" in w for w in ctx.warnings)

    @pytest.mark.asyncio
    async def test_multiple_entry_points_create_multiple_transactions(
        self,
    ):
        """3 entry points produce 3 Transaction nodes."""
        g = SymbolGraph()

        for name in ["A", "B", "C"]:
            g.add_node(_fn(f"com.{name}.handle", "handle"))

        ctx = _make_context(g)
        ctx.entry_points = [
            {"fqn": "com.A.handle", "type": "http", "method": "GET", "path": "/a"},
            {"fqn": "com.B.handle", "type": "http", "method": "POST", "path": "/b"},
            {"fqn": "com.C.handle", "type": "http", "method": "DELETE", "path": "/c"},
        ]

        await discover_transactions(ctx)

        assert ctx.transaction_count == 3
        txn_nodes = [
            n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION
        ]
        assert len(txn_nodes) == 3

    @pytest.mark.asyncio
    async def test_entrypoint_dataclass_http_endpoint_kind(self):
        """EntryPoint with kind='http_endpoint' produces correct HTTP naming."""
        g = SymbolGraph()
        g.add_node(_fn("com.Ctrl.list", "list"))
        g.add_node(GraphNode(fqn="items", name="items", kind=NodeKind.TABLE))
        g.add_edge(_edge("com.Ctrl.list", "items", EdgeKind.READS))

        ctx = _make_context(g)
        ctx.entry_points = [
            EntryPoint(
                fqn="com.Ctrl.list",
                kind="http_endpoint",
                metadata={"method": "GET", "path": "/api/items"},
            )
        ]

        await discover_transactions(ctx)

        assert ctx.transaction_count == 1
        txn_nodes = [
            n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION
        ]
        assert len(txn_nodes) == 1
        assert "GET" in txn_nodes[0].name
        assert "/api/items" in txn_nodes[0].name

    @pytest.mark.asyncio
    async def test_entrypoint_dataclass_message_consumer_kind(self):
        """EntryPoint with kind='message_consumer' produces correct MSG naming."""
        g = SymbolGraph()
        g.add_node(_fn("com.Handler.on", "on"))

        ctx = _make_context(g)
        ctx.entry_points = [
            EntryPoint(
                fqn="com.Handler.on",
                kind="message_consumer",
                metadata={"topic": "user-events"},
            )
        ]

        await discover_transactions(ctx)

        assert ctx.transaction_count == 1
        txn_nodes = [
            n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION
        ]
        assert len(txn_nodes) == 1
        assert "user-events" in txn_nodes[0].name
        assert txn_nodes[0].name.startswith("MSG")

    @pytest.mark.asyncio
    async def test_default_max_depth_is_15(self):
        """DEFAULT_MAX_DEPTH constant is 15."""
        assert DEFAULT_MAX_DEPTH == 15


# ── TABLE node inclusion in transactions ──────────────────


def _build_controller_service_repo_graph() -> tuple[SymbolGraph, list[EntryPoint]]:
    """
    Controller.addAccount -[:CALLS]-> Service.createAccount
      -[:CALLS]-> AccountRepository.save   (stub JPA node)
        -[:WRITES]-> table:accounts
    """
    graph = SymbolGraph()

    for fqn, name in [
        ("com.example.AccountController.addAccount", "addAccount"),
        ("com.example.AccountService.createAccount", "createAccount"),
        ("com.example.AccountRepository.save", "save"),
    ]:
        graph.add_node(
            GraphNode(fqn=fqn, name=name, kind=NodeKind.FUNCTION, language="java")
        )

    table = GraphNode(
        fqn="table:accounts", name="accounts", kind=NodeKind.TABLE, properties={}
    )
    graph.add_node(table)

    graph.add_edge(
        GraphEdge(
            source_fqn="com.example.AccountController.addAccount",
            target_fqn="com.example.AccountService.createAccount",
            kind=EdgeKind.CALLS,
            confidence=Confidence.HIGH,
            evidence="tree-sitter",
        )
    )
    graph.add_edge(
        GraphEdge(
            source_fqn="com.example.AccountService.createAccount",
            target_fqn="com.example.AccountRepository.save",
            kind=EdgeKind.CALLS,
            confidence=Confidence.MEDIUM,
            evidence="tree-sitter",
        )
    )
    graph.add_edge(
        GraphEdge(
            source_fqn="com.example.AccountRepository.save",
            target_fqn="table:accounts",
            kind=EdgeKind.WRITES,
            confidence=Confidence.HIGH,
            evidence="spring-data",
        )
    )

    entry_points = [
        EntryPoint(
            fqn="com.example.AccountController.addAccount",
            kind="http_endpoint",
            metadata={"method": "POST", "path": "/accounts"},
        )
    ]
    return graph, entry_points


@pytest.mark.asyncio
async def test_transaction_includes_table_nodes():
    """Transaction INCLUDES edges should also point to TABLE nodes."""
    graph, entry_points = _build_controller_service_repo_graph()
    ctx = _make_context(graph)
    ctx.entry_points = entry_points

    await discover_transactions(ctx)

    txn_nodes = [n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION]
    assert len(txn_nodes) == 1
    txn_fqn = txn_nodes[0].fqn

    includes_targets = {
        e.target_fqn
        for e in ctx.graph.edges
        if e.kind == EdgeKind.INCLUDES and e.source_fqn == txn_fqn
    }

    assert "com.example.AccountController.addAccount" in includes_targets
    assert "com.example.AccountService.createAccount" in includes_targets
    assert "com.example.AccountRepository.save" in includes_targets
    assert "table:accounts" in includes_targets


@pytest.mark.asyncio
async def test_transaction_no_duplicate_table_includes():
    """Two functions writing to the same table produce only one INCLUDES edge."""
    graph, entry_points = _build_controller_service_repo_graph()

    graph.add_node(
        GraphNode(
            fqn="com.example.AccountRepository.deleteById",
            name="deleteById",
            kind=NodeKind.FUNCTION,
            language="java",
        )
    )
    graph.add_edge(
        GraphEdge(
            source_fqn="com.example.AccountService.createAccount",
            target_fqn="com.example.AccountRepository.deleteById",
            kind=EdgeKind.CALLS,
            confidence=Confidence.MEDIUM,
            evidence="tree-sitter",
        )
    )
    graph.add_edge(
        GraphEdge(
            source_fqn="com.example.AccountRepository.deleteById",
            target_fqn="table:accounts",
            kind=EdgeKind.WRITES,
            confidence=Confidence.HIGH,
            evidence="spring-data",
        )
    )

    ctx = _make_context(graph)
    ctx.entry_points = entry_points

    await discover_transactions(ctx)

    txn_fqn = next(
        n.fqn for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION
    )
    table_includes = [
        e
        for e in ctx.graph.edges
        if e.kind == EdgeKind.INCLUDES
        and e.source_fqn == txn_fqn
        and e.target_fqn == "table:accounts"
    ]
    assert len(table_includes) == 1
