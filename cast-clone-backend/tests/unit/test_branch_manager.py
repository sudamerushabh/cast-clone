"""Tests for BranchManager — ensures branch projects exist and are analyzed."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.branch_manager import BranchManager


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _make_repo(**overrides):
    repo = MagicMock()
    repo.id = str(uuid4())
    repo.local_path = "/repos/test-repo"
    repo.clone_status = "cloned"
    repo.repo_full_name = "org/repo"
    repo.repo_clone_url = "https://github.com/org/repo.git"
    for k, v in overrides.items():
        setattr(repo, k, v)
    return repo


def _make_project(**overrides):
    proj = MagicMock()
    proj.id = str(uuid4())
    proj.branch = "main"
    proj.source_path = "/repos/test-repo--branches/main"
    proj.status = "analyzed"
    proj.last_analyzed_commit = "abc123"
    for k, v in overrides.items():
        setattr(proj, k, v)
    return proj


class TestEnsureBranchProject:
    @pytest.mark.asyncio
    @patch("app.services.branch_manager.get_current_commit", return_value="abc123")
    @patch("app.services.branch_manager.clone_branch_local")
    @patch("app.services.branch_manager.pull_latest")
    async def test_creates_project_if_not_exists(
        self, mock_pull, mock_clone, mock_commit, mock_session
    ):
        """Should create a new Project and clone dir when branch has no project."""
        repo = _make_repo()

        # No existing project found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        mgr = BranchManager(mock_session)
        project = await mgr.ensure_branch_project(repo, "feature/xyz")

        # Should have added a new project
        mock_session.add.assert_called_once()
        mock_clone.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.branch_manager.get_current_commit", return_value="abc123")
    @patch("app.services.branch_manager.pull_latest")
    async def test_returns_existing_project(
        self, mock_pull, mock_commit, mock_session
    ):
        """Should return existing project and pull latest if project exists."""
        repo = _make_repo()
        existing = _make_project(branch="main")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result

        mgr = BranchManager(mock_session)
        project = await mgr.ensure_branch_project(repo, "main")

        assert project.id == existing.id
        mock_session.add.assert_not_called()
        mock_pull.assert_called_once()


class TestNeedsAnalysis:
    @pytest.mark.asyncio
    @patch("app.services.branch_manager.get_current_commit", return_value="new-sha")
    async def test_needs_analysis_when_never_analyzed(self, mock_commit):
        """A project that was never analyzed needs analysis."""
        project = _make_project(status="created", last_analyzed_commit=None)
        mgr = BranchManager(AsyncMock())
        assert await mgr.needs_analysis(project) is True

    @pytest.mark.asyncio
    @patch("app.services.branch_manager.get_current_commit", return_value="new-sha")
    async def test_needs_analysis_when_commit_changed(self, mock_commit):
        """A project whose branch has new commits needs re-analysis."""
        project = _make_project(last_analyzed_commit="old-sha")
        mgr = BranchManager(AsyncMock())
        assert await mgr.needs_analysis(project) is True

    @pytest.mark.asyncio
    @patch("app.services.branch_manager.get_current_commit", return_value="abc123")
    async def test_no_analysis_when_same_commit(self, mock_commit):
        """A project at the same commit doesn't need re-analysis."""
        project = _make_project(last_analyzed_commit="abc123")
        mgr = BranchManager(AsyncMock())
        assert await mgr.needs_analysis(project) is False
