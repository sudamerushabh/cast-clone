"""Tests for Repository API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.postgres import get_session


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture(autouse=True)
def override_get_session(mock_session):
    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


class TestCreateRepository:
    def test_create_repository_success(self, client, mock_session):
        mock_connector = MagicMock()
        mock_connector.id = "conn-1"
        mock_connector.provider = "github"
        mock_connector.base_url = "https://github.com"
        mock_connector.encrypted_token = "enc_xxx"

        # First execute returns the connector, second returns the re-fetched repo
        mock_repo_obj = MagicMock()
        mock_repo_obj.id = "repo-1"
        mock_repo_obj.connector_id = "conn-1"
        mock_repo_obj.repo_full_name = "owner/repo"
        mock_repo_obj.default_branch = "main"
        mock_repo_obj.description = "Test repo"
        mock_repo_obj.language = "Java"
        mock_repo_obj.is_private = False
        mock_repo_obj.clone_status = "pending"
        mock_repo_obj.clone_error = None
        mock_repo_obj.local_path = None
        mock_repo_obj.last_synced_at = None
        mock_repo_obj.created_at = datetime.now(UTC)
        mock_repo_obj.projects = []

        connector_result = MagicMock()
        connector_result.scalar_one_or_none.return_value = mock_connector

        repo_result = MagicMock()
        repo_result.scalar_one.return_value = mock_repo_obj

        mock_session.execute = AsyncMock(
            side_effect=[connector_result, repo_result]
        )

        mock_provider = AsyncMock()
        mock_provider.get_repo = AsyncMock(
            return_value=MagicMock(
                full_name="owner/repo",
                clone_url="https://github.com/owner/repo.git",
                default_branch="main",
                description="Test repo",
                language="Java",
                is_private=False,
            )
        )

        with (
            patch(
                "app.api.repositories.create_provider",
                return_value=mock_provider,
            ),
            patch(
                "app.api.repositories.decrypt_token", return_value="ghp_real"
            ),
        ):
            resp = client.post(
                "/api/v1/repositories",
                json={
                    "connector_id": "conn-1",
                    "repo_full_name": "owner/repo",
                    "branches": ["main"],
                    "auto_analyze": False,
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["repo_full_name"] == "owner/repo"
        assert data["clone_status"] == "pending"


class TestListRepositories:
    def test_list_repositories(self, client, mock_session):
        mock_repo = MagicMock()
        mock_repo.id = "repo-1"
        mock_repo.connector_id = "conn-1"
        mock_repo.repo_full_name = "owner/repo"
        mock_repo.default_branch = "main"
        mock_repo.description = None
        mock_repo.language = "Java"
        mock_repo.is_private = False
        mock_repo.clone_status = "cloned"
        mock_repo.clone_error = None
        mock_repo.local_path = "/data/repos/repo-1"
        mock_repo.last_synced_at = None
        mock_repo.created_at = datetime.now(UTC)
        mock_repo.projects = []

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_repo]
        mock_session.execute = AsyncMock(return_value=mock_result)

        resp = client.get("/api/v1/repositories")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["repositories"][0]["repo_full_name"] == "owner/repo"


class TestDeleteRepository:
    def test_delete_repository(self, client, mock_session):
        mock_repo = MagicMock()
        mock_repo.id = "repo-1"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        mock_session.execute = AsyncMock(return_value=mock_result)

        resp = client.delete("/api/v1/repositories/repo-1")
        assert resp.status_code == 204

    def test_delete_repository_calls_cleanup(self, client, mock_session):
        mock_repo = MagicMock()
        mock_repo.id = "repo-1"
        mock_repo.local_path = "/data/repos/repo-1"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.api.repositories.cleanup_repo_dirs",
            new_callable=AsyncMock,
        ) as mock_cleanup:
            resp = client.delete("/api/v1/repositories/repo-1")

        assert resp.status_code == 204
        mock_cleanup.assert_awaited_once_with("/data/repos/repo-1")

    def test_delete_repository_cleanup_failure_does_not_fail_request(
        self, client, mock_session
    ):
        mock_repo = MagicMock()
        mock_repo.id = "repo-1"
        mock_repo.local_path = "/data/repos/repo-1"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.api.repositories.cleanup_repo_dirs",
            new_callable=AsyncMock,
            side_effect=OSError("permission denied"),
        ):
            resp = client.delete("/api/v1/repositories/repo-1")

        assert resp.status_code == 204

    def test_delete_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        resp = client.delete("/api/v1/repositories/nonexistent")
        assert resp.status_code == 404


class TestCloneStatus:
    def test_clone_status(self, client, mock_session):
        mock_repo = MagicMock()
        mock_repo.clone_status = "cloning"
        mock_repo.clone_error = None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        mock_session.execute = AsyncMock(return_value=mock_result)

        resp = client.get("/api/v1/repositories/repo-1/clone-status")
        assert resp.status_code == 200
        assert resp.json()["clone_status"] == "cloning"
