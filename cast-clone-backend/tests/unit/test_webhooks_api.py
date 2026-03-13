"""Tests for webhook receiver API endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.db import ProjectGitConfig
from app.pr_analysis.models import GitPlatform, PullRequestEvent
from app.services.postgres import get_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_git_config(**overrides) -> ProjectGitConfig:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid4()),
        project_id=str(uuid4()),
        platform="github",
        repo_url="https://github.com/owner/repo",
        api_token_encrypted="encrypted_token",
        webhook_secret="test-webhook-secret",
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


def _make_pr_event(**overrides) -> PullRequestEvent:
    defaults = dict(
        platform=GitPlatform.github,
        repo_url="https://github.com/owner/repo",
        pr_number=42,
        pr_title="Fix bug in parser",
        pr_description="This fixes the off-by-one error",
        author="octocat",
        source_branch="fix/parser-bug",
        target_branch="main",
        action="opened",
        commit_sha="abc123def456",
        created_at="2026-03-13T10:00:00Z",
        raw_payload={"html_url": "https://github.com/owner/repo/pull/42"},
    )
    defaults.update(overrides)
    return PullRequestEvent(**defaults)


def _mock_session(config: ProjectGitConfig | None = None):
    """Return an async session mock."""
    session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = config
    session.execute.return_value = scalar_result
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def fake_refresh(obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = str(uuid4())

    session.refresh = AsyncMock(side_effect=fake_refresh)
    return session


def _github_signature(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebhookValidGithub:
    @patch("app.api.webhooks.create_platform_client")
    def test_valid_github_webhook_accepted(self, mock_create_client):
        """A valid GitHub PR webhook should return 202 accepted."""
        config = _make_git_config()
        project_id = config.project_id
        session = _mock_session(config)

        mock_client = MagicMock()
        mock_client.verify_webhook_signature.return_value = True
        mock_client.parse_webhook.return_value = _make_pr_event()
        mock_create_client.return_value = mock_client

        app = create_app()

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session

        client = TestClient(app, raise_server_exceptions=False)
        payload = json.dumps({"action": "opened"}).encode()

        resp = client.post(
            f"/api/v1/webhooks/github/{project_id}",
            content=payload,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": "sha256=abc",
                "x-github-event": "pull_request",
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["pr_analysis_id"] is not None


class TestWebhookInvalidSignature:
    @patch("app.api.webhooks.create_platform_client")
    def test_invalid_signature_returns_403(self, mock_create_client):
        """An invalid signature should return 403."""
        config = _make_git_config()
        project_id = config.project_id
        session = _mock_session(config)

        mock_client = MagicMock()
        mock_client.verify_webhook_signature.return_value = False
        mock_create_client.return_value = mock_client

        app = create_app()

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session

        client = TestClient(app, raise_server_exceptions=False)
        payload = json.dumps({"action": "opened"}).encode()

        resp = client.post(
            f"/api/v1/webhooks/github/{project_id}",
            content=payload,
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 403
        assert "signature" in resp.json()["detail"].lower()


class TestWebhookUnknownProject:
    def test_unknown_project_returns_404(self):
        """A webhook for an unknown project should return 404."""
        session = _mock_session(None)

        app = create_app()

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session

        client = TestClient(app, raise_server_exceptions=False)
        payload = json.dumps({"action": "opened"}).encode()

        resp = client.post(
            f"/api/v1/webhooks/github/{uuid4()}",
            content=payload,
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 404


class TestWebhookNonPrEvent:
    @patch("app.api.webhooks.create_platform_client")
    def test_non_pr_event_returns_200_ignored(self, mock_create_client):
        """A non-PR event (e.g. push) should return 200 with status=ignored."""
        config = _make_git_config()
        project_id = config.project_id
        session = _mock_session(config)

        mock_client = MagicMock()
        mock_client.verify_webhook_signature.return_value = True
        mock_client.parse_webhook.return_value = None  # Not a PR event
        mock_create_client.return_value = mock_client

        app = create_app()

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session

        client = TestClient(app, raise_server_exceptions=False)
        payload = json.dumps({"action": "push"}).encode()

        resp = client.post(
            f"/api/v1/webhooks/github/{project_id}",
            content=payload,
            headers={
                "content-type": "application/json",
                "x-github-event": "push",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"
