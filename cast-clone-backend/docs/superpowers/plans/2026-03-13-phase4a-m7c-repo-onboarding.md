# Phase 4A M7c: Repo Onboarding — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable users to clone remote repositories from connected Git providers, create per-branch projects, run analysis, and track evolution via snapshot comparisons — completing the full "open CodeLens → add connector → pick repo → select branches → analyze" journey.

**Architecture:** New `Repository` SQLAlchemy model links a remote repo (via connector) to a local clone. Each analyzed branch becomes a `Project` with `repository_id` + `branch` fields. Clone is a full `git clone` to `/data/repos/{repo_id}/`. Analysis per branch uses `git checkout` + existing pipeline. Snapshot JSON on `AnalysisRun` enables evolution tracking without Neo4j historical data. New FastAPI router (`/api/v1/repositories`) with CRUD + clone + sync + evolution endpoints. Frontend: "Add Source" modal, repo cards, clone progress polling, branch selector.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, asyncio subprocess (git clone), pytest + pytest-asyncio, Next.js 16, React 19, TypeScript, Tailwind CSS

**Dependencies:** Phase 4A M7b (Git Connectors — connector model, provider adapters, crypto service)

**Spec Reference:** `cast-clone-backend/docs/12-PHASE-4A-FRONTEND-DESIGN-GITCONNECTOR-REPO-ONBOARDING.MD` — Sections 1.2 (Repository model), 1.2 (Project modifications), 4 (Repo Onboarding), 5 (Evolution Tracking)

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── api/
│   │   ├── __init__.py                        # MODIFY — export repositories_router
│   │   └── repositories.py                    # CREATE — CRUD + clone + sync + evolution endpoints
│   ├── models/
│   │   └── db.py                              # MODIFY — add Repository model, modify Project + AnalysisRun
│   ├── schemas/
│   │   ├── connectors.py                      # (unchanged from M7b)
│   │   └── repositories.py                    # CREATE — Pydantic request/response schemas
│   ├── services/
│   │   └── clone.py                           # CREATE — git clone/checkout/pull service
│   ├── config.py                              # (unchanged — uses repo_storage_path from M7b)
│   └── main.py                                # MODIFY — register repositories_router
└── tests/
    └── unit/
        ├── test_clone_service.py              # CREATE — clone service tests
        └── test_repositories_api.py           # CREATE — API endpoint tests

cast-clone-frontend/
├── lib/
│   ├── types.ts                               # MODIFY — add repository types
│   └── api.ts                                 # MODIFY — add repository API functions
├── components/
│   └── repositories/
│       ├── RepoCard.tsx                        # CREATE — repository card with branch badges
│       ├── AddSourceModal.tsx                  # CREATE — multi-step "Add Source" flow
│       ├── BranchPicker.tsx                    # CREATE — checkbox branch selection
│       └── CloneProgress.tsx                   # CREATE — clone status polling display
└── app/
    └── repositories/
        ├── page.tsx                            # MODIFY — repo list with cards + "Add Source"
        └── [repoId]/
            └── page.tsx                        # MODIFY — repo detail with branches
