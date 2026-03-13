# Phase 5a M8 — PR Analysis Orchestrator

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire together the entire PR analysis pipeline: webhook → fetch diff → map to graph → compute impact → detect drift → score risk → generate AI summary → store results. Runs as a FastAPI background task.

**Architecture:** A single `analyzer.py` module with the main orchestrator function `run_pr_analysis()` that coordinates M2-M7 components. Called from the webhook endpoint via `BackgroundTasks`. Updates `PrAnalysis` status through the pipeline. Logs activity. Handles stale analysis detection.

**Tech Stack:** FastAPI BackgroundTasks, SQLAlchemy async, all M2-M7 modules.

**Depends On:** M2 (git clients), M3 (webhook creates PrAnalysis record), M4 (diff mapper), M5 (risk + drift), M6 (impact aggregator), M7 (AI summary).

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── pr_analysis/
│   │   └── analyzer.py             # CREATE — main orchestrator
│   └── api/
│       └── webhooks.py             # MODIFY — wire in background task
└── tests/
    └── unit/
        └── test_pr_analyzer.py     # CREATE
```

---

### Task 1: PR Analysis Orchestrator

**Files:**
- Create: `app/pr_analysis/analyzer.py`
- Test: `tests/unit/test_pr_analyzer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pr_analyzer.py
"""Tests for the PR analysis orchestrator."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.pr_analysis.analyzer import run_pr_analysis
from app.pr_analysis.models import (
    ChangedNode,
    DiffHunk,
    FileDiff,
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)
from app.pr_analysis.diff_mapper import DiffMapResult


@pytest.fixture
def mock_session():
    session = AsyncMock()
    return session


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.query = AsyncMock(return_value=[])
    return store


@pytest.fixture
def pr_record():
    record = MagicMock()
    record.id = "analysis-1"
    record.project_id = "proj-1"
    record.platform = "github"
    record.pr_number = 42
    record.pr_title = "Fix bug"
    record.pr_description = "Desc"
    record.pr_author = "alice"
    record.source_branch = "fix/bug"
    record.target_branch = "main"
    record.commit_sha = "abc123"
    record.pr_url = "https://github.com/org/repo/pull/42"
    record.status = "pending"
    record.risk_level = None
    record.impact_summary = None
    record.drift_report = None
    record.ai_summary = None
    record.files_changed = None
    record.additions = None
    record.deletions = None
    record.changed_node_count = None
    record.blast_radius_total = None
    record.analysis_duration_ms = None
    record.ai_summary_tokens = None
    return record


class TestRunPrAnalysis:
    @pytest.mark.asyncio
    async def test_successful_analysis(self, mock_session, mock_store, pr_record):
        """Full pipeline runs and updates the record."""
        mock_diff = PRDiff(
            files=[
                FileDiff(
                    path="Svc.java", status="modified", old_path=None,
                    additions=5, deletions=2,
                    hunks=[DiffHunk(old_start=10, old_count=3, new_start=10, new_count=6)],
                )
            ],
            total_additions=5, total_deletions=2, total_files_changed=1,
        )

        mock_map_result = DiffMapResult(
            changed_nodes=[
                ChangedNode(
                    fqn="com.app.Svc.method", name="method", type="Function",
                    path="Svc.java", line=10, end_line=20,
                    language="java", change_type="modified",
                )
            ],
            new_files=[], non_graph_files=[], deleted_files=[],
        )

        with (
            patch("app.pr_analysis.analyzer._fetch_diff", return_value=mock_diff),
            patch("app.pr_analysis.analyzer._create_diff_mapper") as mock_mapper_factory,
            patch("app.pr_analysis.analyzer._create_impact_aggregator") as mock_agg_factory,
            patch("app.pr_analysis.analyzer._create_drift_detector") as mock_drift_factory,
            patch("app.pr_analysis.analyzer.classify_risk", return_value="Medium"),
            patch("app.pr_analysis.analyzer.generate_pr_summary") as mock_ai,
            patch("app.pr_analysis.analyzer.log_activity") as mock_log,
        ):
            mock_mapper = AsyncMock()
            mock_mapper.map_diff_to_nodes.return_value = mock_map_result
            mock_mapper_factory.return_value = mock_mapper

            mock_agg = AsyncMock()
            mock_agg.compute_aggregated_impact.return_value = MagicMock(
                total_blast_radius=10,
                changed_nodes=mock_map_result.changed_nodes,
                downstream_affected=[], upstream_dependents=[],
                by_type={"Function": 5}, by_depth={1: 5},
                by_layer={}, by_module={},
                cross_tech_impacts=[], transactions_affected=[],
            )
            mock_agg_factory.return_value = mock_agg

            mock_drift = AsyncMock()
            mock_drift.detect_drift.return_value = MagicMock(
                has_drift=False,
                potential_new_module_deps=[], circular_deps_affected=[],
                new_files_outside_modules=[],
            )
            mock_drift_factory.return_value = mock_drift

            mock_ai.return_value = MagicMock(summary="AI summary text", tokens_used=500)

            await run_pr_analysis(
                pr_record=pr_record,
                session=mock_session,
                store=mock_store,
                api_token="ghp_test",
                anthropic_api_key="sk-ant-test",
                app_name="proj-1",
            )

        # Verify record was updated
        assert pr_record.status == "completed"
        assert pr_record.risk_level == "Medium"
        assert pr_record.blast_radius_total == 10
        assert pr_record.ai_summary == "AI summary text"
        assert pr_record.files_changed == 1
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_failed_analysis_sets_error_status(self, mock_session, mock_store, pr_record):
        """If diff fetch fails, status is set to 'failed'."""
        with patch("app.pr_analysis.analyzer._fetch_diff", side_effect=Exception("API timeout")):
            await run_pr_analysis(
                pr_record=pr_record,
                session=mock_session,
                store=mock_store,
                api_token="ghp_test",
                anthropic_api_key="",
                app_name="proj-1",
            )

        assert pr_record.status == "failed"
        mock_session.commit.assert_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_analyzer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the orchestrator**

```python
# app/pr_analysis/analyzer.py
"""PR analysis orchestrator — coordinates the full analysis pipeline."""
from __future__ import annotations

import time
from dataclasses import asdict

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.git import create_platform_client
from app.pr_analysis.ai_summary import generate_pr_summary
from app.pr_analysis.diff_mapper import DiffMapper
from app.pr_analysis.drift_detector import DriftDetector
from app.pr_analysis.impact_aggregator import ImpactAggregator
from app.pr_analysis.models import (
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)
from app.pr_analysis.risk_scorer import classify_risk
from app.services.activity import log_activity
from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)


async def run_pr_analysis(
    pr_record,  # PrAnalysis ORM instance
    session: AsyncSession,
    store: GraphStore,
    api_token: str,
    anthropic_api_key: str,
    app_name: str,
) -> None:
    """Run the full PR analysis pipeline.

    Steps:
    1. Fetch diff via Git platform API
    2. Map diff to graph nodes
    3. Compute impact per changed node + aggregate
    4. Detect architecture drift
    5. Classify risk
    6. Generate AI summary
    7. Store results
    """
    start_time = time.monotonic()

    try:
        pr_record.status = "analyzing"
        await session.commit()

        # 1. Fetch diff
        diff = await _fetch_diff(
            platform=pr_record.platform,
            repo_url=_get_repo_url(pr_record),
            pr_number=pr_record.pr_number,
            token=api_token,
        )

        pr_record.files_changed = diff.total_files_changed
        pr_record.additions = diff.total_additions
        pr_record.deletions = diff.total_deletions

        # 2. Map diff to graph nodes
        mapper = _create_diff_mapper(store, app_name)
        map_result = await mapper.map_diff_to_nodes(diff)

        pr_record.changed_node_count = len(map_result.changed_nodes)

        # 3. Compute aggregated impact
        aggregator = _create_impact_aggregator(store, app_name)
        impact = await aggregator.compute_aggregated_impact(map_result.changed_nodes)

        pr_record.blast_radius_total = impact.total_blast_radius

        # 4. Detect drift
        detector = _create_drift_detector(store, app_name)
        drift = await detector.detect_drift(
            map_result.changed_nodes,
            new_files=map_result.new_files,
        )

        # 5. Classify risk
        risk_level = classify_risk(impact)
        pr_record.risk_level = risk_level

        # 6. Generate AI summary
        pr_event = PullRequestEvent(
            platform=GitPlatform(pr_record.platform),
            repo_url=_get_repo_url(pr_record),
            pr_number=pr_record.pr_number,
            pr_title=pr_record.pr_title,
            pr_description=pr_record.pr_description or "",
            author=pr_record.pr_author,
            source_branch=pr_record.source_branch,
            target_branch=pr_record.target_branch,
            action="opened",
            commit_sha=pr_record.commit_sha,
            created_at="",
        )

        summary_result = await generate_pr_summary(
            pr_event=pr_event,
            impact=impact,
            drift=drift,
            risk_level=risk_level,
            api_key=anthropic_api_key,
        )
        pr_record.ai_summary = summary_result.summary
        pr_record.ai_summary_tokens = summary_result.tokens_used

        # 7. Store structured results as JSON
        pr_record.impact_summary = {
            "total_blast_radius": impact.total_blast_radius,
            "by_type": impact.by_type,
            "by_depth": impact.by_depth,
            "by_layer": impact.by_layer,
            "changed_nodes": [
                {"fqn": n.fqn, "name": n.name, "type": n.type, "change_type": n.change_type}
                for n in impact.changed_nodes
            ],
            "downstream_affected": [
                {"fqn": a.fqn, "name": a.name, "type": a.type, "file": a.file, "depth": a.depth}
                for a in impact.downstream_affected[:200]
            ],
            "upstream_dependents": [
                {"fqn": a.fqn, "name": a.name, "type": a.type, "file": a.file, "depth": a.depth}
                for a in impact.upstream_dependents[:200]
            ],
            "downstream_count": len(impact.downstream_affected),
            "upstream_count": len(impact.upstream_dependents),
            "cross_tech": [
                {"kind": ct.kind, "name": ct.name, "detail": ct.detail}
                for ct in impact.cross_tech_impacts
            ],
            "transactions_affected": impact.transactions_affected,
            "new_files": map_result.new_files,
            "non_graph_files": map_result.non_graph_files,
        }

        pr_record.drift_report = {
            "has_drift": drift.has_drift,
            "potential_new_module_deps": [
                {"from_module": d.from_module, "to_module": d.to_module}
                for d in drift.potential_new_module_deps
            ],
            "circular_deps_affected": drift.circular_deps_affected,
            "new_files_outside_modules": drift.new_files_outside_modules,
        }

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        pr_record.analysis_duration_ms = elapsed_ms
        pr_record.status = "completed"
        await session.commit()

        logger.info(
            "pr_analysis_completed",
            analysis_id=pr_record.id,
            risk_level=risk_level,
            blast_radius=impact.total_blast_radius,
            duration_ms=elapsed_ms,
        )

        # Activity log
        await log_activity(
            session=session,
            action="pr_analysis.completed",
            resource_type="pr_analysis",
            resource_id=pr_record.id,
            details={
                "pr_number": pr_record.pr_number,
                "risk_level": risk_level,
                "blast_radius": impact.total_blast_radius,
                "duration_ms": elapsed_ms,
            },
        )

    except Exception as exc:
        logger.error(
            "pr_analysis_failed",
            analysis_id=pr_record.id,
            error=str(exc),
            exc_info=True,
        )
        pr_record.status = "failed"
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        pr_record.analysis_duration_ms = elapsed_ms
        await session.commit()

        await log_activity(
            session=session,
            action="pr_analysis.failed",
            resource_type="pr_analysis",
            resource_id=pr_record.id,
            details={"error": str(exc)},
        )


def _get_repo_url(pr_record) -> str:
    """Extract repo URL from the PR record's pr_url or fall back."""
    if pr_record.pr_url:
        # PR URL like https://github.com/org/repo/pull/42 → https://github.com/org/repo
        parts = pr_record.pr_url.split("/")
        # Find "pull" or "merge_requests" or "pull-requests" and take everything before
        for i, p in enumerate(parts):
            if p in ("pull", "pulls", "merge_requests", "pull-requests"):
                return "/".join(parts[:i])
    return ""


