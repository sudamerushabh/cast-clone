# PR Branch Auto-Analysis Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a PR webhook arrives, automatically create projects for both source and target branches, clone each branch into its own directory, run full code analysis on both, then run the PR impact analysis against the target branch graph.

**Architecture:** Each branch gets its own local git clone (via `git clone --local --branch`) and its own Neo4j graph (keyed by `app_name = {repo_id}:{branch}`). The webhook handler orchestrates: ensure projects exist → ensure branch clones exist → pull latest → analyze both branches → run PR diff-based impact analysis. The existing `run_analysis_pipeline()` is reused for full code analysis; a new `ensure_branch_ready()` service function handles the clone/pull/analyze coordination.

**Tech Stack:** Python 3.12, FastAPI BackgroundTasks, SQLAlchemy 2.0 async, asyncio, Git CLI, Neo4j

---

## File Structure

| File | Responsibility |
|------|---------------|
| **Create:** `app/services/branch_manager.py` | Core orchestration: ensure branch project exists, ensure branch clone dir, pull, trigger analysis, wait for completion |
| **Modify:** `app/services/clone.py` | Add `clone_branch_local()` — creates a local clone for a specific branch from the main repo clone |
| **Modify:** `app/api/webhooks.py` | Rewrite `_run_analysis_background()` to use BranchManager before running PR analysis |
| **Modify:** `app/orchestrator/pipeline.py` | Minor: add a callable variant that works with branch-specific source paths (currently uses `checkout_branch` on shared dir — needs to work with isolated dirs) |
| **Modify:** `app/models/db.py` | Add `commit_sha` field to `Project` model to track last-analyzed commit |
| **Test:** `tests/unit/test_branch_manager.py` | Unit tests for branch manager logic |
| **Test:** `tests/unit/test_clone_branch.py` | Unit tests for local clone function |
| **Modify:** `tests/unit/test_webhooks_api.py` | Update webhook tests for new flow |

## Key Design Decisions

1. **Local clone per branch**: `git clone --local --branch X /path/to/main-clone /path/to/branch-dir` — uses hardlinks to git objects, minimal disk overhead, fully isolated.
2. **Branch directory layout**: `/home/ubuntu/repos/{repo_id}/` (main clone) and `/home/ubuntu/repos/{repo_id}--branches/{branch_name_sanitized}/` for branch clones.
3. **Skip re-analysis if same commit**: Compare `git rev-parse HEAD` of the branch dir against `Project.commit_sha`. If same, skip analysis.
4. **Sequential analysis**: Analyze target branch first (so PR impact analysis has the graph ready), then source branch. Both must complete before PR analysis starts.
5. **Reuse existing pipeline**: `run_analysis_pipeline(project_id)` already handles everything — we just need the project to have the correct `source_path` pointing to its branch clone dir.

---

## Chunk 1: Branch Clone Infrastructure

### Task 1: Add `clone_branch_local()` to clone service

**Files:**
- Modify: `app/services/clone.py`
- Test: `tests/unit/test_clone_branch.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_clone_branch.py
"""Tests for local branch clone operations."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

from app.services.clone import clone_branch_local, get_branch_clone_path, sanitize_branch_name


class TestSanitizeBranchName:
    def test_simple_branch(self):
        assert sanitize_branch_name("main") == "main"

    def test_slash_branch(self):
        assert sanitize_branch_name("feature/payment") == "feature--payment"

    def test_multiple_slashes(self):
        assert sanitize_branch_name("fix/api/auth") == "fix--api--auth"

    def test_special_chars(self):
        assert sanitize_branch_name("release@1.0") == "release-1.0"


class TestGetBranchClonePath:
    def test_returns_branch_dir(self):
        result = get_branch_clone_path("/repos/abc-123", "feature/payment")
        assert result == "/repos/abc-123--branches/feature--payment"

    def test_main_branch(self):
        result = get_branch_clone_path("/repos/abc-123", "main")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_clone_branch.py -v`