```

---

## Task 1: Add Repository Model and Modify Project + AnalysisRun

**Files:**
- Modify: `cast-clone-backend/app/models/db.py`

- [ ] **Step 1: Add Repository model**

Add the `Repository` class to `cast-clone-backend/app/models/db.py`, after `GitConnector` and before `Project`. Also add `Boolean` to the sqlalchemy imports.

```python
class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    connector_id: Mapped[str] = mapped_column(
        ForeignKey("git_connectors.id", ondelete="CASCADE"), nullable=False
    )
    repo_full_name: Mapped[str] = mapped_column(
        String(512), nullable=False
    )  # "owner/repo-name"
    repo_clone_url: Mapped[str] = mapped_column(
        String(1024), nullable=False
    )  # HTTPS clone URL (token NOT embedded)
    default_branch: Mapped[str] = mapped_column(
        String(255), nullable=False, default="main"
    )
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(100))
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    local_path: Mapped[str | None] = mapped_column(
        String(1024)
    )  # /data/repos/{repo_id}/ — set after first clone
    clone_status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending | cloning | cloned | clone_failed
    clone_error: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_by: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )  # nullable now, FK to users.id in Phase 4
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    connector: Mapped[GitConnector] = relationship()
    projects: Mapped[list[Project]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
```

- [ ] **Step 2: Add repository_id and branch to Project model**

Add these new fields to the `Project` class (after the `status` field):

```python
    # M7c: link to repository + branch
    repository_id: Mapped[str | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True
    )  # null for local-path projects
    branch: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # "main", "develop", "feature/auth" — null for local-path

    repository: Mapped[Repository | None] = relationship(back_populates="projects")
```

Also add the `neo4j_app_name` property to Project:

```python
    @property
    def neo4j_app_name(self) -> str:
        """The app_name used in Neo4j to namespace this project's graph."""
        if self.repository_id and self.branch:
            return f"{self.repository_id}:{self.branch}"
        return self.id  # legacy local-path projects
```

- [ ] **Step 3: Add snapshot and commit_sha to AnalysisRun model**

Add these fields to the `AnalysisRun` class (after the `report` field):

```python
    # M7c: evolution tracking
    snapshot: Mapped[dict | None] = mapped_column(JSON)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
```

- [ ] **Step 4: Add `Boolean` import**

Ensure `Boolean` is imported from sqlalchemy at the top of `db.py`:

```python
from sqlalchemy import Boolean, JSON, DateTime, ForeignKey, Integer, String, Text, func
```

- [ ] **Step 5: Verify models load**

Run: `cd cast-clone-backend && uv run python -c "from app.models.db import Repository, Project; print(Repository.__tablename__, hasattr(Project, 'repository_id'))"`
Expected: `repositories True`

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend
git add app/models/db.py
git commit -m "feat(onboarding): add Repository model, extend Project + AnalysisRun for branches"
```

---

## Task 2: Create Clone Service

**Files:**
- Create: `cast-clone-backend/app/services/clone.py`
- Create: `cast-clone-backend/tests/unit/test_clone_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_clone_service.py
"""Tests for git clone/checkout/pull service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.clone import build_authenticated_url, strip_token_from_url


class TestUrlHelpers:
    def test_build_authenticated_url_github(self):
        url = build_authenticated_url(
            "https://github.com/owner/repo.git", "ghp_token123"
        )
        assert url == "https://ghp_token123@github.com/owner/repo.git"

    def test_build_authenticated_url_gitlab(self):
        url = build_authenticated_url(
            "https://gitlab.com/owner/repo.git", "glpat-xxx"
        )
        assert url == "https://glpat-xxx@gitlab.com/owner/repo.git"

    def test_strip_token_from_url(self):
        url = strip_token_from_url("https://ghp_token123@github.com/owner/repo.git")
        assert url == "https://github.com/owner/repo.git"

    def test_strip_token_no_token(self):
        url = strip_token_from_url("https://github.com/owner/repo.git")
        assert url == "https://github.com/owner/repo.git"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_clone_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement clone service**

```python
# app/services/clone.py
"""Git clone, checkout, and pull operations."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import structlog

logger = structlog.get_logger()


def build_authenticated_url(clone_url: str, token: str) -> str:
    """Inject token into HTTPS clone URL for git clone auth."""
    parsed = urlparse(clone_url)
    authed = parsed._replace(netloc=f"{token}@{parsed.hostname}" + (f":{parsed.port}" if parsed.port else ""))
    return urlunparse(authed)


def strip_token_from_url(url: str) -> str:
    """Remove embedded token from a git URL."""
    parsed = urlparse(url)
    if "@" in (parsed.netloc or ""):
        # Remove everything before @ in netloc
        host_part = parsed.netloc.split("@", 1)[1]
        cleaned = parsed._replace(netloc=host_part)
        return urlunparse(cleaned)
    return url


async def clone_repo(
    clone_url: str,
    token: str,
    target_dir: str,
    timeout: int = 600,
) -> None:
    """Full clone a repository to target_dir.

    1. git clone with token-authenticated URL
    2. Strip token from remote URL after clone

    Raises RuntimeError on failure.
    """
    auth_url = build_authenticated_url(clone_url, token)
    target = Path(target_dir)
    target.parent.mkdir(parents=True, exist_ok=True)

    await logger.ainfo(
        "Cloning repository",
        target=target_dir,
    )

    proc = await asyncio.create_subprocess_exec(
        "git", "clone", auth_url, str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Clone timed out after {timeout}s")

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown error"
        # Ensure token is not leaked in error messages
        error_msg = error_msg.replace(token, "***")
        raise RuntimeError(f"Clone failed: {error_msg}")

    # Strip token from remote URL
    proc2 = await asyncio.create_subprocess_exec(
        "git", "-C", str(target),
        "remote", "set-url", "origin", clone_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc2.communicate()

    await logger.ainfo("Clone complete", target=target_dir)


async def checkout_branch(repo_path: str, branch: str) -> None:
    """Checkout a branch in an existing clone."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_path, "checkout", branch,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Checkout failed: {stderr.decode().strip()}")


async def pull_latest(repo_path: str) -> None:
    """Pull latest changes for the current branch."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_path, "pull", "--ff-only",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Pull failed: {stderr.decode().strip()}")


async def get_current_commit(repo_path: str) -> str | None:
    """Get the current HEAD commit SHA."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_path, "rev-parse", "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        return stdout.decode().strip()
    return None
```

- [ ] **Step 4: Run tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_clone_service.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/services/clone.py tests/unit/test_clone_service.py
git commit -m "feat(onboarding): add git clone/checkout/pull service"
```

---

## Task 3: Create Repository Pydantic Schemas

**Files:**
- Create: `cast-clone-backend/app/schemas/repositories.py`

- [ ] **Step 1: Create repository schemas**

```python
# app/schemas/repositories.py
"""Pydantic v2 schemas for Repository API endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ── Request schemas ──────────────────────────────────────────


class RepositoryCreate(BaseModel):
    """Request body for creating a repository from a connector."""

    connector_id: str
    repo_full_name: str
    branches: list[str] = Field(min_length=1)  # branches to analyze
    auto_analyze: bool = False


class BranchAddRequest(BaseModel):
    """Request body for adding a branch to analyze."""

    branch: str = Field(min_length=1)
    auto_analyze: bool = False


# ── Response schemas ─────────────────────────────────────────


class ProjectBranchResponse(BaseModel):
    """A project representing one analyzed branch."""

    model_config = {"from_attributes": True}

    id: str
    branch: str | None
    status: str
    last_analyzed_at: datetime | None = None
    node_count: int | None = None
    edge_count: int | None = None


class RepositoryResponse(BaseModel):
    """Response for a single repository."""

    model_config = {"from_attributes": True}

    id: str
    connector_id: str
    repo_full_name: str
    default_branch: str
    description: str | None = None
    language: str | None = None
    is_private: bool = False
    clone_status: str
    clone_error: str | None = None
    local_path: str | None = None
    last_synced_at: datetime | None = None
    created_at: datetime
    projects: list[ProjectBranchResponse] = Field(default_factory=list)


class RepositoryListResponse(BaseModel):
    """Response for listing repositories."""

    repositories: list[RepositoryResponse]
    total: int


class CloneStatusResponse(BaseModel):
    """Response for polling clone progress."""

    clone_status: str
    clone_error: str | None = None


# ── Evolution schemas ────────────────────────────────────────


class SnapshotPoint(BaseModel):
    """A point in the evolution timeline."""

    run_id: str
    analyzed_at: datetime
    commit_sha: str | None = None
    summary: dict = Field(default_factory=dict)


class EvolutionTimelineResponse(BaseModel):
    """Snapshot timeline for a branch of a repository."""

    repo_id: str
    branch: str
    snapshots: list[SnapshotPoint]


class BranchCompareResponse(BaseModel):
    """Side-by-side comparison of two branches."""

    branch_a: str
    branch_b: str
    diff: dict = Field(default_factory=dict)
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend
git add app/schemas/repositories.py
git commit -m "feat(onboarding): add Pydantic schemas for repository API"
```

