"""WebSocket-based progress reporting for analysis pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

# Active WebSocket connections per project_id
active_connections: dict[str, list[WebSocket]] = {}


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
        """Send a progress event to all connected clients for this project."""
        event = {
            "stage": stage,
            "status": status,
            "message": message,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for ws in active_connections.get(self.project_id, []):
            try:
                await ws.send_json(event)
            except Exception:
                pass  # Connection may have closed

    async def emit_complete(self, report: dict[str, Any]) -> None:
        """Emit pipeline completion event."""
        await self.emit("complete", "complete", details=report)

    async def emit_error(self, error: str) -> None:
        """Emit pipeline error event."""
        await self.emit("error", "failed", message=error)