Expected: FAIL — `clone_branch_local`, `get_branch_clone_path`, `sanitize_branch_name` not defined

- [ ] **Step 3: Implement the functions**

Add to `app/services/clone.py`:

```python
import re

def sanitize_branch_name(branch: str) -> str:
    """Sanitize a branch name for use as a directory name."""
    # Replace slashes with double-dash, strip unsafe chars
    sanitized = branch.replace("/", "--")
    sanitized = re.sub(r"[^a-zA-Z0-9._\-]", "-", sanitized)
    return sanitized


def get_branch_clone_path(repo_local_path: str, branch: str) -> str:
    """Get the path where a branch clone should live.

    Layout: /repos/{repo_id}--branches/{sanitized_branch}/
    """
    base = repo_local_path.rstrip("/")
    return f"{base}--branches/{sanitize_branch_name(branch)}"


async def clone_branch_local(
    source_repo_path: str, branch: str, target_dir: str, timeout: int = 300
) -> None:
    """Create a local clone of a specific branch from an existing repo clone.

    Uses `git clone --local --branch <branch>` which hardlinks git objects
    for minimal disk usage.

    Skips if target_dir already exists and contains a .git directory.
    """
    target = Path(target_dir)
    if target.exists() and (target / ".git").exists():
        logger.info("branch_clone_exists", target=target_dir, branch=branch)
        return

    target.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--local", "--branch", branch,
        source_repo_path, str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"Branch clone timed out after {timeout}s")

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown error"
        raise RuntimeError(f"Clone failed: {error_msg}")

    logger.info("branch_clone_created", target=target_dir, branch=branch)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_clone_branch.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/clone.py tests/unit/test_clone_branch.py
git commit -m "feat: add local branch clone infrastructure"
```

---

### Task 2: Add `commit_sha` to Project model

**Files:**
- Modify: `app/models/db.py`

- [ ] **Step 1: Add the field**

Add to the `Project` class in `app/models/db.py`, after the `branch` field:

```python
    last_analyzed_commit: Mapped[str | None] = mapped_column(String(40), nullable=True)
```

This tracks the commit SHA that was last analyzed for this project, so we can skip re-analysis if the branch hasn't moved.

- [ ] **Step 2: Recreate the projects table** (no data loss — table has data but column is nullable)

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend
PGPASSWORD=codelens psql -h localhost -p 15432 -U codelens -d codelens \
  -c "ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_analyzed_commit VARCHAR(40);"
```

- [ ] **Step 3: Verify**

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend
uv run python -c "from app.models.db import Project; print('last_analyzed_commit' in {c.name for c in Project.__table__.columns})"
```
Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add app/models/db.py
git commit -m "feat: add last_analyzed_commit to Project model"
```

---

## Chunk 2: Branch Manager Service

### Task 3: Create `BranchManager` service

**Files:**
- Create: `app/services/branch_manager.py`
- Test: `tests/unit/test_branch_manager.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_branch_manager.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_branch_manager.py -v`
Expected: FAIL — `app.services.branch_manager` not found

- [ ] **Step 3: Implement BranchManager**

```python
# app/services/branch_manager.py
"""Branch project management — ensures branch projects exist and are ready for analysis."""
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Project, Repository
from app.services.clone import (
    clone_branch_local,
    get_branch_clone_path,
    get_current_commit,
    pull_latest,
)

logger = structlog.get_logger(__name__)


