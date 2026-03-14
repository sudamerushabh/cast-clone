"""Tests for the summary REST endpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_get_summary_cached(app_client, mock_session):
    """GET summary returns cached result."""
    with (
        patch("app.api.summaries._resolve_summary_context") as mock_ctx,
        patch("app.api.summaries.get_or_create_summary") as mock_svc,
        patch("app.api.summaries.get_driver") as mock_driver,
        patch("app.api.summaries.Neo4jGraphStore") as mock_store,
        patch("app.api.summaries.AsyncAnthropicBedrock") as mock_bedrock,
    ):
        mock_ctx.return_value = (
            "test-app",
            None,
            AsyncMock(),
        )
        mock_svc.return_value = {
            "fqn": "com.app.OrderService",
            "summary": "OrderService handles orders...",
            "cached": True,
            "model": "model-1",
            "tokens_used": 300,
        }
        resp = await app_client.get(
            "/api/v1/projects/proj-123/summary/com.app.OrderService"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fqn"] == "com.app.OrderService"
        assert data["cached"] is True


@pytest.mark.asyncio
async def test_summary_node_not_found(app_client, mock_session):
    """GET summary returns 404 when node not in graph."""
    with (
        patch("app.api.summaries._resolve_summary_context") as mock_ctx,
        patch("app.api.summaries.get_or_create_summary") as mock_svc,
        patch("app.api.summaries.get_driver") as mock_driver,
        patch("app.api.summaries.Neo4jGraphStore") as mock_store,
        patch("app.api.summaries.AsyncAnthropicBedrock") as mock_bedrock,
    ):
        mock_ctx.return_value = (
            "test-app",
            None,
            AsyncMock(),
        )
        mock_svc.return_value = {
            "fqn": "does.not.exist",
            "error": "Node not found: does.not.exist",
        }
        resp = await app_client.get(
            "/api/v1/projects/proj-123/summary/does.not.exist"
        )
        assert resp.status_code == 404
