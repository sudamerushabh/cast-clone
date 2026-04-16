# Per-Repository Max-Branch LOC Billing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace cumulative LOC billing (sum of all analysis runs) with per-repository max-branch billing (sum of each repo's highest-LOC branch).

**Architecture:** New `RepositoryLocTracking` model + `loc_tracking.py` service for recalculation. `cumulative_loc()` queries the tracking table instead of summing all analysis runs. Recalculation triggers after scan completion and branch deletion. Frontend adds LOC breakdown table to license page and LOC badge to repo cards.

**Tech Stack:** SQLAlchemy 2.0 async, Alembic, FastAPI, Pydantic v2, Next.js 14 App Router, TypeScript, Tailwind CSS

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `cast-clone-backend/app/services/loc_tracking.py` | `recalculate_repo_loc()` function |
| Create | `cast-clone-backend/migrations/versions/c1_create_repository_loc_tracking.py` | Migration: table + backfill |
| Create | `cast-clone-backend/tests/unit/test_loc_tracking.py` | Unit tests for recalculation logic |
| Modify | `cast-clone-backend/app/models/db.py` | Add `RepositoryLocTracking` model |
| Modify | `cast-clone-backend/app/services/loc_usage.py` | Rewrite `cumulative_loc()` to use tracking table |
| Modify | `cast-clone-backend/app/orchestrator/pipeline.py` | Call `recalculate_repo_loc()` on scan complete |
| Modify | `cast-clone-backend/app/api/repositories.py` | Call recalc on branch delete; add LOC fields to response |
| Modify | `cast-clone-backend/app/schemas/repositories.py` | Add `billable_loc`, `max_loc_branch` to schemas |
| Modify | `cast-clone-backend/app/api/license.py` | Add `loc_breakdown` to status response |
| Modify | `cast-clone-frontend/lib/types.ts` | Add `RepoLocBreakdown`, update response interfaces |
| Modify | `cast-clone-frontend/app/settings/license/page.tsx` | Add LOC breakdown table |
| Modify | `cast-clone-frontend/components/repositories/RepoCard.tsx` | Add LOC badge |

---

## Task 1: Add `RepositoryLocTracking` Model

**Files:**
- Modify: `cast-clone-backend/app/models/db.py` (after `RepositoryGitConfig` class, ~line 314)

- [ ] **Step 1: Add the model**

Add this class after `ProjectGitConfig = RepositoryGitConfig` (line 314) in `cast-clone-backend/app/models/db.py`:

```python
class RepositoryLocTracking(Base):
    """Materialized per-repo LOC billing aggregate.

    One row per repository. Updated after each scan completion or branch
    deletion.  ``billable_loc`` = max(latest completed run LOC) across all
    branches for this repo.
    """

    __tablename__ = "repository_loc_tracking"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    billable_loc: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_loc_project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    max_loc_branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    breakdown: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    last_recalculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    repository: Mapped[Repository] = relationship()
```

- [ ] **Step 2: Verify the model imports are in place**

The file already imports `JSONB`, `text`, `ForeignKey`, `Integer`, `String`, `DateTime`, `func`, `uuid4`, `relationship`, and `Mapped`/`mapped_column` — no new imports needed.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/models/db.py
git commit -m "feat(models): add RepositoryLocTracking model for per-repo LOC billing"
```

---

## Task 2: Create Alembic Migration

**Files:**
- Create: `cast-clone-backend/migrations/versions/c1_create_repository_loc_tracking.py`

- [ ] **Step 1: Write the migration with backfill**

Create `cast-clone-backend/migrations/versions/c1_create_repository_loc_tracking.py`:

```python
"""create repository_loc_tracking table with backfill

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-04-16 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create table
    op.create_table(
        "repository_loc_tracking",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("billable_loc", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "max_loc_project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("max_loc_branch_name", sa.String(255), nullable=True),
        sa.Column(
            "breakdown",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "last_recalculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # 2. Backfill from existing completed analysis runs
    #    For each repo → for each branch (project) → latest completed run's LOC
    #    Then pick the max branch per repo.
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO repository_loc_tracking
            (id, repository_id, billable_loc, max_loc_project_id,
             max_loc_branch_name, breakdown, last_recalculated_at, created_at)
        SELECT
            gen_random_uuid()::text,
            r.id,
            COALESCE(agg.max_loc, 0),
            agg.max_project_id,
            agg.max_branch,
            COALESCE(agg.breakdown, '{}'::jsonb),
            NOW(),
            NOW()
        FROM repositories r
        LEFT JOIN LATERAL (
            SELECT
                max_row.total_loc AS max_loc,
                max_row.project_id AS max_project_id,
                max_row.branch AS max_branch,
                jsonb_object_agg(
                    COALESCE(branch_locs.branch, 'unknown'),
                    branch_locs.loc
                ) AS breakdown
            FROM (
                SELECT DISTINCT ON (p2.id)
                    p2.id AS project_id,
                    p2.branch,
                    ar2.total_loc AS loc
                FROM projects p2
                JOIN analysis_runs ar2 ON ar2.project_id = p2.id
                WHERE p2.repository_id = r.id
                  AND ar2.status = 'completed'
                  AND ar2.total_loc IS NOT NULL
                ORDER BY p2.id, ar2.completed_at DESC
            ) branch_locs
            CROSS JOIN LATERAL (
                SELECT branch_locs.project_id, branch_locs.branch,
                       branch_locs.loc AS total_loc
                FROM (
                    SELECT DISTINCT ON (p3.id)
                        p3.id AS project_id,
                        p3.branch,
                        ar3.total_loc AS loc
                    FROM projects p3
                    JOIN analysis_runs ar3 ON ar3.project_id = p3.id
                    WHERE p3.repository_id = r.id
                      AND ar3.status = 'completed'
                      AND ar3.total_loc IS NOT NULL
                    ORDER BY p3.id, ar3.completed_at DESC
                ) sub
                ORDER BY sub.loc DESC
                LIMIT 1
            ) max_row
            GROUP BY max_row.total_loc, max_row.project_id, max_row.branch
        ) agg ON true
    """))


