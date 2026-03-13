"""Tests for the PR analysis orchestrator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.pr_analysis.analyzer import mark_analyses_stale, run_pr_analysis
from app.pr_analysis.models import (
    ChangedNode,
    DiffHunk,
    FileDiff,
    PRDiff,
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
                    path="Svc.java",
                    status="modified",
                    old_path=None,
                    additions=5,
                    deletions=2,
                    hunks=[DiffHunk(old_start=10, old_count=3, new_start=10, new_count=6)],
                )
            ],
            total_additions=5,
            total_deletions=2,
            total_files_changed=1,
        )

        mock_map_result = DiffMapResult(
            changed_nodes=[
                ChangedNode(
                    fqn="com.app.Svc.method",
                    name="method",
                    type="Function",
                    path="Svc.java",
                    line=10,
                    end_line=20,
                    language="java",
                    change_type="modified",
                )
            ],
            new_files=[],
            non_graph_files=[],
            deleted_files=[],
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
                downstream_affected=[],
                upstream_dependents=[],
                by_type={"Function": 5},
                by_depth={1: 5},
                by_layer={},
                by_module={},
                cross_tech_impacts=[],
                transactions_affected=[],
            )
            mock_agg_factory.return_value = mock_agg

            mock_drift = AsyncMock()
            mock_drift.detect_drift.return_value = MagicMock(
                has_drift=False,
                potential_new_module_deps=[],
                circular_deps_affected=[],
                new_files_outside_modules=[],
            )
            mock_drift_factory.return_value = mock_drift

            mock_ai.return_value = MagicMock(summary="AI summary text", tokens_used=500)

            await run_pr_analysis(
                pr_record=pr_record,
                session=mock_session,
                store=mock_store,
                api_token="ghp_test",
                repo_path="/tmp/repos/test-repo",
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
        with patch(
            "app.pr_analysis.analyzer._fetch_diff", side_effect=Exception("API timeout")
        ):
            await run_pr_analysis(
                pr_record=pr_record,
                session=mock_session,
                store=mock_store,
                api_token="ghp_test",
                repo_path="/tmp/repos/test-repo",
                app_name="proj-1",
            )

        assert pr_record.status == "failed"
        mock_session.commit.assert_called()


class TestStaleDetection:
    @pytest.mark.asyncio
    async def test_mark_stale(self, mock_session):
        """mark_analyses_stale updates all completed analyses for a project."""
        await mark_analyses_stale(mock_session, "proj-1")
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
