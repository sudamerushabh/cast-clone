# tests/unit/test_websocket.py
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.orchestrator.progress import active_connections


@pytest.fixture(autouse=True)
def clear_ws_connections():
    active_connections.clear()
    yield
    active_connections.clear()


class TestWebSocketEndpoint:
    def test_websocket_connects_and_registers(self):
        """WebSocket connection should be registered in active_connections."""
        from app.main import create_app

        app = create_app()
        client = TestClient(app)

        with client.websocket_connect("/api/v1/projects/proj-1/progress") as ws:
            assert "proj-1" in active_connections
            assert len(active_connections["proj-1"]) == 1

        # After disconnect, connection should be removed
        assert len(active_connections.get("proj-1", [])) == 0

    def test_websocket_multiple_connections(self):
        """Multiple WebSocket clients can connect to the same project."""
        from app.main import create_app

        app = create_app()
        client = TestClient(app)

        with client.websocket_connect("/api/v1/projects/proj-1/progress") as ws1:
            with client.websocket_connect("/api/v1/projects/proj-1/progress") as ws2:
                assert len(active_connections["proj-1"]) == 2