def downgrade() -> None:
    op.drop_table("repository_loc_tracking")
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend
git add migrations/versions/c1_create_repository_loc_tracking.py
git commit -m "feat(migrations): add repository_loc_tracking table with backfill"
```

---

## Task 3: Create `loc_tracking.py` Service + Tests (TDD)

**Files:**
- Create: `cast-clone-backend/tests/unit/test_loc_tracking.py`
- Create: `cast-clone-backend/app/services/loc_tracking.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_loc_tracking.py`:

```python
"""Tests for per-repo LOC tracking recalculation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AnalysisRun, Project, Repository, RepositoryLocTracking
from app.services.loc_tracking import recalculate_repo_loc


def _id() -> str:
    return str(uuid4())


def _repo(connector_id: str) -> Repository:
    return Repository(
        id=_id(),
        connector_id=connector_id,
        repo_full_name="org/test-repo",
        repo_clone_url="https://github.com/org/test-repo.git",
        clone_status="cloned",
    )


def _project(repo: Repository, branch: str) -> Project:
    return Project(
        id=_id(),
        name=f"{repo.repo_full_name}:{branch}",
        source_path=f"/repos/{repo.id}--branches/{branch}",
        repository_id=repo.id,
        branch=branch,
    )


def _run(project: Project, loc: int, status: str = "completed") -> AnalysisRun:
    return AnalysisRun(
        id=_id(),
        project_id=project.id,
        status=status,
        total_loc=loc,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC) if status == "completed" else None,
    )


@pytest.mark.asyncio
async def test_single_branch_single_run(async_session: AsyncSession) -> None:
    """One branch, one completed run → billable = that run's LOC."""
    repo = _repo("connector-1")
    proj = _project(repo, "main")
    run = _run(proj, 5000)
    async_session.add_all([repo, proj, run])
    await async_session.commit()

    tracking = await recalculate_repo_loc(repo.id, async_session)

    assert tracking.billable_loc == 5000
    assert tracking.max_loc_branch_name == "main"
    assert tracking.max_loc_project_id == proj.id
    assert tracking.breakdown == {"main": 5000}


@pytest.mark.asyncio
async def test_multiple_branches_picks_max(async_session: AsyncSession) -> None:
    """Three branches → billable = max branch LOC."""
    repo = _repo("connector-1")
    p1 = _project(repo, "main")
    p2 = _project(repo, "develop")
    p3 = _project(repo, "feature-x")
    r1 = _run(p1, 1000)
    r2 = _run(p2, 2000)
    r3 = _run(p3, 5000)
    async_session.add_all([repo, p1, p2, p3, r1, r2, r3])
    await async_session.commit()

    tracking = await recalculate_repo_loc(repo.id, async_session)

    assert tracking.billable_loc == 5000
    assert tracking.max_loc_branch_name == "feature-x"
    assert tracking.breakdown == {"main": 1000, "develop": 2000, "feature-x": 5000}


@pytest.mark.asyncio
async def test_latest_run_wins(async_session: AsyncSession) -> None:
    """Multiple runs for same branch → only the latest completed run counts."""
    repo = _repo("connector-1")
    proj = _project(repo, "main")
    old_run = _run(proj, 10000)
    old_run.completed_at = datetime(2026, 1, 1, tzinfo=UTC)
    new_run = _run(proj, 8000)
    new_run.completed_at = datetime(2026, 4, 1, tzinfo=UTC)
    async_session.add_all([repo, proj, old_run, new_run])
    await async_session.commit()

    tracking = await recalculate_repo_loc(repo.id, async_session)

    assert tracking.billable_loc == 8000
    assert tracking.breakdown == {"main": 8000}


