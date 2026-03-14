"""Tests for the AI usage stats endpoint.

Tests endpoint routing, admin auth, and response format.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.services.postgres import get_session


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    # execute() returns an object with .one() and .all() methods
    result = MagicMock()
    result.one.return_value = MagicMock(
        total_input=0, total_output=0, total_cost=0
    )
    result.all.return_value = []
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.fixture
async def client():
    mock_session = _make_mock_session()

    async def override_get_session():
        yield mock_session

    application = create_app()
    application.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    application.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_usage_summary_returns_200(client):
    """GET /api/v1/admin/ai-usage returns usage summary for admins."""
    resp = await client.get("/api/v1/admin/ai-usage")
    # With auth_disabled=True (default), admin access is granted
    assert resp.status_code == 200
    data = resp.json()
    assert "total_input_tokens" in data
    assert "total_output_tokens" in data
    assert "total_estimated_cost_usd" in data
    assert "by_source" in data
    assert "by_project" in data


@pytest.mark.asyncio
async def test_usage_by_project_returns_200(client):
    """GET /api/v1/admin/ai-usage/project/{id} returns project usage."""
    resp = await client.get("/api/v1/admin/ai-usage/project/proj-123")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
