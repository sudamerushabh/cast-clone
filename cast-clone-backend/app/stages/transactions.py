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

            # Follow IMPLEMENTS edges in reverse: if another function implements
            # the current one (interface method -> impl method), also traverse
            # the implementor to pick up its CALLS edges.  This handles the
            # common Java pattern where a controller calls a service *interface*
            # and the real logic lives in the implementation class.
            for edge in graph.get_edges_to(current_fqn):
                if edge.kind == EdgeKind.IMPLEMENTS and edge.source_fqn not in visited:
                    queue.append((edge.source_fqn, current_depth))

    return flow


# ── Transaction Node Builder ───────────────────────────────


_KIND_TO_TYPE: dict[str, str] = {
    "http_endpoint": "http",
    "http": "http",
    "message_consumer": "message",
    "message": "message",
    "scheduled": "scheduled",
    "main": "main",
}


def _entry_point_to_dict(ep: Any) -> dict[str, Any]:
    """Normalize entry point to dict.

    Handles both dict and EntryPoint dataclass.  Maps EntryPoint.kind
    values (e.g. "http_endpoint") to the short type names used by
    _build_transaction_name (e.g. "http").
    """
    if isinstance(ep, dict):
        # Normalize "type" if it uses the long-form kind values
        ep_type = ep.get("type", "unknown")
        if ep_type in _KIND_TO_TYPE:
            ep = {**ep, "type": _KIND_TO_TYPE[ep_type]}
        return ep
    # EntryPoint dataclass: fqn, kind, metadata
    raw_kind = getattr(ep, "kind", "unknown")
    result: dict[str, Any] = {
        "fqn": getattr(ep, "fqn", ""),
        "type": _KIND_TO_TYPE.get(raw_kind, raw_kind),
    }
    metadata = getattr(ep, "metadata", {})
    if metadata:
        result.update(metadata)
    return result


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
    entry_points: list[Any] = getattr(context, "entry_points", [])

    if not entry_points:
        context.transaction_count = 0
        logger.info(
            "transaction_discovery.complete",
            transactions=0,
            reason="no_entry_points",
        )
        return

    transaction_count = 0

    for ep in entry_points:
        try:
            # Normalize to dict (handles both dict and EntryPoint dataclass)
            ep_dict = _entry_point_to_dict(ep)

            entry_fqn = ep_dict.get("fqn")
            if not entry_fqn:
                logger.warning("transaction_discovery.skip_no_fqn", entry_point=str(ep))
                continue

            # Verify entry point exists in graph
            if graph.get_node(entry_fqn) is None:
                context.warnings.append(f"Entry point not found in graph: {entry_fqn}")
                logger.warning(
                    "transaction_discovery.entry_not_in_graph",
                    fqn=entry_fqn,
                )
                continue

            # Trace the flow via BFS
            flow = trace_transaction_flow(entry_fqn, graph, max_depth)

            if len(flow.visited_fqns) < 1:
                continue

            # Build transaction name and FQN
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
                    "http_method": ep_dict.get("method"),
                    "url_path": ep_dict.get("path"),
                },
            )
            graph.add_node(txn_node)

            # STARTS_AT edge: transaction -> entry function
            graph.add_edge(
                GraphEdge(
                    source_fqn=txn_fqn,
                    target_fqn=entry_fqn,
                    kind=EdgeKind.STARTS_AT,
                    confidence=Confidence.HIGH,
                    evidence="transaction-discovery",
                )
            )

            # ENDS_AT edges: transaction -> each terminal function
            for terminal_fqn in flow.terminal_fqns:
                graph.add_edge(
                    GraphEdge(
                        source_fqn=txn_fqn,
                        target_fqn=terminal_fqn,
                        kind=EdgeKind.ENDS_AT,
                        confidence=Confidence.HIGH,
                        evidence="transaction-discovery",
                    )
                )

            # INCLUDES edges with position: transaction -> each function in flow
            for position, fn_fqn in enumerate(flow.visited_fqns):
                graph.add_edge(
                    GraphEdge(
                        source_fqn=txn_fqn,
                        target_fqn=fn_fqn,
                        kind=EdgeKind.INCLUDES,
                        confidence=Confidence.HIGH,
                        evidence="transaction-discovery",
                        properties={"position": position},
                    )
                )

            # Collect TABLE nodes reachable via WRITES/READS from visited functions
            seen_tables: set[str] = set()
            for fn_fqn in flow.visited_fqns:
                for edge in graph.get_edges_from(fn_fqn):
                    if edge.kind in (EdgeKind.WRITES, EdgeKind.READS):
                        table_node = graph.get_node(edge.target_fqn)
                        if table_node is not None and table_node.kind == NodeKind.TABLE and edge.target_fqn not in seen_tables:
                            seen_tables.add(edge.target_fqn)
                            graph.add_edge(
                                GraphEdge(
                                    source_fqn=txn_fqn,
                                    target_fqn=edge.target_fqn,
                                    kind=EdgeKind.INCLUDES,
                                    confidence=Confidence.HIGH,
                                    evidence="transaction-discovery",
                                )
                            )

            transaction_count += 1
            logger.debug(
                "transaction_discovery.created",
                name=txn_name,
                node_count=len(flow.visited_fqns),
                depth=flow.depth,
                terminals=flow.end_point_types,
            )

        except Exception as e:
            if isinstance(ep, dict):
                ep_fqn = ep.get("fqn", "?")
            else:
                ep_fqn = getattr(ep, "fqn", str(ep))
            msg = f"Transaction discovery failed for {ep_fqn}: {e}"
            context.warnings.append(msg)
            logger.warning(
                "transaction_discovery.entry_failed",
                entry=ep_fqn,
                error=str(e),
            )

    context.transaction_count = transaction_count
    logger.info(
        "transaction_discovery.complete",
        project_id=context.project_id,
        transactions=transaction_count,
        entry_points_scanned=len(entry_points),
    )
