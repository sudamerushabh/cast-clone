"""Tests for the Supervisor agent."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.pr_analysis.ai.supervisor import run_supervisor, SupervisorInput
from app.pr_analysis.ai.report_types import AgentReport
from app.pr_analysis.ai.tool_context import ToolContext
from app.pr_analysis.models import (
    AggregatedImpact,
    DriftReport,
    PullRequestEvent,
    GitPlatform,
)


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.query = AsyncMock(return_value=[])
    store.query_single = AsyncMock(return_value=None)
    return store


@pytest.fixture
def ctx(tmp_path, mock_store):
    return ToolContext(repo_path=str(tmp_path), graph_store=mock_store, app_name="test")


def _make_text_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=500, output_tokens=300)
    return resp


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


def _make_impact() -> AggregatedImpact:
    return AggregatedImpact(
        changed_nodes=[], downstream_affected=[], upstream_dependents=[],
        total_blast_radius=10, by_type={"Function": 5}, by_depth={1: 5},
        by_layer={}, by_module={}, cross_tech_impacts=[], transactions_affected=[],
    )


def _make_drift() -> DriftReport:
    return DriftReport(
        potential_new_module_deps=[], circular_deps_affected=[],
        new_files_outside_modules=[],
    )


class TestRunSupervisor:
    @pytest.mark.asyncio
    async def test_generates_summary(self, ctx):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_text_response("## VERDICT\nMedium risk PR...")
        )

        reports = [
            AgentReport(role="code_change_analyst", raw_text="report1", parsed={"role": "code_change_analyst"}),
            AgentReport(role="architecture_impact_analyst", raw_text="report2", parsed={"role": "arch"}),
            AgentReport(role="infra_config_analyst", raw_text="report3", parsed={"role": "infra"}),
            AgentReport(role="test_gap_analyst", raw_text="report4", parsed={"role": "test"}),
        ]

        sup_input = SupervisorInput(
            subagent_reports=reports,
            pr_event=_make_event(),
            impact=_make_impact(),
            drift=_make_drift(),
            risk_level="Medium",
        )

        result = await run_supervisor(mock_client, sup_input, ctx, model="test-model", settings=MagicMock(pr_analysis_max_subagents=15))
        assert "VERDICT" in result.final_text
        assert result.tool_calls_made == 0
        assert result.total_tokens == 800

    @pytest.mark.asyncio
    async def test_includes_failed_agents(self, ctx):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_text_response("Summary with partial data")
        )

        reports = [
            AgentReport(role="code_change_analyst", raw_text="good report", parsed={"role": "code"}),
            AgentReport(role="infra_config_analyst", raw_text="Agent failed: timeout", parsed=None, parse_failed=True),
        ]

        sup_input = SupervisorInput(
            subagent_reports=reports,
            pr_event=_make_event(),
            impact=_make_impact(),
            drift=_make_drift(),
            risk_level="Low",
        )

        result = await run_supervisor(mock_client, sup_input, ctx, model="m", settings=MagicMock(pr_analysis_max_subagents=15))
        # Supervisor should still produce output despite failed subagent
        assert result.final_text == "Summary with partial data"

    @pytest.mark.asyncio
    async def test_handles_tool_use_loop(self, ctx):
        """Test that the supervisor processes tool calls before final response."""
        # First response: tool_use
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "read_file"
        tool_block.id = "tool_1"
        tool_block.input = {"path": "README.md"}

        tool_resp = MagicMock()
        tool_resp.stop_reason = "tool_use"
        tool_resp.content = [tool_block]
        tool_resp.usage = MagicMock(input_tokens=100, output_tokens=50)

        # Second response: end_turn
        final_resp = _make_text_response("## VERDICT\nAfter reading README...")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[tool_resp, final_resp])

        # Create the README so read_file works
        readme = ctx.repo_path / "README.md" if hasattr(ctx.repo_path, '__truediv__') else None
        import pathlib
        pathlib.Path(ctx.repo_path, "README.md").write_text("# Test repo")

        reports = [
            AgentReport(role="code_change_analyst", raw_text="report", parsed={"role": "code"}),
        ]

        sup_input = SupervisorInput(
            subagent_reports=reports,
            pr_event=_make_event(),
            impact=_make_impact(),
            drift=_make_drift(),
            risk_level="Low",
        )

        result = await run_supervisor(mock_client, sup_input, ctx, model="m", settings=MagicMock(pr_analysis_max_subagents=15))
        assert result.tool_calls_made == 1
        assert "VERDICT" in result.final_text
        assert result.total_tokens == 950  # 150 + 800

    @pytest.mark.asyncio
    async def test_dispatch_subagent_budget(self, ctx):
        """Test that dispatch_subagent respects the 3-agent budget."""
        from app.pr_analysis.ai.supervisor import _handle_dispatch

        settings = MagicMock(pr_analysis_max_subagents=15)

        # Should be rejected when budget is exhausted
        result = await _handle_dispatch(
            AsyncMock(), {"role": "test", "prompt": "investigate", "tools": ["read_file"]},
            ctx, "model", settings, dispatched_count=3,
        )
        parsed = json.loads(result)
        assert "budget exceeded" in parsed["error"]

    @pytest.mark.asyncio
    async def test_dispatch_subagent_invalid_tools(self, ctx):
        """Test that dispatch_subagent rejects invalid tool names."""
        from app.pr_analysis.ai.supervisor import _handle_dispatch

        settings = MagicMock(pr_analysis_max_subagents=15)

        result = await _handle_dispatch(
            AsyncMock(), {"role": "test", "prompt": "investigate", "tools": ["invalid_tool"]},
            ctx, "model", settings, dispatched_count=0,
        )
        parsed = json.loads(result)
        assert "Invalid tool names" in parsed["error"]

    @pytest.mark.asyncio
    async def test_supervisor_handles_api_error(self, ctx):
        """Test that the supervisor returns a graceful error on API failure."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))

        reports = [
            AgentReport(role="code_change_analyst", raw_text="report", parsed={"role": "code"}),
        ]

        sup_input = SupervisorInput(
            subagent_reports=reports,
            pr_event=_make_event(),
            impact=_make_impact(),
            drift=_make_drift(),
            risk_level="Low",
        )

        result = await run_supervisor(mock_client, sup_input, ctx, model="m", settings=MagicMock(pr_analysis_max_subagents=15))
        assert result.error is not None
        assert "API down" in result.error
        assert "Supervisor failed" in result.final_text
