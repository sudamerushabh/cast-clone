"""Tests for Git Config CRUD API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.models.db import ProjectGitConfig, User
from app.services.postgres import get_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> ProjectGitConfig:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid4()),
        project_id=str(uuid4()),
        platform="github",
        repo_url="https://github.com/owner/repo",
        api_token_encrypted="encrypted_token",
        webhook_secret="test-secret",
        monitored_branches=["main", "master", "develop"],
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    config = MagicMock(spec=ProjectGitConfig)
    for k, v in defaults.items():
        setattr(config, k, v)
    return config


def _mock_session(config: ProjectGitConfig | None = None):
    session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = config
    session.execute.return_value = scalar_result
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()

    async def fake_refresh(obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = str(uuid4())
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = datetime.now(timezone.utc)
        if not hasattr(obj, "updated_at") or obj.updated_at is None:
            obj.updated_at = datetime.now(timezone.utc)
        if not hasattr(obj, "is_active") or obj.is_active is None:
            obj.is_active = True

    session.refresh = AsyncMock(side_effect=fake_refresh)
    return session


def _setup_app(session, config=None):
    """Create app with dependency overrides for session and settings."""
    app = create_app()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(auth_disabled=True)

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateGitConfig:
    @patch("app.api.git_config.encrypt_token", return_value="encrypted_value")
    def test_create_config_success(self, mock_encrypt):
        """Creating a git config should return 201 with webhook info."""
        project_id = str(uuid4())
        session = _mock_session(None)  # No existing config

        app = _setup_app(session)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            f"/api/v1/projects/{project_id}/git-config",
            json={
                "platform": "github",
                "repo_url": "https://github.com/owner/repo",
                "api_token": "ghp_abc123",
                "monitored_branches": ["main"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "webhook_url" in data
        assert "webhook_secret" in data
        assert data["platform"] == "github"
        mock_encrypt.assert_called_once()

    def test_create_config_invalid_platform_returns_422(self):
        """An invalid platform should return 422."""
        project_id = str(uuid4())
        session = _mock_session(None)

        app = _setup_app(session)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            f"/api/v1/projects/{project_id}/git-config",
            json={
                "platform": "invalid_platform",
                "repo_url": "https://example.com/repo",
                "api_token": "token123",
            },
        )
        assert resp.status_code == 422


class TestGetGitConfig:
    def test_get_config_success(self):
        """Getting an existing config should return 200."""
        config = _make_config()
        project_id = config.project_id
        session = _mock_session(config)

        app = _setup_app(session)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/projects/{project_id}/git-config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == config.id
        assert data["platform"] == "github"
        # Token should NOT appear in response
        assert "api_token" not in data
        assert "api_token_encrypted" not in data

    def test_get_config_not_found(self):
        """Getting a missing config should return 404."""
        project_id = str(uuid4())
        session = _mock_session(None)

        app = _setup_app(session)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/projects/{project_id}/git-config")
        assert resp.status_code == 404


class TestDeleteGitConfig:
    def test_delete_config_success(self):
        """Deleting an existing config should return 204."""
        config = _make_config()
        project_id = config.project_id
        session = _mock_session(config)

        app = _setup_app(session)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete(f"/api/v1/projects/{project_id}/git-config")
        assert resp.status_code == 204
