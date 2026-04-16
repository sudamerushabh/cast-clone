"""Tests for user management API endpoints (admin only)."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.main import app
from app.services.postgres import get_session


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
async def client(mock_session):
    async def _override_get_session():
        return mock_session

    def _override_get_settings():
        return Settings(auth_disabled=False, secret_key="test-secret")

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_settings] = _override_get_settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


class TestUserEndpointsExist:
    @pytest.mark.asyncio
    async def test_list_users_requires_auth(self, client):
        resp = await client.get("/api/v1/users")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_user_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/users",
            json={
                "username": "new",
                "email": "new@test.com",
                "password": "password123",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_user_requires_auth(self, client):
        resp = await client.get("/api/v1/users/some-id")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_update_user_requires_auth(self, client):
        resp = await client.put("/api/v1/users/some-id", json={"role": "admin"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_user_requires_auth(self, client):
        resp = await client.delete("/api/v1/users/some-id")
        assert resp.status_code == 401
