"""Tests for saved views API endpoints."""
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.postgres import get_session


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
async def client(mock_session):
    async def _override_get_session():
        return mock_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


class TestSavedViewEndpointsExist:
    @pytest.mark.asyncio
    async def test_save_view_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/projects/proj-1/views",
            json={"name": "test", "state": {}},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_views_requires_auth(self, client):
        resp = await client.get("/api/v1/projects/proj-1/views")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_view_requires_auth(self, client):
        resp = await client.get("/api/v1/views/view-1")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_update_view_requires_auth(self, client):
        resp = await client.put(
            "/api/v1/views/view-1",
            json={"name": "updated"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_view_requires_auth(self, client):
        resp = await client.delete("/api/v1/views/view-1")
        assert resp.status_code == 401
