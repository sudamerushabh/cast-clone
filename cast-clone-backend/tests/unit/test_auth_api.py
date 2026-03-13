"""Tests for auth API endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.db import User
from app.services.auth import hash_password, create_access_token
from app.services.postgres import get_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


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


class TestSetupStatus:
    @pytest.mark.asyncio
    async def test_needs_setup_when_no_users(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_session.execute.return_value = mock_result

        resp = await client.get("/api/v1/auth/setup-status")
        assert resp.status_code == 200
        assert resp.json() == {"needs_setup": True}

    @pytest.mark.asyncio
    async def test_no_setup_needed_when_users_exist(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_session.execute.return_value = mock_result

        resp = await client.get("/api/v1/auth/setup-status")
        assert resp.status_code == 200
        assert resp.json() == {"needs_setup": False}


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_endpoint_exists(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "adminpass123"},
        )
        # Should get 401 (invalid credentials), not 404
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "nonexistent", "password": "wrong"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid username or password"
