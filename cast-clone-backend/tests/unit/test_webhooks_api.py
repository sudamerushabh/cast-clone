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
from app.models.db import RepositoryGitConfig
from app.pr_analysis.models import GitPlatform, PullRequestEvent
from app.services.postgres import get_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_git_config(**overrides) -> RepositoryGitConfig:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid4()),
        repository_id=str(uuid4()),
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
    config = MagicMock(spec=RepositoryGitConfig)
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


def _mock_session(config: RepositoryGitConfig | None = None):
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
        repo_id = config.repository_id
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
            f"/api/v1/webhooks/github/{repo_id}",
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
        repo_id = config.repository_id
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
            f"/api/v1/webhooks/github/{repo_id}",
            content=payload,
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 403
        assert "signature" in resp.json()["detail"].lower()


class TestWebhookUnknownRepo:
    def test_unknown_repo_returns_404(self):
        """A webhook for an unknown repository should return 404."""
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
        repo_id = config.repository_id
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
            f"/api/v1/webhooks/github/{repo_id}",
            content=payload,
            headers={
                "content-type": "application/json",
                "x-github-event": "push",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"


# ---------------------------------------------------------------------------
# _run_analysis_background tests
# ---------------------------------------------------------------------------

from app.api.webhooks import _run_analysis_background


def _make_repo_mock(**overrides):
    defaults = dict(
        id="repo-1",
        local_path="/repos/test",
        repo_full_name="org/repo",
    )
    defaults.update(overrides)
    repo = MagicMock()
    for k, v in defaults.items():
        setattr(repo, k, v)
    return repo


def _make_pr_record_mock(**overrides):
    defaults = dict(
        id="pr-1",
        target_branch="main",
        source_branch="feature/xyz",
        status="pending",
        source_path="/repos/test",
    )
    defaults.update(overrides)
    pr = MagicMock()
    for k, v in defaults.items():
        setattr(pr, k, v)
    return pr


def _make_bg_session(pr_record, repo):
    """Build an async session mock for _run_analysis_background.

    session.execute is called twice: first for PrAnalysis, then for Repository.
    """
    session = AsyncMock()
    session.commit = AsyncMock()

    pr_result = MagicMock()
    pr_result.scalar_one_or_none.return_value = pr_record
    repo_result = MagicMock()
    repo_result.scalar_one_or_none.return_value = repo

    session.execute = AsyncMock(side_effect=[pr_result, repo_result])
    return session


def _bg_session_ctx(session):
    """Return an async-context-manager mock wrapping *session*."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestRunAnalysisBackground:
    """Tests for the _run_analysis_background helper."""

    @pytest.mark.asyncio
    @patch("app.api.webhooks.Neo4jGraphStore")
    @patch("app.api.webhooks.get_driver")
    @patch("app.api.webhooks.decrypt_token", return_value="decrypted-token")
    async def test_background_sets_failed_when_repo_not_cloned(
        self, mock_decrypt, mock_driver, mock_store_cls
    ):
        """If the repo exists but has no local_path, status → failed."""
        pr_record = _make_pr_record_mock()
        repo = _make_repo_mock(local_path=None)  # not cloned
        session = _make_bg_session(pr_record, repo)

        with patch(
            "app.services.postgres.get_background_session",
            return_value=_bg_session_ctx(session),
        ):
            await _run_analysis_background(
                "pr-1", "repo-1", "encrypted", "github", "secret"
            )

        assert pr_record.status == "failed"
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    @patch("app.api.webhooks.Neo4jGraphStore")
    @patch("app.api.webhooks.get_driver")
    @patch("app.api.webhooks.decrypt_token", return_value="decrypted-token")
    async def test_background_sets_failed_when_branch_setup_fails(
        self, mock_decrypt, mock_driver, mock_store_cls
    ):
        """If BranchManager.ensure_branch_project raises, status → failed."""
        pr_record = _make_pr_record_mock()
        repo = _make_repo_mock()
        session = _make_bg_session(pr_record, repo)

        mock_mgr = AsyncMock()
        mock_mgr.ensure_branch_project = AsyncMock(
            side_effect=RuntimeError("clone failed")
        )

        with (
            patch(
                "app.services.postgres.get_background_session",
                return_value=_bg_session_ctx(session),
            ),
            patch(
                "app.services.clone.fetch_all_refs", new_callable=AsyncMock
            ),
            patch(
                "app.services.branch_manager.BranchManager",
                return_value=mock_mgr,
            ),
        ):
            await _run_analysis_background(
                "pr-1", "repo-1", "encrypted", "github", "secret"
            )

        assert pr_record.status == "failed"
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    @patch("app.api.webhooks.Neo4jGraphStore")
    @patch("app.api.webhooks.get_driver")
    @patch("app.api.webhooks.decrypt_token", return_value="decrypted-token")
    async def test_background_runs_full_pipeline(
        self, mock_decrypt, mock_driver, mock_store_cls
    ):
        """Happy path: both branches analysed, then PR analysis runs."""
        pr_record = _make_pr_record_mock()
        repo = _make_repo_mock()
        session = _make_bg_session(pr_record, repo)

        target_project = MagicMock()
        target_project.id = "proj-target"
        target_project.source_path = "/repos/test/branches/main"
        source_project = MagicMock()
        source_project.id = "proj-source"
        source_project.source_path = "/repos/test/branches/feature-xyz"

        mock_mgr = AsyncMock()
        mock_mgr.ensure_branch_project = AsyncMock(
            side_effect=[target_project, source_project]
        )
        mock_mgr.needs_analysis = AsyncMock(return_value=True)

        mock_pipeline = AsyncMock()
        mock_pr_analysis = AsyncMock()
        mock_get_commit = AsyncMock(return_value="abc123")

        with (
            patch(
                "app.services.postgres.get_background_session",
                return_value=_bg_session_ctx(session),
            ),
            patch(
                "app.services.clone.fetch_all_refs", new_callable=AsyncMock
            ),
            patch(
                "app.services.branch_manager.BranchManager",
                return_value=mock_mgr,
            ),
            patch(
                "app.orchestrator.pipeline.run_analysis_pipeline",
                mock_pipeline,
            ),
            patch(
                "app.services.clone.get_current_commit",
                mock_get_commit,
            ),
            patch(
                "app.pr_analysis.analyzer.run_pr_analysis",
                mock_pr_analysis,
            ),
        ):
            await _run_analysis_background(
                "pr-1", "repo-1", "encrypted", "github", "secret"
            )

        # Pipeline called for both branches
        assert mock_pipeline.await_count == 2
        mock_pipeline.assert_any_await("proj-target")
        mock_pipeline.assert_any_await("proj-source")

        # PR analysis called
        mock_pr_analysis.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.api.webhooks.Neo4jGraphStore")
    @patch("app.api.webhooks.get_driver")
    @patch("app.api.webhooks.decrypt_token", return_value="decrypted-token")
    async def test_background_skips_analysis_when_not_needed(
        self, mock_decrypt, mock_driver, mock_store_cls
    ):
        """When needs_analysis is False for both branches, pipeline is NOT called."""
        pr_record = _make_pr_record_mock()
        repo = _make_repo_mock()
        session = _make_bg_session(pr_record, repo)

        target_project = MagicMock()
        target_project.id = "proj-target"
        target_project.source_path = "/repos/test/branches/main"
        source_project = MagicMock()
        source_project.id = "proj-source"
        source_project.source_path = "/repos/test/branches/feature-xyz"

        mock_mgr = AsyncMock()
        mock_mgr.ensure_branch_project = AsyncMock(
            side_effect=[target_project, source_project]
        )
        mock_mgr.needs_analysis = AsyncMock(return_value=False)

        mock_pipeline = AsyncMock()
        mock_pr_analysis = AsyncMock()

        with (
            patch(
                "app.services.postgres.get_background_session",
                return_value=_bg_session_ctx(session),
            ),
            patch(
                "app.services.clone.fetch_all_refs", new_callable=AsyncMock
            ),
            patch(
                "app.services.branch_manager.BranchManager",
                return_value=mock_mgr,
            ),
            patch(
                "app.orchestrator.pipeline.run_analysis_pipeline",
                mock_pipeline,
            ),
            patch(
                "app.services.clone.get_current_commit",
                new_callable=AsyncMock,
            ),
            patch(
                "app.pr_analysis.analyzer.run_pr_analysis",
                mock_pr_analysis,
            ),
        ):
            await _run_analysis_background(
                "pr-1", "repo-1", "encrypted", "github", "secret"
            )

        mock_pipeline.assert_not_awaited()
        mock_pr_analysis.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.api.webhooks.Neo4jGraphStore")
    @patch("app.api.webhooks.get_driver")
    @patch("app.api.webhooks.decrypt_token", return_value="decrypted-token")
    async def test_background_continues_on_target_analysis_failure(
        self, mock_decrypt, mock_driver, mock_store_cls
    ):
        """If target branch analysis fails, PR analysis still runs."""
        pr_record = _make_pr_record_mock()
        repo = _make_repo_mock()
        session = _make_bg_session(pr_record, repo)

        target_project = MagicMock()
        target_project.id = "proj-target"
        target_project.source_path = "/repos/test/branches/main"
        source_project = MagicMock()
        source_project.id = "proj-source"
        source_project.source_path = "/repos/test/branches/feature-xyz"

        mock_mgr = AsyncMock()
        mock_mgr.ensure_branch_project = AsyncMock(
            side_effect=[target_project, source_project]
        )
        mock_mgr.needs_analysis = AsyncMock(return_value=True)

        # Target analysis fails, source succeeds
        mock_pipeline = AsyncMock(
            side_effect=[RuntimeError("target boom"), None]
        )
        mock_pr_analysis = AsyncMock()
        mock_get_commit = AsyncMock(return_value="abc123")

        with (
            patch(
                "app.services.postgres.get_background_session",
                return_value=_bg_session_ctx(session),
            ),
            patch(
                "app.services.clone.fetch_all_refs", new_callable=AsyncMock
            ),
            patch(
                "app.services.branch_manager.BranchManager",
                return_value=mock_mgr,
            ),
            patch(
                "app.orchestrator.pipeline.run_analysis_pipeline",
                mock_pipeline,
            ),
            patch(
                "app.services.clone.get_current_commit",
                mock_get_commit,
            ),
            patch(
                "app.pr_analysis.analyzer.run_pr_analysis",
                mock_pr_analysis,
            ),
        ):
            await _run_analysis_background(
                "pr-1", "repo-1", "encrypted", "github", "secret"
            )

        # Pipeline was called twice (target failed, source succeeded)
        assert mock_pipeline.await_count == 2
        # PR analysis still ran despite target failure
        mock_pr_analysis.assert_awaited_once()
