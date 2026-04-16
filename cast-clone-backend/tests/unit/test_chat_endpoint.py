# tests/unit/test_chat_endpoint.py
"""Tests for the chat API endpoint.

Tests endpoint routing, auth, and SSE response format.
Uses mocked chat service.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.postgres import get_session


@pytest.mark.asyncio
async def test_chat_endpoint_returns_sse():
    """POST /api/v1/projects/{id}/chat returns text/event-stream."""
    async def mock_stream(*args, **kwargs):
        yield 'event: text\ndata: {"content": "Hello"}\n\n'
        yield 'event: done\ndata: {"input_tokens": 100, "output_tokens": 50}\n\n'

    mock_session = AsyncMock()

    async def override_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_get_session

    @asynccontextmanager
    async def _noop_lock(*_args, **_kwargs):
        yield

    async def _noop_rate_limit(*_args, **_kwargs):
        return None

    try:
        with patch("app.api.chat._resolve_project_context") as mock_resolve, \
             patch("app.api.chat.get_driver", return_value=MagicMock()), \
             patch("app.api.chat.get_redis", return_value=MagicMock()), \
             patch("app.api.chat.check_rate_limit", _noop_rate_limit), \
             patch("app.api.chat.chat_lock", _noop_lock), \
             patch("app.ai.chat.chat_stream", return_value=mock_stream()):
            mock_resolve.return_value = ("test-app", ["Java"], ["Spring"], None)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/projects/proj-123/chat",
                    json={"message": "What is OrderService?"},
                )
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers["content-type"]
    finally:
        app.dependency_overrides.pop(get_session, None)
