"""Tests for Git Connector API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.db import GitConnector
from app.services.git_providers.base import GitUser
from app.services.postgres import get_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_connector(**overrides) -> GitConnector:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid4()),
        name="My GitHub",
        provider="github",
        base_url="https://github.com",
        auth_method="pat",
        encrypted_token="enc_tok",
        status="connected",
        remote_username="octocat",
        created_by=None,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    c = MagicMock(spec=GitConnector)
    for k, v in defaults.items():
        setattr(c, k, v)
    return c


def _mock_session(connectors: list[GitConnector] | None = None):
    """Return an async session mock wired for common queries."""
    session = AsyncMock()

    # For scalar_one_or_none (get by id)
    if connectors:
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = connectors[0]
        session.execute.return_value = scalar_result
    else:
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        session.execute.return_value = scalar_result

    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateConnector:
    @patch("app.api.connectors.create_provider")
    @patch("app.api.connectors.encrypt_token", return_value="encrypted")
    def test_create_connector_success(self, mock_encrypt, mock_create_prov):
        mock_provider = AsyncMock()
        mock_provider.validate = AsyncMock(
            return_value=GitUser(username="octocat", display_name="Octocat")
        )
        mock_create_prov.return_value = mock_provider

        app = create_app()
        session = AsyncMock()

        # Mock execute for any queries during create (there shouldn't be lookups)
        session.commit = AsyncMock()
        session.add = MagicMock()

        # After refresh, the connector object should have the fields set
        async def fake_refresh(obj):
            obj.id = str(uuid4())
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)

        session.refresh = AsyncMock(side_effect=fake_refresh)

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/connectors",
            json={
                "name": "My GitHub",
                "provider": "github",
                "base_url": "https://github.com",
                "token": "ghp_abc123",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My GitHub"
        assert data["provider"] == "github"
        assert data["remote_username"] == "octocat"
        # Token should NOT appear in response
        assert "token" not in data
        assert "encrypted_token" not in data

    @patch("app.api.connectors.create_provider")
    def test_create_connector_invalid_token(self, mock_create_prov):
        mock_provider = AsyncMock()
        mock_provider.validate = AsyncMock(
            side_effect=Exception("401 Unauthorized")
        )
        mock_create_prov.return_value = mock_provider

        app = create_app()

        async def override_session():
            yield AsyncMock()

        app.dependency_overrides[get_session] = override_session
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/connectors",
            json={
                "name": "Bad",
                "provider": "github",
                "base_url": "https://github.com",
                "token": "bad-token",
            },
        )
        assert resp.status_code == 400
        assert "validate" in resp.json()["detail"].lower()


class TestListConnectors:
    def test_list_connectors(self):
        app = create_app()
        c = _make_connector()
        session = AsyncMock()

        # First call: count query; second call: select query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [c]

        session.execute = AsyncMock(
            side_effect=[count_result, select_result]
        )

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/connectors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["connectors"]) == 1


class TestGetConnector:
    def test_get_connector_found(self):
        app = create_app()
        c = _make_connector()
        session = _mock_session([c])

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/api/v1/connectors/{c.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == c.id

    def test_get_connector_not_found(self):
        app = create_app()
        session = _mock_session(None)

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/api/v1/connectors/{uuid4()}")
        assert resp.status_code == 404


class TestDeleteConnector:
    def test_delete_connector(self):
        app = create_app()
        c = _make_connector()
        session = _mock_session([c])

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete(f"/api/v1/connectors/{c.id}")
        assert resp.status_code == 204


class TestTestConnector:
    @patch("app.api.connectors.create_provider")
    @patch("app.api.connectors.decrypt_token", return_value="ghp_abc123")
    def test_test_connector_success(self, mock_decrypt, mock_create_prov):
        mock_provider = AsyncMock()
        mock_provider.validate = AsyncMock(
            return_value=GitUser(username="octocat")
        )
        mock_create_prov.return_value = mock_provider

        app = create_app()
        c = _make_connector()
        session = _mock_session([c])

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(f"/api/v1/connectors/{c.id}/test")
        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"
        assert resp.json()["remote_username"] == "octocat"

    @patch("app.api.connectors.create_provider")
    @patch("app.api.connectors.decrypt_token", return_value="bad")
    def test_test_connector_failure(self, mock_decrypt, mock_create_prov):
        mock_provider = AsyncMock()
        mock_provider.validate = AsyncMock(
            side_effect=Exception("auth failed")
        )
        mock_create_prov.return_value = mock_provider

        app = create_app()
        c = _make_connector()
        session = _mock_session([c])

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(f"/api/v1/connectors/{c.id}/test")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


class TestListRemoteRepos:
    @patch("app.api.connectors.create_provider")
    @patch("app.api.connectors.decrypt_token", return_value="tok")
    def test_list_repos(self, mock_decrypt, mock_create_prov):
        from app.services.git_providers.base import GitRepo

        mock_provider = AsyncMock()
        mock_provider.list_repos = AsyncMock(
            return_value=(
                [
                    GitRepo(
                        full_name="octocat/hello",
                        clone_url="https://github.com/octocat/hello.git",
                        default_branch="main",
                    )
                ],
                False,
            )
        )
        mock_create_prov.return_value = mock_provider

        app = create_app()
        c = _make_connector()
        session = _mock_session([c])

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/api/v1/connectors/{c.id}/repos")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["repos"]) == 1
        assert data["repos"][0]["full_name"] == "octocat/hello"
        assert data["has_more"] is False
