# tests/unit/test_progress.py
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestrator.progress import (
    WebSocketProgressReporter,
    active_connections,
)


@pytest.fixture(autouse=True)
def clear_connections():
    """Ensure clean state for each test."""
    active_connections.clear()
    yield
    active_connections.clear()


class TestWebSocketProgressReporter:
    @pytest.mark.asyncio
    async def test_emit_sends_json_to_connected_ws(self):
        ws = AsyncMock()
        active_connections["proj-1"] = [ws]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit("discovery", "running", "Scanning filesystem...")

        ws.send_json.assert_called_once()
        event = ws.send_json.call_args[0][0]
        assert event["stage"] == "discovery"
        assert event["status"] == "running"
        assert event["message"] == "Scanning filesystem..."
        assert "timestamp" in event

    @pytest.mark.asyncio
    async def test_emit_with_details(self):
        ws = AsyncMock()
        active_connections["proj-1"] = [ws]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit("parsing", "complete", details={"nodes": 100, "edges": 200})

        event = ws.send_json.call_args[0][0]
        assert event["details"]["nodes"] == 100
        assert event["details"]["edges"] == 200

    @pytest.mark.asyncio
    async def test_emit_no_connections(self):
        reporter = WebSocketProgressReporter("proj-no-ws")
        # Should not raise
        await reporter.emit("discovery", "running", "test")

    @pytest.mark.asyncio
    async def test_emit_handles_broken_connection(self):
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = RuntimeError("connection closed")
        active_connections["proj-1"] = [ws_bad, ws_good]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit("discovery", "running", "test")

        # Good connection still receives the message
        ws_good.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_complete(self):
        ws = AsyncMock()
        active_connections["proj-1"] = [ws]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit_complete({"total_nodes": 500, "total_edges": 1000})

        event = ws.send_json.call_args[0][0]
        assert event["stage"] == "complete"
        assert event["status"] == "complete"
        assert event["details"]["total_nodes"] == 500

    @pytest.mark.asyncio
    async def test_emit_error(self):
        ws = AsyncMock()
        active_connections["proj-1"] = [ws]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit_error("Stage 1 failed: path not found")

        event = ws.send_json.call_args[0][0]
        assert event["stage"] == "error"
        assert event["status"] == "failed"
        assert "path not found" in event["message"]

    @pytest.mark.asyncio
    async def test_emit_to_multiple_connections(self):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        active_connections["proj-1"] = [ws1, ws2]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit("discovery", "complete")

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()
