"""Celery producer-site resolution helpers (M3).

Given a SymbolGraph plus the map of task FQN → queue name (built by
CeleryPlugin), find CALLS edges whose target is a Celery trigger method
(``.delay``, ``.apply_async``, ``.s``, ``.signature``), resolve the
producing caller, and emit PRODUCES edges from the caller to the queue.
"""

from __future__ import annotations

from app.models.enums import Confidence, EdgeKind
from app.models.graph import GraphEdge

_TRIGGER_METHODS: tuple[str, ...] = (".delay", ".apply_async", ".s", ".signature")


def resolve_producer_edges(graph, task_to_queue: dict[str, str]) -> list[GraphEdge]:
    """Return PRODUCES edges for each CALLS edge that hits a Celery trigger method."""
    edges: list[GraphEdge] = []
    for call in graph.edges:
        if call.kind != EdgeKind.CALLS:
            continue
        target = call.target_fqn
        base_fqn: str | None = None
        for suffix in _TRIGGER_METHODS:
            if target.endswith(suffix):
                base_fqn = target[: -len(suffix)]
                break
        if base_fqn is None:
            continue
        queue = task_to_queue.get(base_fqn)
        if queue is None:
            continue
        edges.append(
            GraphEdge(
                source_fqn=call.source_fqn,
                target_fqn=f"queue::{queue}",
                kind=EdgeKind.PRODUCES,
                confidence=Confidence.HIGH,
                evidence="celery-producer",
                properties={"queue": queue},
            )
        )
    return edges
