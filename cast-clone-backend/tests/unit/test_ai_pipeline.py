"""End-to-end tests for the AI pipeline public API."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.pr_analysis.ai import generate_pr_summary
from app.pr_analysis.ai.report_types import SummaryResult
from app.pr_analysis.models import (
    AggregatedImpact,
    ChangedNode,
    DiffHunk,
    DriftReport,
    FileDiff,
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)


def _make_event() -> PullRequestEvent:
    return PullRequestEvent(
        platform=GitPlatform.github,
        repo_url="https://github.com/org/repo",
        pr_number=42,
        pr_title="Fix order processing",
        pr_description="Fixes #123",
        author="alice",
        source_branch="fix/order-bug",
        target_branch="main",
        action="opened",
        commit_sha="abc123",
        created_at="2026-03-13T10:00:00Z",
    )


def _make_diff() -> PRDiff:
    return PRDiff(
        files=[
            FileDiff(
                path="src/main/java/com/app/OrderService.java",
                status="modified", old_path=None, additions=5, deletions=2,
                hunks=[DiffHunk(old_start=10, old_count=3, new_start=10, new_count=6)],
            )
        ],
        total_additions=5, total_deletions=2, total_files_changed=1,
    )


def _make_impact() -> AggregatedImpact:
    return AggregatedImpact(
        changed_nodes=[
            ChangedNode(
                fqn="com.app.OrderService.create", name="create",
                type="Function", path="src/main/java/com/app/OrderService.java",
                line=10, end_line=50, language="java", change_type="modified",
            )
        ],
        downstream_affected=[], upstream_dependents=[],
        total_blast_radius=10, by_type={"Function": 5}, by_depth={1: 5},
        by_layer={}, by_module={}, cross_tech_impacts=[], transactions_affected=[],
    )


def _make_drift() -> DriftReport:
    return DriftReport(
        potential_new_module_deps=[], circular_deps_affected=[],
        new_files_outside_modules=[],
    )


def _mock_text_response(text):
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    return resp


def _mock_settings():
    settings = MagicMock()
    settings.aws_region = "us-east-1"
    settings.pr_analysis_model = "test-model"
    settings.pr_analysis_supervisor_model = "test-supervisor-model"
    settings.pr_analysis_max_subagents = 15
    settings.pr_analysis_max_total_tokens = 500_000
    return settings


class TestGeneratePrSummary:
    @pytest.mark.asyncio
    async def test_full_pipeline_returns_summary(self, tmp_path):
        # Create a minimal repo
        src = tmp_path / "src" / "main" / "java" / "com" / "app"
        src.mkdir(parents=True)
        (src / "OrderService.java").write_text("public class OrderService {}")

        mock_store = AsyncMock()
        mock_store.query = AsyncMock(return_value=[])
        mock_store.query_single = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_text_response('{"role": "test", "summary": "ok"}')
        )

        with (
            patch("app.pr_analysis.ai.AsyncAnthropicBedrock", return_value=mock_client),
            patch("app.pr_analysis.ai.get_settings", return_value=_mock_settings()),
        ):
            result = await generate_pr_summary(
                pr_event=_make_event(),
                diff=_make_diff(),
                impact=_make_impact(),
                drift=_make_drift(),
                risk_level="Medium",
                repo_path=str(tmp_path),
                graph_store=mock_store,
                app_name="test-project",
            )

        assert isinstance(result, SummaryResult)
        assert len(result.summary) > 0
        assert result.agents_run >= 1

    @pytest.mark.asyncio
    async def test_fallback_when_no_repo_path(self):
        mock_store = AsyncMock()
        mock_store.query = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_text_response("Simple fallback summary")
        )

        with (
            patch("app.pr_analysis.ai.AsyncAnthropicBedrock", return_value=mock_client),
            patch("app.pr_analysis.ai.get_settings", return_value=_mock_settings()),
        ):
            result = await generate_pr_summary(
                pr_event=_make_event(),
                diff=_make_diff(),
                impact=_make_impact(),
                drift=_make_drift(),
                risk_level="Low",
                repo_path="",  # No repo
                graph_store=mock_store,
                app_name="test",
            )

        assert isinstance(result, SummaryResult)
        # Falls back to single-call mode
        assert len(result.summary) > 0

    @pytest.mark.asyncio
    async def test_fallback_on_pipeline_failure(self, tmp_path):
        mock_store = AsyncMock()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))

        with (
            patch("app.pr_analysis.ai.AsyncAnthropicBedrock", return_value=mock_client),
            patch("app.pr_analysis.ai.get_settings", return_value=_mock_settings()),
        ):
            result = await generate_pr_summary(
                pr_event=_make_event(),
                diff=_make_diff(),
                impact=_make_impact(),
                drift=_make_drift(),
                risk_level="Low",
                repo_path=str(tmp_path),
                graph_store=mock_store,
                app_name="test",
            )

        assert isinstance(result, SummaryResult)
        # Should not crash -- returns fallback
        assert "unavailable" in result.summary.lower() or len(result.summary) > 0

    @pytest.mark.asyncio
    async def test_single_call_fallback_success(self):
        """Test that single-call fallback produces a proper SummaryResult."""
        mock_store = AsyncMock()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_text_response("This PR changes order processing logic.")
        )

        with (
            patch("app.pr_analysis.ai.AsyncAnthropicBedrock", return_value=mock_client),
            patch("app.pr_analysis.ai.get_settings", return_value=_mock_settings()),
        ):
            result = await generate_pr_summary(
                pr_event=_make_event(),
                diff=_make_diff(),
                impact=_make_impact(),
                drift=_make_drift(),
                risk_level="High",
                repo_path="",
                graph_store=mock_store,
                app_name="test",
            )

        assert result.summary == "This PR changes order processing logic."
        assert result.tokens_used == 150  # 100 + 50
        assert result.agents_run == 1
        assert result.agents_failed == 0
