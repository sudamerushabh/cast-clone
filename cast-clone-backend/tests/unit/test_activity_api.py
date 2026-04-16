"""Tests for activity feed API endpoints."""

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


class TestActivityEndpointsExist:
    @pytest.mark.asyncio
    async def test_activity_feed_requires_auth(self, client):
        resp = await client.get("/api/v1/activity")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_activity_feed_with_params(self, client):
        resp = await client.get(
            "/api/v1/activity",
            params={"limit": 20, "action": "user.login"},
        )
        assert resp.status_code == 401
