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
    """One branch, one completed run -> billable = that run's LOC."""
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
    """Three branches -> billable = max branch LOC."""
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
    """Multiple runs for same branch -> only the latest completed run counts."""
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
    bad.completed_at = datetime(2099, 1, 1, tzinfo=UTC)
    async_session.add_all([repo, proj, good, bad])
    await async_session.commit()

    tracking = await recalculate_repo_loc(repo.id, async_session)

    assert tracking.billable_loc == 3000


@pytest.mark.asyncio
async def test_no_completed_runs_zero(async_session: AsyncSession) -> None:
    """Repo with no completed runs -> billable = 0."""
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

    run2 = _run(proj, 7000)
    run2.completed_at = datetime(2099, 1, 1, tzinfo=UTC)
    async_session.add(run2)
    await async_session.commit()

    tracking = await recalculate_repo_loc(repo.id, async_session)

    assert tracking.billable_loc == 7000
    result = await async_session.execute(
        select(RepositoryLocTracking).where(
            RepositoryLocTracking.repository_id == repo.id
        )
    )
    assert len(result.scalars().all()) == 1
