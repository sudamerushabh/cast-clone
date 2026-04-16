"""Tests for WebSocket dead-connection eviction (CHAN-75) and
singleton accessor exception types (CHAN-74)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketDisconnect

from app.orchestrator.progress import (
    WebSocketProgressReporter,
    active_connections,
)


@pytest.fixture(autouse=True)
def _clear_connections():
    active_connections.clear()
    yield
    active_connections.clear()


class TestWebSocketCleanup:
    @pytest.mark.asyncio
    async def test_dead_connection_removed_after_broadcast_failure(self) -> None:
        """A connection that raises WebSocketDisconnect is evicted from the
        active_connections registry after the broadcast loop completes."""
        ws_dead = AsyncMock()
        ws_dead.send_json.side_effect = WebSocketDisconnect(code=1001)
        ws_healthy = AsyncMock()

        active_connections["proj-1"] = [ws_dead, ws_healthy]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit("parsing", "running")

        # Dead connection is gone, healthy remains
        remaining = active_connections.get("proj-1", [])
        assert ws_dead not in remaining
        assert ws_healthy in remaining
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_broadcast_continues_after_dead_connection(self) -> None:
        """A second healthy connection still receives the message when an
        earlier connection in the iteration order is dead."""
        ws_dead = AsyncMock()
        ws_dead.send_json.side_effect = WebSocketDisconnect(code=1006)
        ws_healthy = AsyncMock()

        # dead listed first so we exercise the "continue after failure" path
        active_connections["proj-2"] = [ws_dead, ws_healthy]
        reporter = WebSocketProgressReporter("proj-2")

        await reporter.emit("enrich", "running")

        ws_healthy.send_json.assert_awaited_once()
        event = ws_healthy.send_json.call_args[0][0]
        assert event["stage"] == "enrich"
        assert event["status"] == "running"

    @pytest.mark.asyncio
    async def test_all_dead_connections_cleans_up_project_key(self) -> None:
        """When every connection for a project is dead, the project key itself
        is removed from active_connections to prevent memory growth."""
        ws_dead_1 = AsyncMock()
        ws_dead_1.send_json.side_effect = WebSocketDisconnect()
        ws_dead_2 = AsyncMock()
        ws_dead_2.send_json.side_effect = RuntimeError("connection closed")

        active_connections["proj-gone"] = [ws_dead_1, ws_dead_2]
        reporter = WebSocketProgressReporter("proj-gone")

        await reporter.emit("complete", "complete")

        assert "proj-gone" not in active_connections

    @pytest.mark.asyncio
    async def test_runtime_error_treated_as_dead(self) -> None:
        """RuntimeError (e.g. send after close) also triggers eviction."""
        ws_dead = AsyncMock()
        ws_dead.send_json.side_effect = RuntimeError(
            'Cannot call "send" once a close message has been sent.'
        )
        active_connections["proj-3"] = [ws_dead]
        reporter = WebSocketProgressReporter("proj-3")

        await reporter.emit("linker", "running")

        assert "proj-3" not in active_connections


class TestSingletonAccessors:
    """CHAN-74: singleton accessors must raise RuntimeError, not
    AssertionError — asserts are stripped under python -O in production."""

    def test_get_redis_raises_runtimeerror_when_not_initialized(self) -> None:
        import app.services.redis as redis_module

        original = redis_module._redis
        redis_module._redis = None
        try:
            with pytest.raises(RuntimeError, match="Redis not initialized"):
                redis_module.get_redis()
        finally:
            redis_module._redis = original

    def test_get_driver_raises_runtimeerror_when_not_initialized(self) -> None:
        import app.services.neo4j as neo4j_module

        original = neo4j_module._driver
        neo4j_module._driver = None
        try:
            with pytest.raises(RuntimeError, match="Neo4j not initialized"):
                neo4j_module.get_driver()
        finally:
            neo4j_module._driver = original

    def test_get_engine_raises_runtimeerror_when_not_initialized(self) -> None:
        import app.services.postgres as pg_module

        original = pg_module._engine
        pg_module._engine = None
        try:
            with pytest.raises(RuntimeError, match="PostgreSQL not initialized"):
                pg_module.get_engine()
        finally:
            pg_module._engine = original