class BranchManager:
    """Ensures branch projects exist with their own clone directories."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_branch_project(
        self, repo: Repository, branch: str
    ) -> Project:
        """Ensure a Project record and clone directory exist for a branch.

        If the project already exists, pulls latest code.
        If it doesn't exist, creates the project and clones the branch.

        Returns the Project record.
        """
        # Check for existing project
        result = await self._session.execute(
            select(Project).where(
                Project.repository_id == repo.id,
                Project.branch == branch,
            )
        )
        project = result.scalar_one_or_none()

        branch_dir = get_branch_clone_path(repo.local_path, branch)

        if project is not None:
            # Project exists — pull latest
            try:
                await pull_latest(branch_dir)
                logger.info("branch_pulled", branch=branch, path=branch_dir)
            except Exception as exc:
                logger.warning(
                    "branch_pull_failed", branch=branch, error=str(exc)
                )
            return project

        # Create new project + clone
        await clone_branch_local(repo.local_path, branch, branch_dir)

        project = Project(
            name=f"{repo.repo_full_name}:{branch}",
            source_path=branch_dir,
            status="created",
            repository_id=repo.id,
            branch=branch,
        )
        self._session.add(project)
        await self._session.flush()
        await self._session.refresh(project)

        logger.info(
            "branch_project_created",
            project_id=project.id,
            branch=branch,
            path=branch_dir,
        )
        return project

    async def needs_analysis(self, project: Project) -> bool:
        """Check if a project needs (re-)analysis.

        Returns True if:
        - Never analyzed (status != "analyzed")
        - Branch has new commits since last analysis
        """
        if project.status != "analyzed" or project.last_analyzed_commit is None:
            return True

        current_commit = await get_current_commit(project.source_path)
        if current_commit != project.last_analyzed_commit:
            return True

        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_branch_manager.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/branch_manager.py tests/unit/test_branch_manager.py
git commit -m "feat: add BranchManager service for auto-creating branch projects"
```

---

## Chunk 3: Webhook Handler Rewrite

### Task 4: Update webhook to use BranchManager and run full analysis before PR analysis

**Files:**
- Modify: `app/api/webhooks.py`
- Modify: `tests/unit/test_webhooks_api.py`

- [ ] **Step 1: Rewrite `_run_analysis_background()` in `app/api/webhooks.py`**

Replace the existing `_run_analysis_background` function with the new flow:

```python
async def _run_analysis_background(
    pr_analysis_id: str,
    repo_id: str,
    api_token_encrypted: str,
    platform: str,
    secret_key: str,
) -> None:
    """Background task wrapper for PR analysis.

    Flow:
    1. Load repo and PR record
    2. Ensure projects exist for both source and target branches
    3. Pull latest code for both branches
    4. Run full code analysis on both branches (if needed)
    5. Run PR-specific impact analysis against target branch graph
    """
    from app.orchestrator.pipeline import run_analysis_pipeline
    from app.pr_analysis.analyzer import run_pr_analysis
    from app.services.branch_manager import BranchManager
    from app.services.clone import get_current_commit
    from app.services.postgres import get_background_session

    async with get_background_session() as session:
        # Load PR record
        result = await session.execute(
            select(PrAnalysis).where(PrAnalysis.id == pr_analysis_id)
        )
        pr_record = result.scalar_one_or_none()
        if not pr_record:
            logger.error("pr_analysis_not_found", id=pr_analysis_id)
            return

        # Load repository
        repo_result = await session.execute(
            select(Repository).where(Repository.id == repo_id)
        )
        repo = repo_result.scalar_one_or_none()
        if not repo or not repo.local_path:
            logger.error("repository_not_found_or_not_cloned", id=repo_id)
            pr_record.status = "failed"
            await session.commit()
            return

        # Fetch latest refs in the main clone
        try:
            from app.services.clone import pull_latest as _pull_main
            await _pull_main(repo.local_path)
        except Exception as exc:
            logger.warning("main_repo_pull_failed", error=str(exc))

        mgr = BranchManager(session)

        # Ensure both branch projects exist and are cloned
        target_branch = pr_record.target_branch
        source_branch = pr_record.source_branch

        try:
            target_project = await mgr.ensure_branch_project(repo, target_branch)
            source_project = await mgr.ensure_branch_project(repo, source_branch)
            await session.commit()
        except Exception as exc:
            logger.error("branch_setup_failed", error=str(exc), exc_info=True)
            pr_record.status = "failed"
            await session.commit()
            return

        # Analyze target branch first (PR impact analysis needs this graph)
        if await mgr.needs_analysis(target_project):
            try:
                await run_analysis_pipeline(target_project.id)
                # Update last_analyzed_commit
                commit = await get_current_commit(target_project.source_path)
                if commit:
                    target_project.last_analyzed_commit = commit
                await session.commit()
            except Exception as exc:
                logger.error(
                    "target_branch_analysis_failed",
                    branch=target_branch, error=str(exc), exc_info=True,
                )
                # Continue anyway — PR analysis can still try with existing graph

        # Analyze source branch
        if await mgr.needs_analysis(source_project):
            try:
                await run_analysis_pipeline(source_project.id)
                commit = await get_current_commit(source_project.source_path)
                if commit:
                    source_project.last_analyzed_commit = commit
                await session.commit()
            except Exception as exc:
                logger.warning(
                    "source_branch_analysis_failed",
                    branch=source_branch, error=str(exc), exc_info=True,
                )

        # Now run the PR-specific analysis (diff, impact, drift, AI)
        # Uses target branch graph for impact analysis
        app_name = f"{repo_id}:{target_branch}"

        store = Neo4jGraphStore(get_driver())
        api_token = decrypt_token(api_token_encrypted, secret_key)

        await run_pr_analysis(
            pr_record=pr_record,
            session=session,
            store=store,
            api_token=api_token,
            repo_path=target_project.source_path,
            app_name=app_name,
        )
```

- [ ] **Step 2: Remove the old `checkout_branch` call from `pipeline.py`**

In `app/orchestrator/pipeline.py`, the branch checkout logic (lines 237-252) should now be a no-op because each project's `source_path` already points to the correct branch directory. However, keep it as a safety net — if `source_path` is the main clone dir (legacy projects), checkout still works.

No code change needed here — the existing checkout is safe as-is.

- [ ] **Step 3: Update webhook tests**

Update `tests/unit/test_webhooks_api.py` — the webhook endpoint URL changed from `{project_id}` to `{repo_id}` (already done in previous refactor), but verify tests still pass with the new `_run_analysis_background` signature.

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_webhooks_api.py -v`

- [ ] **Step 4: Run full test suite**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/ -x -q`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add app/api/webhooks.py tests/unit/test_webhooks_api.py
git commit -m "feat: webhook handler auto-creates branch projects and runs full analysis"
```

---

### Task 5: Update reanalyze endpoint to use BranchManager

**Files:**
- Modify: `app/api/pull_requests.py`

- [ ] **Step 1: Update the `reanalyze_pr` endpoint**

The reanalyze endpoint should also ensure branches are up-to-date before re-running analysis. Update the `reanalyze_pr` function to pass the same parameters to `_run_analysis_background`:

No change needed — the existing `reanalyze_pr` already calls `_run_analysis_background` with the same signature. The new logic inside that function handles everything.

- [ ] **Step 2: Run tests**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_pull_requests_api.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit** (if any changes were needed)

---

## Chunk 4: Pipeline Source Path Fix

### Task 6: Ensure existing projects use branch clone dirs

**Files:**
- Modify: `app/api/repositories.py`

- [ ] **Step 1: Update `create_repository` to set per-branch source_path**

Currently `create_repository` sets all projects' `source_path` to the same `target_dir` (the main clone). Update it so each project gets its own branch clone path.

In `app/api/repositories.py`, update the project creation loop (around line 174):

```python
    # Before (all projects share one dir):
    # target_dir = str(Path(settings.repo_storage_path) / repo_id)
    # for branch in body.branches:
    #     project = Project(source_path=target_dir, ...)

    # After (each project gets its own branch dir):
    from app.services.clone import get_branch_clone_path

    base_dir = str(Path(settings.repo_storage_path) / repo_id)
    for branch in body.branches:
        branch_source = get_branch_clone_path(base_dir, branch)
        project = Project(
            name=f"{remote_repo.full_name}:{branch}",
            source_path=branch_source,
            status="created",
            repository_id=repo.id,
            branch=branch,
        )
        session.add(project)
```

- [ ] **Step 2: Update `_background_clone` to also create branch clones**

After the main repo clone succeeds, create local clones for each branch project:

```python
async def _background_clone(
    repo_id: str, clone_url: str, token: str, target_dir: str
) -> None:
    from app.services.postgres import _session_factory
    from app.services.clone import clone_branch_local, get_branch_clone_path
    assert _session_factory is not None

    async with _session_factory() as session:
        result = await session.execute(
            select(Repository)
            .options(selectinload(Repository.projects))
            .where(Repository.id == repo_id)
        )
        repo = result.scalar_one_or_none()
        if repo is None:
            return

        repo.clone_status = "cloning"
        await session.commit()

        try:
            await clone_repo(clone_url, token, target_dir)
            repo.clone_status = "cloned"
            repo.local_path = target_dir
            repo.clone_error = None

            # Create branch clones for each project
            for project in repo.projects:
                if project.branch:
                    branch_dir = get_branch_clone_path(target_dir, project.branch)
                    try:
                        await clone_branch_local(target_dir, project.branch, branch_dir)
                    except Exception as exc:
                        await logger.awarning(
                            "branch_clone_failed",
                            branch=project.branch,
                            error=str(exc),
                        )
        except Exception as exc:
            repo.clone_status = "clone_failed"
            repo.clone_error = str(exc)

        await session.commit()
```

- [ ] **Step 3: Update `add_branch` endpoint to set correct source_path**

In `app/api/repositories.py`, update the `add_branch` endpoint (around line 359):

```python
    from app.services.clone import get_branch_clone_path

    branch_dir = get_branch_clone_path(repo.local_path, body.branch) if repo.local_path else ""
    project = Project(
        name=f"{repo.repo_full_name}:{body.branch}",
        source_path=branch_dir,
        status="created",
        repository_id=repo.id,
        branch=body.branch,
    )
```

- [ ] **Step 4: Run tests**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/ -x -q`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add app/api/repositories.py
git commit -m "feat: per-branch clone directories for repository projects"
```

---

## Chunk 5: Frontend Updates

### Task 7: Update frontend PR detail to show branch info

**Files:**
- Modify: `cast-clone-frontend/app/repositories/[repoId]/page.tsx`

No frontend changes are strictly needed — the branches section already renders `repo.projects`, and new projects created by the webhook will automatically appear when the page refreshes.

- [ ] **Step 1: Verify by loading the repo detail page**

```bash
curl -s http://localhost:3000/repositories/<repo-id> | grep -c "branch"
```

The new branch projects will appear automatically in the branches section with status "created" → "analyzing" → "analyzed".

- [ ] **Step 2: Commit** (no changes expected)

---

## Chunk 6: Full Integration Verification

### Task 8: End-to-end verification

- [ ] **Step 1: Run full test suite**

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/ -q
```
Expected: All tests pass (no regressions)

- [ ] **Step 2: TypeScript check**

```bash
cd /home/ubuntu/cast-clone/cast-clone-frontend && npx tsc --noEmit
```
Expected: Clean compile

- [ ] **Step 3: Verify backend starts**

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend && uv run python -c "from app.main import app; print('OK')"
```

- [ ] **Step 4: Check for stale references**

```bash
# Check for old project_id references in PR/webhook/git-config code
cd /home/ubuntu/cast-clone/cast-clone-backend
grep -rn "project_id" app/api/webhooks.py app/api/git_config.py app/api/pull_requests.py app/services/branch_manager.py
# Should only appear in Project model references, not as URL params or PrAnalysis fields
```

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: PR webhook auto-creates and analyzes both branch projects"
```
