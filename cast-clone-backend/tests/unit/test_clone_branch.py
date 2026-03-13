"""Tests for local branch clone operations."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

from app.services.clone import (
    clone_branch_local,
    get_branch_clone_path,
    sanitize_branch_name,
    fetch_all_refs,
    cleanup_repo_dirs,
)


class TestSanitizeBranchName:
    def test_simple_branch(self):
        assert sanitize_branch_name("main") == "main"

    def test_slash_branch(self):
        assert sanitize_branch_name("feature/payment") == "feature--payment"

    def test_multiple_slashes(self):
        assert sanitize_branch_name("fix/api/auth") == "fix--api--auth"

    def test_special_chars(self):
        assert sanitize_branch_name("release@1.0") == "release-1.0"

    def test_empty_string(self):
        assert sanitize_branch_name("") == ""

    def test_very_long_name(self):
        result = sanitize_branch_name("a" * 300)
        assert len(result) == 300
        assert result == "a" * 300

    def test_dots_and_underscores_preserved(self):
        assert sanitize_branch_name("release_v1.2.3") == "release_v1.2.3"

    def test_all_special_chars(self):
        assert sanitize_branch_name("@#$%") == "----"

    def test_consecutive_slashes(self):
        assert sanitize_branch_name("a//b") == "a----b"


class TestGetBranchClonePath:
    def test_returns_branch_dir(self):
        result = get_branch_clone_path("/repos/abc-123", "feature/payment")
        assert result == "/repos/abc-123--branches/feature--payment"

    def test_main_branch(self):
        result = get_branch_clone_path("/repos/abc-123", "main")
        assert result == "/repos/abc-123--branches/main"

    def test_trailing_slash(self):
        result = get_branch_clone_path("/repos/abc-123/", "main")
        assert result == "/repos/abc-123--branches/main"


class TestCloneBranchLocal:
    @pytest.mark.asyncio
    @patch("app.services.clone.asyncio.create_subprocess_exec")
    async def test_clone_creates_directory_and_runs_git(self, mock_exec, tmp_path):
        """clone_branch_local should run git clone --local --branch."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        source = str(tmp_path / "source")
        Path(source).mkdir()
        target = str(tmp_path / "target")

        await clone_branch_local(source, "feature/pay", target)

        # Verify git clone was called with correct args
        call_args = mock_exec.call_args[0]
        assert "git" in call_args
        assert "clone" in call_args
        assert "--local" in call_args
        assert "--branch" in call_args
        assert "feature/pay" in call_args

    @pytest.mark.asyncio
    @patch("app.services.clone.asyncio.create_subprocess_exec")
    async def test_clone_skips_if_dir_exists(self, mock_exec, tmp_path):
        """If branch dir already exists, clone_branch_local should skip."""
        target = str(tmp_path / "existing")
        Path(target).mkdir()
        (Path(target) / ".git").mkdir()  # Looks like a git repo

        await clone_branch_local(str(tmp_path / "source"), "main", target)

        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.clone.asyncio.create_subprocess_exec")
    async def test_clone_failure_raises(self, mock_exec):
        """clone_branch_local should raise on git clone failure."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"fatal: branch not found")
        mock_proc.returncode = 128
        mock_exec.return_value = mock_proc

        with pytest.raises(RuntimeError, match="Clone failed"):
            await clone_branch_local("/src", "bad-branch", "/target")

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, tmp_path):
        """A target_dir whose resolved path escapes its parent should raise ValueError."""
        # /some/real/dir/.. resolves to /some/real, but parent is /some/real/dir
        # so resolved does not start with parent.resolve() -> ValueError
        evil_target = str(tmp_path / "subdir" / "..")
        with pytest.raises(ValueError, match="Invalid clone target"):
            await clone_branch_local("/src", "main", evil_target)


class TestFetchAllRefs:
    @pytest.mark.asyncio
    @patch("app.services.clone.asyncio.create_subprocess_exec")
    async def test_fetch_all_runs_git_fetch(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        await fetch_all_refs("/repos/test")

        call_args = mock_exec.call_args[0]
        assert "git" in call_args
        assert "fetch" in call_args
        assert "--all" in call_args

    @pytest.mark.asyncio
    @patch("app.services.clone.asyncio.create_subprocess_exec")
    async def test_fetch_all_failure_raises(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"error: could not fetch")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        with pytest.raises(RuntimeError, match="Fetch failed"):
            await fetch_all_refs("/repos/test")


class TestCleanupRepoDirs:
    @pytest.mark.asyncio
    async def test_cleanup_removes_directories(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "file.txt").write_text("test")
        branches_dir = tmp_path / "repo--branches"
        branches_dir.mkdir()
        (branches_dir / "main").mkdir()

        await cleanup_repo_dirs(str(repo_dir))

        assert not repo_dir.exists()
        assert not branches_dir.exists()

    @pytest.mark.asyncio
    async def test_cleanup_noop_when_none(self):
        await cleanup_repo_dirs(None)  # should not raise

    @pytest.mark.asyncio
    async def test_cleanup_noop_when_dirs_missing(self, tmp_path):
        await cleanup_repo_dirs(str(tmp_path / "nonexistent"))  # should not raise
