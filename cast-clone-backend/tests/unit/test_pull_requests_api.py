"""Tests for PR analysis API endpoints."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_user
from app.config import Settings, get_settings
from app.main import app
from app.models.db import PrAnalysis, User
from app.services.postgres import get_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def admin_user():
    return User(
        id="admin-1",
        username="admin",
        email="admin@test.com",
        password_hash="x",
        role="admin",
        is_active=True,
    )


@pytest.fixture
async def client(mock_session, admin_user):
    async def _override_session():
        return mock_session

    async def _override_user():
        return admin_user

    def _override_settings():
        return Settings(auth_disabled=False, secret_key="test-key")

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_settings] = _override_settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _make_pr_analysis() -> MagicMock:
    pr = MagicMock(spec=PrAnalysis)
    pr.id = "pr-1"
    pr.repository_id = "repo-1"
    pr.platform = "github"
    pr.pr_number = 42
    pr.pr_title = "Fix bug"
    pr.pr_description = "Desc"
    pr.pr_author = "alice"
    pr.source_branch = "fix/bug"
    pr.target_branch = "main"
    pr.commit_sha = "abc123"
    pr.pr_url = "https://github.com/org/repo/pull/42"
    pr.status = "completed"
    pr.risk_level = "Medium"
    pr.changed_node_count = 5
    pr.blast_radius_total = 47
    pr.files_changed = 3
    pr.additions = 20
    pr.deletions = 5
    pr.ai_summary = "This PR modifies..."
    pr.analysis_duration_ms = 5000
    pr.ai_summary_tokens = 500
    pr.impact_summary = {"total_blast_radius": 47}
    pr.drift_report = {"has_drift": False}
    pr.graph_analysis_run_id = None
    pr.created_at = datetime(2026, 3, 13, tzinfo=timezone.utc)
    pr.updated_at = datetime(2026, 3, 13, tzinfo=timezone.utc)
    return pr


class TestListPrAnalyses:
    @pytest.mark.asyncio
    async def test_list_returns_paginated(self, client, mock_session):
        pr = _make_pr_analysis()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [pr]
        mock_count = MagicMock()
        mock_count.scalar.return_value = 1
        mock_session.execute.side_effect = [mock_count, mock_result]

        resp = await client.get("/api/v1/repositories/repo-1/pull-requests")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["pr_number"] == 42

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, client, mock_session):
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.side_effect = [mock_count, mock_result]

        resp = await client.get(
            "/api/v1/repositories/repo-1/pull-requests?status=failed"
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestGetPrAnalysis:
    @pytest.mark.asyncio
    async def test_get_detail(self, client, mock_session):
        pr = _make_pr_analysis()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pr
        mock_session.execute.return_value = mock_result

        resp = await client.get("/api/v1/repositories/repo-1/pull-requests/pr-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "pr-1"
        assert data["ai_summary"] == "This PR modifies..."

    @pytest.mark.asyncio
    async def test_get_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        resp = await client.get(
            "/api/v1/repositories/repo-1/pull-requests/nonexistent"
        )
        assert resp.status_code == 404


class TestGetPrImpact:
    @pytest.mark.asyncio
    async def test_get_impact_detail(self, client, mock_session):
        pr = _make_pr_analysis()
        pr.impact_summary = {
            "total_blast_radius": 47,
            "by_type": {"Function": 30},
            "by_depth": {"1": 10},
            "by_layer": {},
            "changed_nodes": [
                {
                    "fqn": "a.b",
                    "name": "b",
                    "type": "Function",
                    "change_type": "modified",
                }
            ],
            "downstream_count": 30,
            "upstream_count": 17,
            "cross_tech": [],
            "transactions_affected": [],
        }
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pr
        mock_session.execute.return_value = mock_result

        resp = await client.get(
            "/api/v1/repositories/repo-1/pull-requests/pr-1/impact"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_blast_radius"] == 47


class TestGetPrDrift:
    @pytest.mark.asyncio
    async def test_get_drift_report(self, client, mock_session):
        pr = _make_pr_analysis()
        pr.drift_report = {
            "has_drift": False,
            "potential_new_module_deps": [],
            "circular_deps_affected": [],
            "new_files_outside_modules": [],
        }
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pr
        mock_session.execute.return_value = mock_result

        resp = await client.get(
            "/api/v1/repositories/repo-1/pull-requests/pr-1/drift"
        )
        assert resp.status_code == 200
        assert resp.json()["has_drift"] is False


class TestReanalyze:
    @pytest.mark.asyncio
    async def test_reanalyze_queues_task(self, client, mock_session):
        pr = _make_pr_analysis()
        pr.status = "stale"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pr

        # Mock git config lookup
        config = MagicMock()
        config.api_token_encrypted = "encrypted"
        config.platform = "github"
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = config

        mock_session.execute.side_effect = [mock_result, mock_result2]

        with patch("app.api.webhooks._run_analysis_background", new_callable=AsyncMock):
            resp = await client.post(
                "/api/v1/repositories/repo-1/pull-requests/pr-1/reanalyze"
            )
        assert resp.status_code == 202