async def _fetch_diff(
    platform: str, repo_url: str, pr_number: int, token: str
) -> PRDiff:
    client = create_platform_client(platform)
    return await client.fetch_diff(repo_url, pr_number, token)


def _create_diff_mapper(store: GraphStore, app_name: str) -> DiffMapper:
    return DiffMapper(store, app_name)


def _create_impact_aggregator(store: GraphStore, app_name: str) -> ImpactAggregator:
    return ImpactAggregator(store, app_name)


def _create_drift_detector(store: GraphStore, app_name: str) -> DriftDetector:
    return DriftDetector(store, app_name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_analyzer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/analyzer.py tests/unit/test_pr_analyzer.py
git commit -m "feat(phase5a): implement PR analysis orchestrator pipeline"
```

---

### Task 2: Wire Orchestrator into Webhook Endpoint

**Files:**
- Modify: `app/api/webhooks.py`

- [ ] **Step 1: Update webhook endpoint to queue analysis**

In `app/api/webhooks.py`, replace the commented-out background task line with the actual call:

```python
    # Add at top of webhooks.py:
    from app.config import Settings, get_settings
    from app.services.crypto import decrypt_token
    from app.services.neo4j import Neo4jGraphStore, get_driver

    # Also add to app/services/postgres.py — a new public function for background tasks:
    # @contextlib.asynccontextmanager
    # async def get_background_session() -> AsyncIterator[AsyncSession]:
    #     """Get a session outside of FastAPI's Depends (for background tasks)."""
    #     assert _session_factory is not None, "PostgreSQL not initialized"
    #     async with _session_factory() as session:
    #         yield session

    # In the receive_webhook function, after creating pr_record:
    # (replace the commented line)
    settings = get_settings()
    background_tasks.add_task(
        _run_analysis_background,
        pr_analysis_id=pr_record.id,
        project_id=project_id,
        api_token_encrypted=config.api_token_encrypted,
        platform=platform,
        secret_key=settings.secret_key,
        anthropic_api_key=settings.anthropic_api_key,
    )
```

Add the background wrapper function:

```python
async def _run_analysis_background(
    pr_analysis_id: str,
    project_id: str,
    api_token_encrypted: str,
    platform: str,
    secret_key: str,
    anthropic_api_key: str,
) -> None:
    """Background task wrapper for PR analysis."""
    from app.pr_analysis.analyzer import run_pr_analysis
    from app.services.postgres import get_background_session

    async with get_background_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(PrAnalysis).where(PrAnalysis.id == pr_analysis_id)
        )
        pr_record = result.scalar_one_or_none()
        if not pr_record:
            logger.error("pr_analysis_not_found", id=pr_analysis_id)
            return

        store = Neo4jGraphStore(get_driver())
        api_token = decrypt_token(api_token_encrypted, secret_key)

        await run_pr_analysis(
            pr_record=pr_record,
            session=session,
            store=store,
            api_token=api_token,
            anthropic_api_key=anthropic_api_key,
            app_name=project_id,
        )
