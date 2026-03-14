"""Tests for API key management endpoints.

Tests create, list, and revoke operations using mocked DB sessions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.services.postgres import get_session


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
async def api_key_client(mock_session):
    """Async test client with mocked DB session and auth disabled."""
    app = create_app()

    async def override_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_api_key(api_key_client, mock_session):
    """POST /api/v1/api-keys creates a key and returns raw key once."""

    async def mock_refresh(obj):
        obj.id = "new-key-id"
        obj.created_at = datetime(2026, 1, 1, tzinfo=UTC)

    mock_session.refresh = mock_refresh

    resp = await api_key_client.post(
        "/api/v1/api-keys",
        json={"name": "My Test Key"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Test Key"
    assert "raw_key" in data
    assert data["raw_key"].startswith("clk_")
    assert "id" in data


@pytest.mark.asyncio
async def test_create_api_key_missing_name(api_key_client):
    """POST /api/v1/api-keys with empty name returns 422."""
    resp = await api_key_client.post(
        "/api/v1/api-keys",
        json={"name": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_api_keys(api_key_client, mock_session):
    """GET /api/v1/api-keys returns keys without raw key."""
    mock_key = MagicMock()
    mock_key.id = "key-1"
    mock_key.name = "Test Key"
    mock_key.is_active = True
    mock_key.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    mock_key.last_used_at = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_key]
    mock_session.execute = AsyncMock(return_value=mock_result)

    resp = await api_key_client.get("/api/v1/api-keys")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "Test Key"
    assert "raw_key" not in data[0]


@pytest.mark.asyncio
async def test_revoke_api_key(api_key_client, mock_session):
    """DELETE /api/v1/api-keys/{id} sets is_active=false."""
    mock_key = MagicMock()
    mock_key.id = "key-1"
    mock_key.is_active = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_key
    mock_session.execute = AsyncMock(return_value=mock_result)

    resp = await api_key_client.delete("/api/v1/api-keys/key-1")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Key revoked"


@pytest.mark.asyncio
async def test_revoke_nonexistent_key(api_key_client, mock_session):
    """DELETE /api/v1/api-keys/{id} with unknown id returns 404."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    resp = await api_key_client.delete("/api/v1/api-keys/nonexistent")
    assert resp.status_code == 404
