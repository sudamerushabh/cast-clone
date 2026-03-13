# Phase 5a M9 — PR Analysis API Endpoints

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose REST API endpoints for listing, viewing, and re-analyzing PR analyses.

**Architecture:** A single `pull_requests.py` router with 5 endpoints: paginated list (filterable by status/risk/branch), detail view, impact detail, drift report, and re-analyze trigger. All endpoints require JWT auth. Follows the existing CRUD patterns from `connectors.py` and `analysis_views.py`.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2 response models from M1.

**Depends On:** M1 (schemas + models), M3 (webhook creates records), M8 (orchestrator for re-analyze).

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── api/
│   │   ├── __init__.py              # MODIFY — register new router
│   │   └── pull_requests.py         # CREATE
│   └── main.py                      # MODIFY — include new router
└── tests/
    └── unit/
        └── test_pull_requests_api.py # CREATE
```

---

### Task 1: PR Analysis List + Detail Endpoints

**Files:**
- Create: `app/api/pull_requests.py`
- Test: `tests/unit/test_pull_requests_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pull_requests_api.py
"""Tests for PR analysis API endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from httpx import AsyncClient, ASGITransport

from app.config import Settings, get_settings
from app.main import app
from app.models.db import PrAnalysis, User
from app.api.dependencies import get_current_user
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
        id="admin-1", username="admin", email="admin@test.com",
        password_hash="x", role="admin", is_active=True,
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
    pr.project_id = "proj-1"
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

        resp = await client.get("/api/v1/projects/proj-1/pull-requests")
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

        resp = await client.get("/api/v1/projects/proj-1/pull-requests?status=failed")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestGetPrAnalysis:
    @pytest.mark.asyncio
    async def test_get_detail(self, client, mock_session):
        pr = _make_pr_analysis()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pr
        mock_session.execute.return_value = mock_result

        resp = await client.get("/api/v1/projects/proj-1/pull-requests/pr-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "pr-1"
        assert data["ai_summary"] == "This PR modifies..."

    @pytest.mark.asyncio
    async def test_get_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        resp = await client.get("/api/v1/projects/proj-1/pull-requests/nonexistent")
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
            "changed_nodes": [{"fqn": "a.b", "name": "b", "type": "Function", "change_type": "modified"}],
            "downstream_count": 30,
            "upstream_count": 17,
            "cross_tech": [],
            "transactions_affected": [],
        }
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pr
        mock_session.execute.return_value = mock_result

        resp = await client.get("/api/v1/projects/proj-1/pull-requests/pr-1/impact")
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

        resp = await client.get("/api/v1/projects/proj-1/pull-requests/pr-1/drift")
        assert resp.status_code == 200
        assert resp.json()["has_drift"] is False


class TestReanalyze:
    @pytest.mark.asyncio
    async def test_reanalyze_queues_task(self, client, mock_session):
        pr = _make_pr_analysis()
        pr.status = "stale"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pr
        mock_session.execute.side_effect = [mock_result, mock_result]  # get pr, get config

        # Mock git config lookup
        config = MagicMock()
        config.api_token_encrypted = "encrypted"
        config.platform = "github"
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = config

        mock_session.execute.side_effect = [mock_result, mock_result2]

        with patch("app.api.pull_requests.BackgroundTasks"):
            resp = await client.post("/api/v1/projects/proj-1/pull-requests/pr-1/reanalyze")
        assert resp.status_code == 202
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pull_requests_api.py -v`
Expected: FAIL

- [ ] **Step 3: Implement PR analysis endpoints**

```python
# app/api/pull_requests.py
"""PR analysis list, detail, impact, drift, and re-analyze endpoints."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.config import Settings, get_settings
from app.models.db import PrAnalysis, ProjectGitConfig, User
from app.schemas.pull_requests import (
    PrAnalysisListResponse,
    PrAnalysisResponse,
    PrDriftResponse,
    PrImpactResponse,
)
from app.services.postgres import get_session

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/pull-requests",
    tags=["pull-requests"],
)


async def _get_pr_or_404(
    project_id: str, pr_analysis_id: str, session: AsyncSession
) -> PrAnalysis:
    result = await session.execute(
        select(PrAnalysis).where(
            PrAnalysis.id == pr_analysis_id,
            PrAnalysis.project_id == project_id,
        )
    )
    pr = result.scalar_one_or_none()
    if not pr:
        raise HTTPException(status_code=404, detail="PR analysis not found")
    return pr