---

## Task 4: Write Failing Tests for Repository API

**Files:**
- Create: `cast-clone-backend/tests/unit/test_repositories_api.py`

- [ ] **Step 1: Write the test file**

```python
# tests/unit/test_repositories_api.py
"""Tests for Repository API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture(autouse=True)
def mock_dependencies(mock_session):
    with patch(
        "app.api.repositories.get_session",
        return_value=mock_session,
    ):
        yield


class TestCreateRepository:
    def test_create_repository_success(self, client, mock_session):
        mock_connector = MagicMock()
        mock_connector.id = "conn-1"
        mock_connector.provider = "github"
        mock_connector.base_url = "https://github.com"
        mock_connector.encrypted_token = "enc_xxx"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_connector
        mock_session.execute = AsyncMock(return_value=mock_result)

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

        async def fake_refresh(obj):
            obj.id = "repo-123"
            obj.created_at = datetime.now(timezone.utc)
            obj.clone_status = "pending"
            obj.projects = []

        mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        with (
            patch("app.api.repositories.create_provider", return_value=mock_provider),
            patch("app.api.repositories.decrypt_token", return_value="ghp_real"),
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
        mock_repo.created_at = datetime.now(timezone.utc)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_repositories_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.repositories'`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add tests/unit/test_repositories_api.py
git commit -m "test: add failing tests for repository API endpoints"
```

---

## Task 5: Implement Repository API Router

**Files:**
- Create: `cast-clone-backend/app/api/repositories.py`

- [ ] **Step 1: Write the repository router**

```python
# app/api/repositories.py
"""Repository CRUD + clone + sync + evolution API endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models.db import AnalysisRun, GitConnector, Project, Repository
from app.schemas.repositories import (
    BranchAddRequest,
    BranchCompareResponse,
    CloneStatusResponse,
    EvolutionTimelineResponse,
    ProjectBranchResponse,
    RepositoryCreate,
    RepositoryListResponse,
    RepositoryResponse,
    SnapshotPoint,
)
from app.services.clone import clone_repo, get_current_commit, pull_latest
from app.services.crypto import decrypt_token
from app.services.git_providers import create_provider
from app.services.postgres import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/repositories", tags=["repositories"])


def _get_settings() -> Settings:
    return Settings()


def _repo_to_response(repo: Repository) -> RepositoryResponse:
    """Convert a Repository ORM object to a response schema."""
    projects = []
    for p in (repo.projects or []):
        # Find latest analysis run for this project
        last_run = None
        if hasattr(p, "analysis_runs") and p.analysis_runs:
            completed = [r for r in p.analysis_runs if r.status == "completed"]
            if completed:
                last_run = max(completed, key=lambda r: r.completed_at or datetime.min)

        projects.append(
            ProjectBranchResponse(
                id=p.id,
                branch=p.branch,
                status=p.status,
                last_analyzed_at=last_run.completed_at if last_run else None,
                node_count=last_run.node_count if last_run else None,
                edge_count=last_run.edge_count if last_run else None,
            )
        )

    return RepositoryResponse(
        id=repo.id,
        connector_id=repo.connector_id,
        repo_full_name=repo.repo_full_name,
        default_branch=repo.default_branch,
        description=repo.description,
        language=repo.language,
        is_private=repo.is_private,
        clone_status=repo.clone_status,
        clone_error=repo.clone_error,
        local_path=repo.local_path,
        last_synced_at=repo.last_synced_at,
        created_at=repo.created_at,
        projects=projects,
    )


# ── Background task: clone ───────────────────────────────────


async def _background_clone(repo_id: str, clone_url: str, token: str) -> None:
    """Background task to clone a repository."""
    settings = _get_settings()
    target_dir = f"{settings.repo_storage_path}/{repo_id}"

    # We need a fresh session for the background task
    from app.services.postgres import _session_factory

    assert _session_factory is not None
    async with _session_factory() as session:
        result = await session.execute(
            select(Repository).where(Repository.id == repo_id)
        )
        repo = result.scalar_one_or_none()
        if not repo:
            return

        repo.clone_status = "cloning"
        repo.clone_error = None
        await session.commit()

        try:
            await clone_repo(
                clone_url, token, target_dir, timeout=settings.git_clone_timeout
            )
            repo.clone_status = "cloned"
            repo.local_path = target_dir
            repo.last_synced_at = datetime.now(timezone.utc)
        except Exception as exc:
            await logger.aerror("Clone failed", repo_id=repo_id, error=str(exc))
            repo.clone_status = "clone_failed"
            repo.clone_error = str(exc)

        await session.commit()


# ── CRUD ─────────────────────────────────────────────────────


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_repository(
    body: RepositoryCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> RepositoryResponse:
    """Create a repository from a connector + repo name. Starts clone in background."""
    # Verify connector exists
    result = await session.execute(
        select(GitConnector).where(GitConnector.id == body.connector_id)
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    # Fetch repo info from provider
    settings = _get_settings()
    token = decrypt_token(connector.encrypted_token, settings.secret_key)
    provider = create_provider(connector.provider, connector.base_url, token)

    try:
        repo_info = await provider.get_repo(body.repo_full_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch repo info: {exc}",
        ) from exc

    # Create repository
    repo = Repository(
        connector_id=connector.id,
        repo_full_name=repo_info.full_name,
        repo_clone_url=repo_info.clone_url,
        default_branch=repo_info.default_branch,
        description=repo_info.description,
        language=repo_info.language,
        is_private=repo_info.is_private,
        clone_status="pending",
    )
    session.add(repo)
    await session.flush()  # Get repo.id

    # Create a Project for each requested branch
    for branch in body.branches:
        project = Project(
            name=f"{repo_info.full_name}:{branch}",
            source_path="",  # Will be set after clone
            status="created",
            repository_id=repo.id,
            branch=branch,
        )
        session.add(project)

    await session.commit()
    await session.refresh(repo, attribute_names=["projects"])

    # Start clone in background
    background_tasks.add_task(
        _background_clone, repo.id, repo_info.clone_url, token
    )

    return _repo_to_response(repo)


@router.get("", response_model=RepositoryListResponse)
async def list_repositories(
    session: AsyncSession = Depends(get_session),
) -> RepositoryListResponse:
    """List all repositories."""
    result = await session.execute(
        select(Repository)
        .options(selectinload(Repository.projects))
        .order_by(Repository.created_at.desc())
    )
    repos = result.scalars().all()
    return RepositoryListResponse(
        repositories=[_repo_to_response(r) for r in repos],
        total=len(repos),
    )


@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> RepositoryResponse:
    """Get a single repository with its branch projects."""
    result = await session.execute(
        select(Repository)
        .options(selectinload(Repository.projects))
        .where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return _repo_to_response(repo)


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a repository and all its branch projects."""
    result = await session.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    await session.delete(repo)
    await session.commit()


