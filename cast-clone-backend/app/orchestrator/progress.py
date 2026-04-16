"""WebSocket-based progress reporting for analysis pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

logger = structlog.get_logger(__name__)

# Active WebSocket connections per project_id
active_connections: dict[str, list[WebSocket]] = {}


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
            except (WebSocketDisconnect, RuntimeError):
                dead.append(ws)
            except Exception as exc:
                # Catch-all for driver-level ConnectionClosedError variants
                # that aren't importable across websockets versions.
                logger.warning(
                    "websocket_send_failed",
                    project_id=self.project_id,
                    error=str(exc),
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
