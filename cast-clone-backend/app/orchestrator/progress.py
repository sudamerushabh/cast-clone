"""WebSocket-based progress reporting for analysis pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from app.models.context import AnalysisContext

try:
    from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
except ImportError:  # pragma: no cover - fallback when websockets driver absent
    ConnectionClosedError = ConnectionClosedOK = RuntimeError  # type: ignore[assignment,misc]

logger = structlog.get_logger(__name__)

# Active WebSocket connections per project_id
active_connections: dict[str, list[WebSocket]] = {}

# CHAN-73: live AnalysisContext per project_id, populated by the pipeline
# entry point and consumed by the DELETE /projects/{id}/analyze endpoint
# to flip ``context.cancelled=True``. Kept next to ``active_connections``
# for symmetry — both are per-process in-memory maps that mirror the
# pipeline's runtime state. Single-pipeline-per-project is already
# enforced by ``POST /analyze`` (409 if status=="analyzing"), so the
# map-not-dict choice is deliberate.
active_contexts: dict[str, AnalysisContext] = {}


def _remove_dead_connections(project_id: str, dead: list[WebSocket]) -> None:
    """Remove dead WebSocket connections from active_connections in-place."""
    if not dead:
        return
    connections = active_connections.get(project_id, [])
    for ws in dead:
        if ws in connections:
            connections.remove(ws)
    if not connections and project_id in active_connections:
        del active_connections[project_id]
    logger.info(
        "websocket_disconnected",
        project_id=project_id,
        count=len(dead),
    )


class WebSocketProgressReporter:
    """Emits progress events to all WebSocket clients watching a project."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    async def emit(
        self,
        stage: str,
        status: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Send a progress event to all connected clients for this project.

        Dead connections (WebSocketDisconnect, closed state, runtime errors)
        are collected and evicted after the broadcast loop to avoid mutating
        the collection mid-iteration and to prevent unbounded memory growth.
        """
        event = {
            "stage": stage,
            "status": status,
            "message": message,
            "details": details or {},
            "timestamp": datetime.now(UTC).isoformat(),
        }
        connections = active_connections.get(self.project_id, [])
        dead: list[WebSocket] = []
        for ws in list(connections):
            try:
                await ws.send_json(event)
            except (
                WebSocketDisconnect,
                RuntimeError,
                ConnectionClosedError,
                ConnectionClosedOK,
            ) as exc:
                logger.info(
                    "websocket_send_failed",
                    project_id=self.project_id,
                    error_type=type(exc).__name__,
                )
                dead.append(ws)
        _remove_dead_connections(self.project_id, dead)

    async def emit_complete(self, report: dict[str, Any]) -> None:
        """Emit pipeline completion event."""
        await self.emit("complete", "complete", details=report)

    async def emit_error(self, error: str) -> None:
        """Emit pipeline error event."""
        await self.emit("error", "failed", message=error)