# ── Clone status ─────────────────────────────────────────────


@router.get("/{repo_id}/clone-status", response_model=CloneStatusResponse)
async def get_clone_status(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> CloneStatusResponse:
    """Poll clone progress."""
    result = await session.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return CloneStatusResponse(
        clone_status=repo.clone_status,
        clone_error=repo.clone_error,
    )


# ── Sync ─────────────────────────────────────────────────────


@router.post("/{repo_id}/sync", response_model=CloneStatusResponse)
async def sync_repository(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> CloneStatusResponse:
    """Git pull latest for a cloned repository."""
    result = await session.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if repo.clone_status != "cloned" or not repo.local_path:
        raise HTTPException(
            status_code=400, detail="Repository not yet cloned"
        )

    try:
        await pull_latest(repo.local_path)
        repo.last_synced_at = datetime.now(timezone.utc)
        await session.commit()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {exc}",
        ) from exc

    return CloneStatusResponse(
        clone_status=repo.clone_status,
        clone_error=repo.clone_error,
    )


# ── Branch management ────────────────────────────────────────


@router.post(
    "/{repo_id}/branches",
    response_model=ProjectBranchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_branch(
    repo_id: str,
    body: BranchAddRequest,
    session: AsyncSession = Depends(get_session),
) -> ProjectBranchResponse:
    """Add a new branch to analyze."""
    result = await session.execute(
        select(Repository)
        .options(selectinload(Repository.projects))
        .where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Check if branch already exists as a project
    for p in repo.projects:
        if p.branch == body.branch:
            raise HTTPException(
                status_code=409,
                detail=f"Branch '{body.branch}' already exists as a project",
            )

    project = Project(
        name=f"{repo.repo_full_name}:{body.branch}",
        source_path=repo.local_path or "",
        status="created",
        repository_id=repo.id,
        branch=body.branch,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    return ProjectBranchResponse(
        id=project.id,
        branch=project.branch,
        status=project.status,
    )


@router.get("/{repo_id}/projects", response_model=list[ProjectBranchResponse])
async def list_branch_projects(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[ProjectBranchResponse]:
    """List projects (one per branch) for a repository."""
    result = await session.execute(
        select(Project).where(Project.repository_id == repo_id)
    )
    projects = result.scalars().all()
    return [
        ProjectBranchResponse(
            id=p.id,
            branch=p.branch,
            status=p.status,
        )
        for p in projects
    ]


# ── Evolution ────────────────────────────────────────────────


@router.get("/{repo_id}/evolution", response_model=EvolutionTimelineResponse)
async def get_evolution_timeline(
    repo_id: str,
    branch: str = Query("main"),
    session: AsyncSession = Depends(get_session),
) -> EvolutionTimelineResponse:
    """Get snapshot timeline for evolution tracking."""
    # Find the project for this branch
    result = await session.execute(
        select(Project).where(
            Project.repository_id == repo_id,
            Project.branch == branch,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"No project found for branch '{branch}'",
        )

    # Get completed analysis runs with snapshots
    result = await session.execute(
        select(AnalysisRun)
        .where(
            AnalysisRun.project_id == project.id,
            AnalysisRun.status == "completed",
            AnalysisRun.snapshot.isnot(None),
        )
        .order_by(AnalysisRun.completed_at.asc())
    )
    runs = result.scalars().all()

    snapshots = [
        SnapshotPoint(
            run_id=r.id,
            analyzed_at=r.completed_at or r.started_at,
            commit_sha=r.commit_sha,
            summary=r.snapshot.get("summary", {}) if r.snapshot else {},
        )
        for r in runs
    ]

    return EvolutionTimelineResponse(
        repo_id=repo_id,
        branch=branch,
        snapshots=snapshots,
    )


@router.get("/{repo_id}/compare", response_model=BranchCompareResponse)
async def compare_branches(
    repo_id: str,
    branch_a: str = Query(...),
    branch_b: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> BranchCompareResponse:
    """Compare latest snapshots of two branches."""
    # Get latest snapshot for each branch
    async def _get_latest_snapshot(branch: str) -> dict | None:
        result = await session.execute(
            select(Project).where(
                Project.repository_id == repo_id,
                Project.branch == branch,
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            return None

        result = await session.execute(
            select(AnalysisRun)
            .where(
                AnalysisRun.project_id == project.id,
                AnalysisRun.status == "completed",
                AnalysisRun.snapshot.isnot(None),
            )
            .order_by(AnalysisRun.completed_at.desc())
            .limit(1)
        )
        run = result.scalar_one_or_none()
        return run.snapshot if run else None

    snap_a = await _get_latest_snapshot(branch_a)
    snap_b = await _get_latest_snapshot(branch_b)

    # Compute diff
    diff: dict = {}
    if snap_a and snap_b:
        sum_a = snap_a.get("summary", {})
        sum_b = snap_b.get("summary", {})
        for key in set(sum_a.keys()) | set(sum_b.keys()):
            val_a = sum_a.get(key, 0)
            val_b = sum_b.get(key, 0)
            if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                diff[key] = {"branch_a": val_a, "branch_b": val_b, "delta": val_b - val_a}

    return BranchCompareResponse(
        branch_a=branch_a,
        branch_b=branch_b,
        diff=diff,
    )
```

- [ ] **Step 2: Run tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_repositories_api.py -v`
Expected: FAIL — router not registered

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/api/repositories.py
git commit -m "feat(onboarding): implement repository CRUD + clone + evolution API"
```

---

## Task 6: Register Repository Router

**Files:**
- Modify: `cast-clone-backend/app/api/__init__.py`
- Modify: `cast-clone-backend/app/main.py`

- [ ] **Step 1: Export from api/__init__.py**

Add to `app/api/__init__.py`:

```python
from app.api.repositories import router as repositories_router
```

And add `"repositories_router"` to the `__all__` list.

- [ ] **Step 2: Register in main.py**

Add to `app/main.py` imports:

```python
from app.api import repositories_router
```

Add in the router registration section:

```python
application.include_router(repositories_router)
```

- [ ] **Step 3: Run tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_repositories_api.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend
git add app/api/__init__.py app/main.py
git commit -m "feat(onboarding): register repositories router in FastAPI app"
```

---

## Task 7: Add Frontend Repository Types and API Functions

**Files:**
- Modify: `cast-clone-frontend/lib/types.ts`
- Modify: `cast-clone-frontend/lib/api.ts`

- [ ] **Step 1: Add repository types to types.ts**

Add to the end of `cast-clone-frontend/lib/types.ts`:

```typescript
// ─── Phase 4A: Repository types ─────────────────────────────────────────────

export type CloneStatus = "pending" | "cloning" | "cloned" | "clone_failed";

export interface ProjectBranchResponse {
  id: string;
  branch: string | null;
  status: ProjectStatus;
  last_analyzed_at: string | null;
  node_count: number | null;
  edge_count: number | null;
}

export interface RepositoryResponse {
  id: string;
  connector_id: string;
  repo_full_name: string;
  default_branch: string;
  description: string | null;
  language: string | null;
  is_private: boolean;
  clone_status: CloneStatus;
  clone_error: string | null;
  local_path: string | null;
  last_synced_at: string | null;
  created_at: string;
  projects: ProjectBranchResponse[];
}

export interface RepositoryListResponse {
  repositories: RepositoryResponse[];
  total: number;
}

export interface CreateRepositoryRequest {
  connector_id: string;
  repo_full_name: string;
  branches: string[];
  auto_analyze: boolean;
}

export interface CloneStatusResponse {
  clone_status: CloneStatus;
  clone_error: string | null;
}

export interface SnapshotPoint {
  run_id: string;
  analyzed_at: string;
  commit_sha: string | null;
  summary: Record<string, number>;
}

export interface EvolutionTimelineResponse {
  repo_id: string;
  branch: string;
  snapshots: SnapshotPoint[];
}
```

- [ ] **Step 2: Add repository API functions to api.ts**

Add to the end of `cast-clone-frontend/lib/api.ts` (merge imports into existing import block):

```typescript
// ─── Repository endpoints (Phase 4A) ────────────────────────────────────────

export async function createRepository(
  data: CreateRepositoryRequest,
): Promise<RepositoryResponse> {
  return apiFetch<RepositoryResponse>("/api/v1/repositories", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function listRepositories(): Promise<RepositoryListResponse> {
  return apiFetch<RepositoryListResponse>("/api/v1/repositories");
}

export async function getRepository(id: string): Promise<RepositoryResponse> {
  return apiFetch<RepositoryResponse>(`/api/v1/repositories/${id}`);
}

export async function deleteRepository(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/repositories/${id}`, {
    method: "DELETE",
  });
}

export async function getCloneStatus(
  repoId: string,
): Promise<CloneStatusResponse> {
  return apiFetch<CloneStatusResponse>(
    `/api/v1/repositories/${repoId}/clone-status`,
  );
}

export async function syncRepository(
  repoId: string,
): Promise<CloneStatusResponse> {
  return apiFetch<CloneStatusResponse>(
    `/api/v1/repositories/${repoId}/sync`,
    { method: "POST" },
  );
}

export async function getEvolutionTimeline(
  repoId: string,
  branch: string,
): Promise<EvolutionTimelineResponse> {
  return apiFetch<EvolutionTimelineResponse>(
    `/api/v1/repositories/${repoId}/evolution?branch=${encodeURIComponent(branch)}`,
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
cd cast-clone-frontend
git add lib/types.ts lib/api.ts
git commit -m "feat(onboarding): add frontend repository types and API client functions"
```

---

## Task 8: Create RepoCard Component

**Files:**
- Create: `cast-clone-frontend/components/repositories/RepoCard.tsx`

- [ ] **Step 1: Create RepoCard.tsx**

```tsx
// cast-clone-frontend/components/repositories/RepoCard.tsx
"use client";

import * as React from "react";
import Link from "next/link";
import { GitBranch, Loader2, Lock, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { RepositoryResponse } from "@/lib/types";

interface RepoCardProps {
  repo: RepositoryResponse;
  onDelete: (id: string) => void;
}

const cloneStatusConfig: Record<string, { label: string; color: string }> = {
  pending: { label: "Pending", color: "bg-yellow-500/10 text-yellow-700 dark:text-yellow-400" },
  cloning: { label: "Cloning...", color: "bg-blue-500/10 text-blue-700 dark:text-blue-400" },
  cloned: { label: "Ready", color: "bg-green-500/10 text-green-700 dark:text-green-400" },
  clone_failed: { label: "Failed", color: "bg-red-500/10 text-red-700 dark:text-red-400" },
};

export function RepoCard({ repo, onDelete }: RepoCardProps) {
  const statusInfo = cloneStatusConfig[repo.clone_status] ?? cloneStatusConfig.pending;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base font-medium">
          <Link
            href={`/repositories/${repo.id}`}
            className="hover:underline"
          >
            {repo.repo_full_name}
          </Link>
        </CardTitle>
        <div className="flex items-center gap-1.5">
          {repo.is_private && <Lock className="size-3.5 text-muted-foreground" />}
          <Badge variant="outline" className={statusInfo.color}>
            {repo.clone_status === "cloning" && (
              <Loader2 className="mr-1 size-3 animate-spin" />
            )}
            {statusInfo.label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {repo.description && (
          <p className="mb-2 line-clamp-2 text-sm text-muted-foreground">
            {repo.description}
          </p>
        )}

        <div className="flex flex-wrap gap-1.5">
          {repo.language && (
            <Badge variant="secondary" className="text-xs">
              {repo.language}
            </Badge>
          )}
          {repo.projects.map((p) => (
            <Link
              key={p.id}
              href={`/repositories/${repo.id}/${encodeURIComponent(p.branch ?? "main")}`}
            >
              <Badge variant="outline" className="text-xs hover:bg-accent">
                <GitBranch className="mr-0.5 size-3" />
                {p.branch ?? "main"}
              </Badge>
            </Link>
          ))}
        </div>

        {repo.clone_error && (
          <p className="mt-2 text-xs text-destructive">{repo.clone_error}</p>
        )}

        <div className="mt-3 flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive"
            onClick={() => onDelete(repo.id)}
          >
            <Trash2 className="mr-1 size-3.5" />
            Delete
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add components/repositories/RepoCard.tsx
git commit -m "feat(onboarding): add RepoCard component with branch badges"
```

---

## Task 9: Create AddSourceModal and BranchPicker Components

**Files:**
- Create: `cast-clone-frontend/components/repositories/AddSourceModal.tsx`
- Create: `cast-clone-frontend/components/repositories/BranchPicker.tsx`
- Create: `cast-clone-frontend/components/repositories/CloneProgress.tsx`

- [ ] **Step 1: Create BranchPicker.tsx**

```tsx
// cast-clone-frontend/components/repositories/BranchPicker.tsx
"use client";

import * as React from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

interface BranchPickerProps {
  branches: string[];
  defaultBranch: string;
  selected: string[];
  onChange: (selected: string[]) => void;
}

export function BranchPicker({
  branches,
  defaultBranch,
  selected,
  onChange,
}: BranchPickerProps) {
  function toggle(branch: string) {
    if (selected.includes(branch)) {
      onChange(selected.filter((b) => b !== branch));
    } else {
      onChange([...selected, branch]);
    }
  }

  return (
    <div className="space-y-2">
      {branches.map((branch) => (
        <div key={branch} className="flex items-center gap-2">
          <Checkbox
            id={`branch-${branch}`}
            checked={selected.includes(branch)}
            onCheckedChange={() => toggle(branch)}
          />
          <Label htmlFor={`branch-${branch}`} className="text-sm">
            {branch}
            {branch === defaultBranch && (
              <span className="ml-1.5 text-xs text-muted-foreground">
                (default)
              </span>
            )}
          </Label>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create CloneProgress.tsx**

```tsx
// cast-clone-frontend/components/repositories/CloneProgress.tsx
"use client";

import * as React from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { getCloneStatus } from "@/lib/api";
import type { CloneStatus } from "@/lib/types";

interface CloneProgressProps {
  repoId: string;
  onComplete: () => void;
}

export function CloneProgress({ repoId, onComplete }: CloneProgressProps) {
  const [status, setStatus] = React.useState<CloneStatus>("pending");
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (status === "cloned" || status === "clone_failed") return;

    const interval = setInterval(async () => {
      try {
        const data = await getCloneStatus(repoId);
        setStatus(data.clone_status);
        setError(data.clone_error);
        if (data.clone_status === "cloned" || data.clone_status === "clone_failed") {
          clearInterval(interval);
          if (data.clone_status === "cloned") {
            onComplete();
          }
        }
      } catch {
        // Ignore polling errors
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [repoId, status, onComplete]);

  return (
    <div className="flex items-center gap-3 rounded-lg border p-4">
      {status === "pending" || status === "cloning" ? (
        <>
          <Loader2 className="size-5 animate-spin text-primary" />
          <div>
            <p className="text-sm font-medium">
              {status === "pending" ? "Preparing clone..." : "Cloning repository..."}
            </p>
            <p className="text-xs text-muted-foreground">
              This may take a few minutes for large repositories.
            </p>
          </div>
        </>
      ) : status === "cloned" ? (
        <>
          <CheckCircle2 className="size-5 text-green-600" />
          <p className="text-sm font-medium text-green-700 dark:text-green-400">
            Repository cloned successfully!
          </p>
        </>
      ) : (
        <>
          <XCircle className="size-5 text-red-600" />
          <div>
            <p className="text-sm font-medium text-red-700 dark:text-red-400">
              Clone failed
            </p>
            {error && <p className="text-xs text-muted-foreground">{error}</p>}
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create AddSourceModal.tsx**

```tsx
// cast-clone-frontend/components/repositories/AddSourceModal.tsx
"use client";

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BranchPicker } from "./BranchPicker";
import { CloneProgress } from "./CloneProgress";
import {
  listConnectors,
  listRemoteRepos,
  listRemoteBranches,
  createRepository,
} from "@/lib/api";
import type {
  ConnectorResponse,
  RemoteRepoResponse,
} from "@/lib/types";

interface AddSourceModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

type Step = "connector" | "repo" | "branches" | "progress";

export function AddSourceModal({
  open,
  onClose,
  onCreated,
}: AddSourceModalProps) {
  const [step, setStep] = React.useState<Step>("connector");
  const [connectors, setConnectors] = React.useState<ConnectorResponse[]>([]);
  const [selectedConnector, setSelectedConnector] =
    React.useState<ConnectorResponse | null>(null);
  const [repos, setRepos] = React.useState<RemoteRepoResponse[]>([]);
  const [repoSearch, setRepoSearch] = React.useState("");
  const [selectedRepo, setSelectedRepo] =
    React.useState<RemoteRepoResponse | null>(null);
  const [branches, setBranches] = React.useState<string[]>([]);
  const [defaultBranch, setDefaultBranch] = React.useState("main");
  const [selectedBranches, setSelectedBranches] = React.useState<string[]>([]);
  const [createdRepoId, setCreatedRepoId] = React.useState<string | null>(
    null,
  );
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Load connectors on open
  React.useEffect(() => {
    if (open) {
      setStep("connector");
      setSelectedConnector(null);
      setSelectedRepo(null);
      setError(null);
      listConnectors().then((data) => setConnectors(data.connectors));
    }
  }, [open]);

  async function handleSelectConnector(c: ConnectorResponse) {
    setSelectedConnector(c);
    setStep("repo");
    setLoading(true);
    try {
      const data = await listRemoteRepos(c.id, 1, 30, repoSearch || undefined);
      setRepos(data.repos);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load repos");
    } finally {
      setLoading(false);
    }
  }

  async function handleSearchRepos() {
    if (!selectedConnector) return;
    setLoading(true);
    try {
      const data = await listRemoteRepos(
        selectedConnector.id,
        1,
        30,
        repoSearch || undefined,
      );
      setRepos(data.repos);
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectRepo(repo: RemoteRepoResponse) {
    if (!selectedConnector) return;
    setSelectedRepo(repo);
    setStep("branches");
    setLoading(true);
    try {
      const [owner, name] = repo.full_name.split("/");
      const data = await listRemoteBranches(selectedConnector.id, owner, name);
      setBranches(data.branches);
      setDefaultBranch(data.default_branch);
      setSelectedBranches([data.default_branch]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load branches");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate() {
    if (!selectedConnector || !selectedRepo || selectedBranches.length === 0)
      return;
    setLoading(true);
    setError(null);
    try {
      const result = await createRepository({
        connector_id: selectedConnector.id,
        repo_full_name: selectedRepo.full_name,
        branches: selectedBranches,
        auto_analyze: false,
      });
      setCreatedRepoId(result.id);
      setStep("progress");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create repository");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {step === "connector" && "Select Connector"}
            {step === "repo" && "Choose Repository"}
            {step === "branches" && "Select Branches"}
            {step === "progress" && "Cloning Repository"}
          </DialogTitle>
        </DialogHeader>

        {error && (
          <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Step 1: Connector */}
        {step === "connector" && (
          <div className="space-y-2">
            {connectors.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No connectors found. Add a connector first.
              </p>
            ) : (
              connectors.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => handleSelectConnector(c)}
                  className="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent"
                >
                  <span className="font-medium">{c.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {c.provider}
                  </span>
                </button>
              ))
            )}
          </div>
        )}

        {/* Step 2: Repo */}
        {step === "repo" && (
          <div className="space-y-3">
            <div className="flex gap-2">
              <Input
                placeholder="Search repositories..."
                value={repoSearch}
                onChange={(e) => setRepoSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearchRepos()}
              />
              <Button
                variant="outline"
                onClick={handleSearchRepos}
                disabled={loading}
              >
                Search
              </Button>
            </div>
            <div className="max-h-64 space-y-1 overflow-auto">
              {repos.map((r) => (
                <button
                  key={r.full_name}
                  type="button"
                  onClick={() => handleSelectRepo(r)}
                  className="flex w-full flex-col rounded-lg border p-2 text-left transition-colors hover:bg-accent"
                >
                  <span className="text-sm font-medium">{r.full_name}</span>
                  {r.description && (
                    <span className="line-clamp-1 text-xs text-muted-foreground">
                      {r.description}
                    </span>
                  )}
                </button>
              ))}
            </div>
            <Button variant="outline" onClick={() => setStep("connector")}>
              Back
            </Button>
          </div>
        )}

        {/* Step 3: Branches */}
        {step === "branches" && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Select branches to analyze for{" "}
              <strong>{selectedRepo?.full_name}</strong>:
            </p>
            <BranchPicker
              branches={branches}
              defaultBranch={defaultBranch}
              selected={selectedBranches}
              onChange={setSelectedBranches}
            />
            <div className="flex gap-2">
              <Button
                onClick={handleCreate}
                disabled={loading || selectedBranches.length === 0}
              >
                {loading ? "Creating..." : "Clone & Create"}
              </Button>
              <Button variant="outline" onClick={() => setStep("repo")}>
                Back
              </Button>
            </div>
          </div>
        )}

        {/* Step 4: Progress */}
        {step === "progress" && createdRepoId && (
          <div className="space-y-4">
            <CloneProgress
              repoId={createdRepoId}
              onComplete={() => {
                onCreated();
                onClose();
              }}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Commit**

```bash
cd cast-clone-frontend
git add components/repositories/
git commit -m "feat(onboarding): add AddSourceModal, BranchPicker, CloneProgress components"
```

---

## Task 10: Wire Up Repository Pages

**Files:**
- Modify: `cast-clone-frontend/app/repositories/page.tsx`
- Modify: `cast-clone-frontend/app/repositories/[repoId]/page.tsx`

- [ ] **Step 1: Update repositories list page**

```tsx
// cast-clone-frontend/app/repositories/page.tsx
"use client";

import * as React from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { RepoCard } from "@/components/repositories/RepoCard";
import { AddSourceModal } from "@/components/repositories/AddSourceModal";
import { listRepositories, deleteRepository } from "@/lib/api";
import type { RepositoryResponse } from "@/lib/types";

export default function RepositoriesPage() {
  const [repos, setRepos] = React.useState<RepositoryResponse[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [showAddModal, setShowAddModal] = React.useState(false);

  async function load() {
    try {
      const data = await listRepositories();
      setRepos(data.repositories);
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    load();
  }, []);

  async function handleDelete(id: string) {
    await deleteRepository(id);
    setRepos((prev) => prev.filter((r) => r.id !== id));
  }

  if (loading) {
    return (
      <div className="p-6">
        <p className="text-muted-foreground">Loading repositories...</p>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Repositories</h1>
        <Button onClick={() => setShowAddModal(true)}>
          <Plus className="mr-1.5 size-4" />
          Add Source
        </Button>
      </div>

      {repos.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="text-muted-foreground">
            No repositories yet. Connect a Git provider and add your first
            repository.
          </p>
          <Button className="mt-4" onClick={() => setShowAddModal(true)}>
            <Plus className="mr-1.5 size-4" />
            Add Your First Repository
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {repos.map((r) => (
            <RepoCard key={r.id} repo={r} onDelete={handleDelete} />
          ))}
        </div>
      )}

      <AddSourceModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onCreated={load}
      />
    </div>
  );
}
```

- [ ] **Step 2: Update repo detail page**

```tsx
// cast-clone-frontend/app/repositories/[repoId]/page.tsx
"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { GitBranch, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getRepository, syncRepository } from "@/lib/api";
import type { RepositoryResponse } from "@/lib/types";

export default function RepoDetailPage() {
  const params = useParams();
  const repoId = params.repoId as string;
  const [repo, setRepo] = React.useState<RepositoryResponse | null>(null);
  const [syncing, setSyncing] = React.useState(false);

  React.useEffect(() => {
    getRepository(repoId).then(setRepo);
  }, [repoId]);

  async function handleSync() {
    setSyncing(true);
    try {
      await syncRepository(repoId);
      const updated = await getRepository(repoId);
      setRepo(updated);
    } finally {
      setSyncing(false);
    }
  }

  if (!repo) {
    return (
      <div className="p-6">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{repo.repo_full_name}</h1>
          {repo.description && (
            <p className="mt-1 text-muted-foreground">{repo.description}</p>
          )}
        </div>
        <Button
          variant="outline"
          onClick={handleSync}
          disabled={syncing || repo.clone_status !== "cloned"}
        >
          <RefreshCw
            className={`mr-1.5 size-4 ${syncing ? "animate-spin" : ""}`}
          />
          {syncing ? "Syncing..." : "Sync"}
        </Button>
      </div>

      <h2 className="mb-3 text-lg font-semibold">Branches</h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {repo.projects.map((p) => (
          <Card key={p.id}>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <GitBranch className="size-4" />
                <Link
                  href={`/repositories/${repoId}/${encodeURIComponent(p.branch ?? "main")}`}
                  className="hover:underline"
                >
                  {p.branch ?? "main"}
                </Link>
                <Badge
                  variant="outline"
                  className={
                    p.status === "analyzed"
                      ? "bg-green-500/10 text-green-700"
                      : ""
                  }
                >
                  {p.status}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex gap-4 text-sm text-muted-foreground">
                {p.node_count != null && <span>{p.node_count} nodes</span>}
                {p.edge_count != null && <span>{p.edge_count} edges</span>}
                {p.last_analyzed_at && (
                  <span>
                    Analyzed{" "}
                    {new Date(p.last_analyzed_at).toLocaleDateString()}
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
cd cast-clone-frontend
git add app/repositories/
git commit -m "feat(onboarding): wire up repository list and detail pages"
```

---

## Task 11: Run Full Test Suite + Lint

- [ ] **Step 1: Run backend unit tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run backend lint**

Run: `cd cast-clone-backend && uv run ruff check app/api/repositories.py app/schemas/repositories.py app/services/clone.py`
Expected: No errors

- [ ] **Step 3: Run frontend typecheck**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 4: Run frontend lint**

Run: `cd cast-clone-frontend && npm run lint`
Expected: No errors

- [ ] **Step 5: Fix any issues and commit**

```bash
cd cast-clone-backend && git add -A && git commit -m "fix: address lint issues from Phase 4A M7c"
cd ../cast-clone-frontend && git add -A && git commit -m "fix: address lint issues from Phase 4A M7c frontend"
```

---

## Verification Checklist

After all tasks are complete, confirm:

- [ ] `app/models/db.py` contains `Repository` model with clone_status, local_path fields
- [ ] `Project` model has `repository_id`, `branch`, and `neo4j_app_name` property
- [ ] `AnalysisRun` model has `snapshot` (JSON) and `commit_sha` fields
- [ ] `app/services/clone.py` exists with `clone_repo()`, `checkout_branch()`, `pull_latest()`
- [ ] `app/schemas/repositories.py` exists with 8 schemas including evolution types
- [ ] `app/api/repositories.py` exists with 10 endpoints (CRUD + clone + sync + branches + evolution)
- [ ] Repository router registered in `main.py`
- [ ] Frontend `lib/types.ts` has repository + evolution types
- [ ] Frontend `lib/api.ts` has 7 repository API functions
- [ ] `/repositories` page shows repo cards with "Add Source" button
- [ ] "Add Source" modal walks through connector → repo → branches → clone progress
- [ ] `/repositories/[repoId]` page shows branch list with status
- [ ] All backend tests pass
- [ ] All frontend typechecks pass
