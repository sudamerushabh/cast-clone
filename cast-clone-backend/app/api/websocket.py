"""WebSocket endpoint for real-time analysis progress."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.orchestrator.progress import active_connections

router = APIRouter(tags=["websocket"])


@router.websocket("/api/v1/projects/{project_id}/progress")
async def analysis_progress(websocket: WebSocket, project_id: str) -> None:
    """WebSocket endpoint for streaming analysis progress events.

    Clients connect here before triggering analysis. The pipeline's
    WebSocketProgressReporter emits events to all connected clients.
    """
    await websocket.accept()
    active_connections.setdefault(project_id, []).append(websocket)

    try:
        while True:
            # Keep connection alive — client can send pings or messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connections = active_connections.get(project_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections and project_id in active_connections:
            del active_connections[project_id]