@pytest.mark.asyncio
async def test_failed_runs_excluded(async_session: AsyncSession) -> None:
    """Failed runs should not count."""
    repo = _repo("connector-1")
    proj = _project(repo, "main")
    good = _run(proj, 3000, status="completed")
    bad = _run(proj, 99999, status="failed")
    bad.completed_at = datetime(2099, 1, 1, tzinfo=UTC)  # Newer but failed
    async_session.add_all([repo, proj, good, bad])
    await async_session.commit()

    tracking = await recalculate_repo_loc(repo.id, async_session)

    assert tracking.billable_loc == 3000


@pytest.mark.asyncio
async def test_no_completed_runs_zero(async_session: AsyncSession) -> None:
    """Repo with no completed runs → billable = 0."""
    repo = _repo("connector-1")
    proj = _project(repo, "main")
    async_session.add_all([repo, proj])
    await async_session.commit()

    tracking = await recalculate_repo_loc(repo.id, async_session)

    assert tracking.billable_loc == 0
    assert tracking.max_loc_branch_name is None
    assert tracking.breakdown == {}


@pytest.mark.asyncio
async def test_upsert_updates_existing(async_session: AsyncSession) -> None:
    """Calling recalculate twice should update, not duplicate."""
    repo = _repo("connector-1")
    proj = _project(repo, "main")
    run1 = _run(proj, 5000)
    async_session.add_all([repo, proj, run1])
    await async_session.commit()

    await recalculate_repo_loc(repo.id, async_session)

    # Add a new run with more LOC
    run2 = _run(proj, 7000)
    run2.completed_at = datetime(2099, 1, 1, tzinfo=UTC)
    async_session.add(run2)
    await async_session.commit()

    tracking = await recalculate_repo_loc(repo.id, async_session)

    assert tracking.billable_loc == 7000
    # Verify only one tracking row exists
    result = await async_session.execute(
        select(RepositoryLocTracking).where(
            RepositoryLocTracking.repository_id == repo.id
        )
    )
    assert len(result.scalars().all()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_loc_tracking.py -v
```

Expected: FAIL — `ImportError: cannot import name 'recalculate_repo_loc' from 'app.services.loc_tracking'`

- [ ] **Step 3: Implement `loc_tracking.py`**

Create `cast-clone-backend/app/services/loc_tracking.py`:

```python
"""Per-repository LOC tracking — recalculation logic.

Each repository's billable LOC = max(latest completed run LOC) across all
its branches (Projects).  This module provides the recalculation function
called after scan completion and branch deletion.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AnalysisRun, Project, RepositoryLocTracking
from app.services.loc_usage import invalidate_cumulative_loc_cache

logger = structlog.get_logger(__name__)


async def recalculate_repo_loc(
    repository_id: str,
    session: AsyncSession,
) -> RepositoryLocTracking:
    """Recompute billable LOC for a repository from its branches' latest runs.

    Idempotent: upserts the tracking row.  Safe to call concurrently — the
    last writer wins with the same correct result.

    Returns the upserted ``RepositoryLocTracking`` row.
    """
    # 1. For each branch (Project), get the latest completed run's total_loc.
    #    DISTINCT ON (p.id) + ORDER BY completed_at DESC → latest per branch.
    stmt = (
        select(Project.id, Project.branch, AnalysisRun.total_loc)
        .join(AnalysisRun, AnalysisRun.project_id == Project.id)
        .where(
            Project.repository_id == repository_id,
            AnalysisRun.status == "completed",
            AnalysisRun.total_loc.isnot(None),
        )
        .order_by(Project.id, AnalysisRun.completed_at.desc())
        .distinct(Project.id)
    )
    rows = (await session.execute(stmt)).all()

    # 2. Build breakdown and find max.
    breakdown: dict[str, int] = {}
    max_loc = 0
    max_project_id: str | None = None
    max_branch_name: str | None = None

    for project_id, branch, total_loc in rows:
        branch_name = branch or "unknown"
        breakdown[branch_name] = total_loc
        if total_loc > max_loc:
            max_loc = total_loc
            max_project_id = project_id
            max_branch_name = branch_name

    # 3. Upsert tracking row.
    result = await session.execute(
        select(RepositoryLocTracking).where(
            RepositoryLocTracking.repository_id == repository_id
        )
    )
    tracking = result.scalar_one_or_none()

    if tracking is None:
        tracking = RepositoryLocTracking(
            repository_id=repository_id,
            billable_loc=max_loc,
            max_loc_project_id=max_project_id,
            max_loc_branch_name=max_branch_name,
            breakdown=breakdown,
            last_recalculated_at=datetime.now(UTC),
        )
        session.add(tracking)
    else:
        tracking.billable_loc = max_loc
        tracking.max_loc_project_id = max_project_id
        tracking.max_loc_branch_name = max_branch_name
        tracking.breakdown = breakdown
        tracking.last_recalculated_at = datetime.now(UTC)

    await session.flush()

    invalidate_cumulative_loc_cache()
    logger.info(
        "loc_tracking.recalculated",
        repository_id=repository_id,
        billable_loc=max_loc,
        max_branch=max_branch_name,
        branch_count=len(breakdown),
    )
    return tracking
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd cast-clone-backend
uv run pytest tests/unit/test_loc_tracking.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/services/loc_tracking.py tests/unit/test_loc_tracking.py
git commit -m "feat(loc-tracking): add recalculate_repo_loc with TDD tests"
```

---

## Task 4: Rewrite `cumulative_loc()` to Use Tracking Table

**Files:**
- Modify: `cast-clone-backend/app/services/loc_usage.py`

- [ ] **Step 1: Rewrite the query function**

Replace the entire contents of `cast-clone-backend/app/services/loc_usage.py` with:

```python
"""Cumulative LOC usage query with a short in-process cache.

Billable LOC = SUM(repository_loc_tracking.billable_loc)
             + SUM(latest completed run LOC for standalone projects)

A 60-second cache prevents hammering the DB during hot loops (status polling,
dashboard renders); the cache is explicitly invalidated when a tracking row
is recalculated.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AnalysisRun, Project, RepositoryLocTracking
from app.services.postgres import get_background_session

logger = structlog.get_logger(__name__)

_CACHE_TTL_SECONDS = 60.0
_cache_value: int | None = None
_cache_set_at: float = 0.0
_lock = asyncio.Lock()


async def cumulative_loc(session: AsyncSession | None = None) -> int:
    """Return total billable LOC across all repositories + standalone projects.

    Cached for 60 seconds.  Call :func:`invalidate_cumulative_loc_cache` when
    a tracking row is recalculated to force a fresh read.
    """
    global _cache_value, _cache_set_at

    now = time.monotonic()
    if _cache_value is not None and (now - _cache_set_at) < _CACHE_TTL_SECONDS:
        return _cache_value

    async with _lock:
        now = time.monotonic()
        if (
            _cache_value is not None
            and (now - _cache_set_at) < _CACHE_TTL_SECONDS
        ):
            return _cache_value

        async def _query(s: AsyncSession) -> int:
            # Part 1: Sum of per-repo max-branch LOC from tracking table
            repo_result = await s.execute(
                select(
                    func.coalesce(func.sum(RepositoryLocTracking.billable_loc), 0)
                )
            )
            repo_total = int(repo_result.scalar_one())

            # Part 2: Standalone projects (no repository_id) — latest run each
            # Uses a subquery with DISTINCT ON to get latest completed run per project
            standalone_latest = (
                select(
                    AnalysisRun.project_id,
                    AnalysisRun.total_loc,
                )
                .join(Project, Project.id == AnalysisRun.project_id)
                .where(
                    Project.repository_id.is_(None),
                    AnalysisRun.status == "completed",
                    AnalysisRun.total_loc.isnot(None),
                )
                .order_by(AnalysisRun.project_id, AnalysisRun.completed_at.desc())
                .distinct(AnalysisRun.project_id)
                .subquery()
            )
            standalone_result = await s.execute(
                select(func.coalesce(func.sum(standalone_latest.c.total_loc), 0))
            )
            standalone_total = int(standalone_result.scalar_one())

            return repo_total + standalone_total

        if session is not None:
            value = await _query(session)
        else:
            async with get_background_session() as s:
                value = await _query(s)

        _cache_value = value
        _cache_set_at = time.monotonic()
        logger.debug("cumulative_loc.cache_refreshed", total_loc=value)
        return value


def invalidate_cumulative_loc_cache() -> None:
    """Clear the cumulative LOC cache; next call will re-query."""
    global _cache_value, _cache_set_at
    _cache_value = None
    _cache_set_at = 0.0
    logger.debug("cumulative_loc.cache_invalidated")
```

- [ ] **Step 2: Run existing tests to check nothing breaks**

```bash
cd cast-clone-backend
uv run pytest tests/ -v -k "loc" --no-header
```

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/services/loc_usage.py
git commit -m "feat(loc-usage): rewrite cumulative_loc to use tracking table + standalone fallback"
```

---

## Task 5: Wire Recalculation into Pipeline Completion

**Files:**
- Modify: `cast-clone-backend/app/orchestrator/pipeline.py` (~line 384-398)

- [ ] **Step 1: Add recalculation after pipeline completes**

In `cast-clone-backend/app/orchestrator/pipeline.py`, find the "Pipeline complete" block (line 384-398). Replace the `invalidate_cumulative_loc_cache()` call with `recalculate_repo_loc()`.

Change the import at the top of the file (line 22):

```python
# BEFORE:
from app.services.loc_usage import invalidate_cumulative_loc_cache

# AFTER:
from app.services.loc_usage import invalidate_cumulative_loc_cache
```

Then in the pipeline complete block (~line 384-398), change:

```python
        # BEFORE (line 388):
        invalidate_cumulative_loc_cache()

        # AFTER:
        # Recalculate per-repo LOC tracking (also invalidates cumulative cache)
        if project.repository_id:
            from app.services.loc_tracking import recalculate_repo_loc
            await recalculate_repo_loc(project.repository_id, session)
        else:
            invalidate_cumulative_loc_cache()
```

- [ ] **Step 2: Run pipeline-related tests**

```bash
cd cast-clone-backend
uv run pytest tests/ -v -k "pipeline" --no-header
```

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/orchestrator/pipeline.py
git commit -m "feat(pipeline): trigger LOC recalculation on scan completion"
```

---

## Task 6: Wire Recalculation into Branch Deletion

**Files:**
- Modify: `cast-clone-backend/app/api/repositories.py` (~line 420-482)

- [ ] **Step 1: Add recalc call after branch project deletion**

In `cast-clone-backend/app/api/repositories.py`, in the `delete_branch_project` function, add a recalculation call after the DB commit (after line 463: `await session.commit()`):

```python
    # Delete DB record (cascades to analysis_runs)
    await session.delete(project)
    await session.commit()

    # Recalculate repo LOC tracking after branch removal
    from app.services.loc_tracking import recalculate_repo_loc
    await recalculate_repo_loc(repo_id, session)
```

- [ ] **Step 2: Also add recalc after full repository deletion**

In the `delete_repository` function (~line 267-291), after `await session.commit()` (line 284), add cache invalidation since the CASCADE delete removes the tracking row:

```python
    await session.delete(repo)
    await session.commit()

    # CASCADE deleted the tracking row; invalidate cache so cumulative_loc()
    # picks up the removal.
    from app.services.loc_usage import invalidate_cumulative_loc_cache
    invalidate_cumulative_loc_cache()
```

Note: `invalidate_cumulative_loc_cache` is not currently imported in this file. Add it via the lazy import shown above, or add to top-level imports — lazy import is fine here since delete is infrequent.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/api/repositories.py
git commit -m "feat(api): recalculate LOC tracking on branch/repo deletion"
```

---

## Task 7: Add LOC Fields to Repository API Responses

**Files:**
- Modify: `cast-clone-backend/app/schemas/repositories.py`
- Modify: `cast-clone-backend/app/api/repositories.py`

- [ ] **Step 1: Add fields to Pydantic schemas**

In `cast-clone-backend/app/schemas/repositories.py`, add two fields to `RepositoryResponse` (after line 46):

```python
class RepositoryResponse(BaseModel):
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
    billable_loc: int | None = None
    max_loc_branch: str | None = None
```

- [ ] **Step 2: Populate LOC fields in `_repo_to_response`**

In `cast-clone-backend/app/api/repositories.py`, modify `_repo_to_response` (line 48-87) to accept an optional tracking parameter and pass the LOC fields:

```python
def _repo_to_response(
    repo: Repository,
    tracking: RepositoryLocTracking | None = None,
) -> RepositoryResponse:
    projects = []
    for p in repo.projects:
        last_analyzed_at = None
        node_count = None
        edge_count = None
        if hasattr(p, 'analysis_runs') and p.analysis_runs:
            completed = [r for r in p.analysis_runs if r.status == "completed"]
            if completed:
                latest = max(completed, key=lambda r: r.completed_at or r.started_at)
                last_analyzed_at = (latest.completed_at or latest.started_at).isoformat() if (latest.completed_at or latest.started_at) else None
                if latest.snapshot:
                    node_count = latest.snapshot.get("node_count")
                    edge_count = latest.snapshot.get("edge_count")
        projects.append(
            ProjectBranchResponse(
                id=p.id,
                branch=p.branch,
                status=p.status,
                last_analyzed_at=last_analyzed_at,
                node_count=node_count,
                edge_count=edge_count,
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
        billable_loc=tracking.billable_loc if tracking else None,
        max_loc_branch=tracking.max_loc_branch_name if tracking else None,
    )
```

- [ ] **Step 3: Load tracking rows in list/get endpoints**

In `list_repositories` (~line 230-244), after loading repos, bulk-load tracking rows:

```python
@router.get("", response_model=RepositoryListResponse)
async def list_repositories(
    session: AsyncSession = Depends(get_session),
) -> RepositoryListResponse:
    """List all onboarded repositories."""
    result = await session.execute(
        select(Repository)
        .options(_REPO_LOAD)
        .order_by(Repository.created_at.desc())
    )
    repos = result.scalars().all()

    # Bulk-load LOC tracking for all repos
    repo_ids = [r.id for r in repos]
    if repo_ids:
        from app.models.db import RepositoryLocTracking
        tracking_result = await session.execute(
            select(RepositoryLocTracking).where(
                RepositoryLocTracking.repository_id.in_(repo_ids)
            )
        )
        tracking_map = {
            t.repository_id: t for t in tracking_result.scalars().all()
        }
    else:
        tracking_map = {}

    return RepositoryListResponse(
        repositories=[
            _repo_to_response(r, tracking_map.get(r.id))
            for r in repos
        ],
        total=len(repos),
    )
```

Do the same for `get_repository` (~line 247-264):

```python
@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> RepositoryResponse:
    """Get a single repository by ID."""
    result = await session.execute(
        select(Repository)
        .options(_REPO_LOAD)
        .where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found",
        )
    from app.models.db import RepositoryLocTracking
    tracking_result = await session.execute(
        select(RepositoryLocTracking).where(
            RepositoryLocTracking.repository_id == repo_id
        )
    )
    tracking = tracking_result.scalar_one_or_none()
    return _repo_to_response(repo, tracking)
```

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend
git add app/schemas/repositories.py app/api/repositories.py
git commit -m "feat(api): add billable_loc and max_loc_branch to repository responses"
```

---

## Task 8: Add LOC Breakdown to License Status API

**Files:**
- Modify: `cast-clone-backend/app/api/license.py`

- [ ] **Step 1: Add response models**

In `cast-clone-backend/app/api/license.py`, after `InstallationIdResponse` (line 60), add:

```python
class RepoLocBreakdown(BaseModel):
    repository_id: str
    repo_full_name: str
    billable_loc: int
    max_branch: str | None
    branches: dict[str, int]


class LicenseStatusResponse(BaseModel):
    state: Literal[
        "UNLICENSED",
        "LICENSED_HEALTHY",
        "LICENSED_WARN",
        "LICENSED_GRACE",
        "LICENSED_BLOCKED",
    ]
    installation_id: str
    license_disabled: bool
    tier: int | str | None = None
    loc_limit: int | None = None
    loc_used: int | None = None
    loc_breakdown: list[RepoLocBreakdown] = Field(default_factory=list)
    customer_name: str | None = None
    customer_email: str | None = None
    customer_organization: str | None = None
    issued_by: str | None = None
    expires_at: int | None = None
    issued_at: int | None = None
    notes: str | None = None
```

Add `Field` to the existing pydantic import at line 18:

```python
from pydantic import BaseModel, Field
```

- [ ] **Step 2: Build breakdown in `_build_status_response`**

In `_build_status_response` (~line 91-126), after computing `loc_used`, query the tracking table:

```python
async def _build_status_response(
    request: Request,
    settings: Settings,
) -> LicenseStatusResponse:
    state: LicenseState = getattr(
        request.app.state, "license_state", LicenseState.UNLICENSED
    )
    info: LicenseInfo | None = getattr(request.app.state, "license_info", None)
    installation_id: str = getattr(request.app.state, "installation_id", "")

    base: dict[str, Any] = {
        "state": state.value,
        "installation_id": installation_id,
        "license_disabled": settings.license_disabled,
    }
    if info is None:
        return LicenseStatusResponse(**base)

    loc_used = await cumulative_loc()

    # Build per-repo LOC breakdown
    from sqlalchemy import select as sa_select
    from app.models.db import Repository, RepositoryLocTracking
    from app.services.postgres import get_background_session

    breakdown_list: list[RepoLocBreakdown] = []
    async with get_background_session() as session:
        result = await session.execute(
            sa_select(RepositoryLocTracking, Repository.repo_full_name)
            .join(Repository, Repository.id == RepositoryLocTracking.repository_id)
            .where(RepositoryLocTracking.billable_loc > 0)
            .order_by(RepositoryLocTracking.billable_loc.desc())
        )
        for tracking, repo_name in result.all():
            breakdown_list.append(
                RepoLocBreakdown(
                    repository_id=tracking.repository_id,
                    repo_full_name=repo_name,
                    billable_loc=tracking.billable_loc,
                    max_branch=tracking.max_loc_branch_name,
                    branches=tracking.breakdown or {},
                )
            )

    return LicenseStatusResponse(
        **base,
        tier=info.license.tier,
        loc_limit=info.license.loc_limit,
        loc_used=loc_used,
        loc_breakdown=breakdown_list,
        customer_name=info.license.customer.name,
        customer_email=info.license.customer.email,
        customer_organization=info.license.customer.organization,
        issued_by=info.license.issued_by,
        expires_at=info.exp,
        issued_at=info.iat,
        notes=info.license.notes or None,
    )
```

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/api/license.py
git commit -m "feat(api): add loc_breakdown to license status response"
```

---

## Task 9: Update Frontend Types

**Files:**
- Modify: `cast-clone-frontend/lib/types.ts`

- [ ] **Step 1: Add `RepoLocBreakdown` interface and update existing types**

In `cast-clone-frontend/lib/types.ts`, in the "License Management" section (~line 771), add the new interface and update `LicenseStatusResponse`:

```typescript
// Add after line 798 (after InstallationIdResponse):
export interface RepoLocBreakdown {
  repository_id: string;
  repo_full_name: string;
  billable_loc: number;
  max_branch: string | null;
  branches: Record<string, number>;
}
```

Update `LicenseStatusResponse` (~line 780) to add `loc_breakdown`:

```typescript
export interface LicenseStatusResponse {
  state: LicenseState;
  installation_id: string;
  license_disabled: boolean;
  tier: number | string | null;
  loc_limit: number | null;
  loc_used: number | null;
  loc_breakdown: RepoLocBreakdown[];
  customer_name: string | null;
  customer_email: string | null;
  customer_organization: string | null;
  issued_by: string | null;
  expires_at: number | null;
  issued_at: number | null;
  notes: string | null;
}
```

Update `RepositoryResponse` (~line 444) to add LOC fields:

```typescript
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
  billable_loc: number | null;
  max_loc_branch: string | null;
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add lib/types.ts
git commit -m "feat(types): add RepoLocBreakdown, update license and repo response types"
```

---

## Task 10: Add LOC Breakdown Table to License Page

**Files:**
- Modify: `cast-clone-frontend/app/settings/license/page.tsx`

- [ ] **Step 1: Add the LocBreakdownTable component**

In `cast-clone-frontend/app/settings/license/page.tsx`, add this component after `LocProgressBar` (after line 122):

```tsx
// ── LOC Breakdown Table ──

function LocBreakdownTable({
  breakdown,
  totalUsed,
}: {
  breakdown: RepoLocBreakdown[];
  totalUsed: number;
}) {
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());

  if (breakdown.length === 0) return null;

  function toggleExpand(repoId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(repoId)) next.delete(repoId);
      else next.add(repoId);
      return next;
    });
  }

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-muted-foreground">
        LOC by Repository
      </h4>
      <div className="rounded-md border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="px-3 py-2 text-left font-medium">Repository</th>
              <th className="px-3 py-2 text-left font-medium">Max Branch</th>
              <th className="px-3 py-2 text-right font-medium">LOC</th>
              <th className="px-3 py-2 text-right font-medium">% of Total</th>
            </tr>
          </thead>
          <tbody>
            {breakdown.map((repo) => {
              const isExpanded = expanded.has(repo.repository_id);
              const pct =
                totalUsed > 0
                  ? ((repo.billable_loc / totalUsed) * 100).toFixed(1)
                  : "0.0";
              const branches = Object.entries(repo.branches).sort(
                ([, a], [, b]) => b - a
              );
              const hasMultipleBranches = branches.length > 1;

              return (
                <React.Fragment key={repo.repository_id}>
                  <tr
                    className={`border-b last:border-0 ${
                      hasMultipleBranches
                        ? "cursor-pointer hover:bg-muted/30"
                        : ""
                    }`}
                    onClick={() =>
                      hasMultipleBranches && toggleExpand(repo.repository_id)
                    }
                  >
                    <td className="px-3 py-2">
                      <span className="flex items-center gap-1">
                        {hasMultipleBranches && (
                          <span className="text-xs text-muted-foreground">
                            {isExpanded ? "▼" : "▶"}
                          </span>
                        )}
                        <span className="font-mono text-xs">
                          {repo.repo_full_name}
                        </span>
                      </span>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {repo.max_branch}
                    </td>
                    <td className="px-3 py-2 text-right font-medium tabular-nums">
                      {formatNumber(repo.billable_loc)}
                    </td>
                    <td className="px-3 py-2 text-right text-muted-foreground tabular-nums">
                      {pct}%
                    </td>
                  </tr>
                  {isExpanded &&
                    branches.map(([branch, loc]) => (
                      <tr
                        key={branch}
                        className="border-b last:border-0 bg-muted/20"
                      >
                        <td className="pl-8 pr-3 py-1.5 text-xs text-muted-foreground">
                          {branch}
                        </td>
                        <td className="px-3 py-1.5" />
                        <td className="px-3 py-1.5 text-right text-xs tabular-nums">
                          {formatNumber(loc)}
                          {branch === repo.max_branch && (
                            <span className="ml-1 text-emerald-600">← max</span>
                          )}
                        </td>
                        <td className="px-3 py-1.5" />
                      </tr>
                    ))}
                </React.Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t bg-muted/50 font-medium">
              <td className="px-3 py-2">Total</td>
              <td className="px-3 py-2" />
              <td className="px-3 py-2 text-right tabular-nums">
                {formatNumber(totalUsed)}
              </td>
              <td className="px-3 py-2" />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add import for the type**

Update the import at line 6:

```typescript
import type { LicenseStatusResponse, LicenseState, RepoLocBreakdown } from "@/lib/types";
```

Also add `React` import — change line 3 from:

```typescript
import { useCallback, useEffect, useRef, useState } from "react";
```

to:

```typescript
import React, { useCallback, useEffect, useRef, useState } from "react";
```

- [ ] **Step 3: Render the table in the page**

In the main `LicenseSettingsPage` component, find the LOC Usage card (~line 383-396). Add the breakdown table inside the same card, after `LocProgressBar`:

```tsx
              {/* LOC Usage */}
              {status.loc_limit != null && status.loc_used != null && (
                <Card>
                  <CardHeader>
                    <CardTitle>Usage</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <LocProgressBar
                      used={status.loc_used}
                      limit={status.loc_limit}
                    />
                    {status.loc_breakdown && status.loc_breakdown.length > 0 && (
                      <LocBreakdownTable
                        breakdown={status.loc_breakdown}
                        totalUsed={status.loc_used}
                      />
                    )}
                  </CardContent>
                </Card>
              )}
```

Note the change: `<CardContent>` now has `className="space-y-4"` and wraps both the progress bar and the breakdown table.

- [ ] **Step 4: Start dev server and verify**

```bash
cd cast-clone-frontend
npm run dev
```

Open `http://localhost:3000/settings/license` and verify:
- Progress bar still shows correctly
- Below it, a "LOC by Repository" table appears with expandable rows
- Clicking a repo with multiple branches expands to show per-branch LOC

- [ ] **Step 5: Commit**

```bash
cd cast-clone-frontend
git add app/settings/license/page.tsx
git commit -m "feat(ui): add LOC breakdown table to license settings page"
```

---

## Task 11: Add LOC Badge to RepoCard

**Files:**
- Modify: `cast-clone-frontend/components/repositories/RepoCard.tsx`

- [ ] **Step 1: Add LOC display to RepoCard**

In `cast-clone-frontend/components/repositories/RepoCard.tsx`, add a LOC line below the branch badges. After the branch badges `div` (line 46-55), before the `clone_error` line:

```tsx
        {/* LOC billing info */}
        {repo.billable_loc != null && repo.billable_loc > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            Billable: {repo.billable_loc.toLocaleString()} LOC
            {repo.max_loc_branch && (
              <span className="ml-1">({repo.max_loc_branch})</span>
            )}
          </p>
        )}
```

- [ ] **Step 2: Start dev server and verify**

```bash
cd cast-clone-frontend
npm run dev
```

Open `http://localhost:3000/repositories` and verify each repo card shows the LOC badge.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add components/repositories/RepoCard.tsx
git commit -m "feat(ui): add billable LOC badge to repository cards"
```

---

## Task 12: Run Migration and End-to-End Verification

**Files:** None (verification only)

- [ ] **Step 1: Run the alembic migration**

```bash
cd cast-clone-backend
uv run alembic upgrade head
```

Expected: Migration creates `repository_loc_tracking` table and backfills from existing data.

- [ ] **Step 2: Run the full test suite**

```bash
cd cast-clone-backend
uv run pytest tests/ -v --no-header
```

Expected: All tests pass, including the new `test_loc_tracking.py` tests.

- [ ] **Step 3: Run linting**

```bash
cd cast-clone-backend
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
```

- [ ] **Step 4: Start backend + frontend and verify E2E**

```bash
# Terminal 1:
cd cast-clone-backend && uv run uvicorn app.main:app --reload

# Terminal 2:
cd cast-clone-frontend && npm run dev
```

Verify:
1. `GET /api/v1/license/status` returns `loc_breakdown` array
2. `GET /api/v1/repositories` returns `billable_loc` and `max_loc_branch` per repo
3. License page shows the breakdown table
4. Repository list shows LOC badges
5. If you have existing data, `loc_used` should be **lower** than before (the new per-repo max model)

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(licensing): per-repo max-branch LOC billing — complete implementation"
```