```

- [ ] **Step 2: Run existing webhook tests to verify no regression**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhooks_api.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/api/webhooks.py
git commit -m "feat(phase5a): wire PR analysis orchestrator into webhook endpoint"
```

---

### Task 3: Stale Analysis Detection

**Files:**
- Modify: `app/pr_analysis/analyzer.py`
- Test: `tests/unit/test_pr_analyzer.py` (append)

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_pr_analyzer.py`:

```python
from app.pr_analysis.analyzer import mark_analyses_stale


class TestStaleDetection:
    @pytest.mark.asyncio
    async def test_mark_stale(self, mock_session):
        """mark_analyses_stale updates all completed analyses for a project."""
        await mark_analyses_stale(mock_session, "proj-1")
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_analyzer.py::TestStaleDetection -v`
Expected: FAIL

- [ ] **Step 3: Implement stale marking**

Add to `app/pr_analysis/analyzer.py`:

```python
from sqlalchemy import update
from app.models.db import PrAnalysis


async def mark_analyses_stale(
    session: AsyncSession, project_id: str
) -> None:
    """Mark all completed PR analyses for a project as stale.

    Called after a full project re-analysis to indicate the graph has changed.
    """
    await session.execute(
        update(PrAnalysis)
        .where(
            PrAnalysis.project_id == project_id,
            PrAnalysis.status == "completed",
        )
        .values(status="stale")
    )
    await session.commit()
    logger.info("pr_analyses_marked_stale", project_id=project_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_analyzer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/analyzer.py tests/unit/test_pr_analyzer.py
git commit -m "feat(phase5a): add stale analysis detection for graph version tracking"
```

---

## Success Criteria

- [ ] `run_pr_analysis()` coordinates the full pipeline: fetch diff → map → impact → drift → risk → AI → store
- [ ] On success: status="completed", all fields populated, activity logged
- [ ] On failure: status="failed", error logged, activity logged
- [ ] Webhook endpoint queues analysis as background task
- [ ] `mark_analyses_stale()` marks completed analyses as stale after project re-analysis
- [ ] All tests pass: `uv run pytest tests/unit/test_pr_analyzer.py -v`