@router.get("", response_model=PrAnalysisListResponse)
async def list_pr_analyses(
    project_id: str,
    status: str | None = Query(None),
    risk: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> PrAnalysisListResponse:
    """List PR analyses for a project, with optional filters."""
    base_filter = [PrAnalysis.project_id == project_id]
    if status:
        base_filter.append(PrAnalysis.status == status)
    if risk:
        base_filter.append(PrAnalysis.risk_level == risk)

    # Count
    count_q = select(func.count(PrAnalysis.id)).where(*base_filter)
    count_result = await session.execute(count_q)
    total = count_result.scalar() or 0

    # Fetch
    q = (
        select(PrAnalysis)
        .where(*base_filter)
        .order_by(PrAnalysis.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(q)
    items = result.scalars().all()

    return PrAnalysisListResponse(
        items=[PrAnalysisResponse.model_validate(pr) for pr in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{pr_analysis_id}", response_model=PrAnalysisResponse)
async def get_pr_analysis(
    project_id: str,
    pr_analysis_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> PrAnalysisResponse:
    """Get full PR analysis detail."""
    pr = await _get_pr_or_404(project_id, pr_analysis_id, session)
    return PrAnalysisResponse.model_validate(pr)


@router.get("/{pr_analysis_id}/impact")
async def get_pr_impact(
    project_id: str,
    pr_analysis_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    """Get detailed impact data for a PR analysis."""
    pr = await _get_pr_or_404(project_id, pr_analysis_id, session)
    if not pr.impact_summary:
        raise HTTPException(status_code=404, detail="Impact data not available")
    return {"pr_analysis_id": pr.id, **pr.impact_summary}


@router.get("/{pr_analysis_id}/drift")
async def get_pr_drift(
    project_id: str,
    pr_analysis_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    """Get drift report for a PR analysis."""
    pr = await _get_pr_or_404(project_id, pr_analysis_id, session)
    if not pr.drift_report:
        raise HTTPException(status_code=404, detail="Drift data not available")
    return {"pr_analysis_id": pr.id, **pr.drift_report}


@router.post("/{pr_analysis_id}/reanalyze", status_code=202)
async def reanalyze_pr(
    project_id: str,
    pr_analysis_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _user: User = Depends(get_current_user),
) -> dict:
    """Re-run analysis for a PR (e.g., after graph update)."""
    pr = await _get_pr_or_404(project_id, pr_analysis_id, session)

    # Get git config for API token
    config_result = await session.execute(
        select(ProjectGitConfig).where(ProjectGitConfig.project_id == project_id)
    )
    config = config_result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=400, detail="No git config — cannot re-analyze")

    pr.status = "pending"
    await session.commit()

    # Queue re-analysis (same background task as webhook)
    from app.api.webhooks import _run_analysis_background
    background_tasks.add_task(
        _run_analysis_background,
        pr_analysis_id=pr.id,
        project_id=project_id,
        api_token_encrypted=config.api_token_encrypted,
        platform=config.platform,
        secret_key=settings.secret_key,
        anthropic_api_key=settings.anthropic_api_key,
    )

    return {"status": "queued", "pr_analysis_id": pr.id}
```

- [ ] **Step 4: Register the router**

Add to `app/api/__init__.py`:
```python
from app.api.pull_requests import router as pull_requests_router
```
Add `"pull_requests_router"` to the `__all__` list.

Add to `app/main.py`:
```python
from app.api import pull_requests_router
# ...
application.include_router(pull_requests_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pull_requests_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend
git add app/api/pull_requests.py app/api/__init__.py app/main.py tests/unit/test_pull_requests_api.py
git commit -m "feat(phase5a): add PR analysis list, detail, impact, drift, and reanalyze endpoints"
```

---

## Success Criteria

- [ ] `GET /projects/{id}/pull-requests` returns paginated list with status/risk filters
- [ ] `GET /projects/{id}/pull-requests/{id}` returns full PR analysis detail
- [ ] `GET /projects/{id}/pull-requests/{id}/impact` returns structured impact data
- [ ] `GET /projects/{id}/pull-requests/{id}/drift` returns drift report
- [ ] `POST /projects/{id}/pull-requests/{id}/reanalyze` queues re-analysis (202)
- [ ] 404 returned for nonexistent analyses
- [ ] All endpoints require auth
- [ ] All tests pass: `uv run pytest tests/unit/test_pull_requests_api.py -v`
