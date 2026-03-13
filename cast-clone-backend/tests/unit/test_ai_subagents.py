"""Tests for the shared agentic loop runner."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.pr_analysis.ai.subagents import run_agent, AgentConfig, AgentResult
from app.pr_analysis.ai.tool_context import ToolContext


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.query = AsyncMock(return_value=[])
    return store


@pytest.fixture
def ctx(tmp_path, mock_store):
    return ToolContext(repo_path=str(tmp_path), graph_store=mock_store, app_name="test")


def _make_text_response(text: str):
    """Mock an Anthropic response with just text (agent done)."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    return resp


def _make_tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "tool_1"):
    """Mock an Anthropic response that requests a tool call."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = tool_name
    tool_block.input = tool_input
    tool_block.id = tool_id
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [tool_block]
    resp.usage = MagicMock(input_tokens=200, output_tokens=100)
    return resp


class TestRunAgent:
    @pytest.mark.asyncio
    async def test_simple_text_response(self, ctx):
        """Agent that returns text immediately (no tool calls)."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_text_response('{"role": "test", "data": true}')
        )

        config = AgentConfig(
            role="test_agent",
            system_prompt="You are a test agent.",
            initial_message="Analyze this.",
            tools=[],
            max_tool_calls=25,
        )

        result = await run_agent(mock_client, config, ctx, model="test-model", timeout=60)
        assert isinstance(result, AgentResult)
        assert result.final_text == '{"role": "test", "data": true}'
        assert result.tool_calls_made == 0
        assert result.total_tokens == 150

    @pytest.mark.asyncio
    async def test_tool_call_then_text(self, ctx):
        """Agent makes one tool call, then returns text."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _make_tool_use_response("list_directory", {"path": ""}),
                _make_text_response("Done analyzing."),
            ]
        )

        config = AgentConfig(
            role="test_agent",
            system_prompt="You are a test agent.",
            initial_message="Analyze the repo.",
            tools=["list_directory"],
            max_tool_calls=25,
        )

        with patch("app.pr_analysis.ai.subagents.handle_tool_call", return_value='{"entries": []}'):
            result = await run_agent(mock_client, config, ctx, model="test-model", timeout=60)

        assert result.tool_calls_made == 1
        assert result.final_text == "Done analyzing."

    @pytest.mark.asyncio
    async def test_tool_call_limit_enforced(self, ctx):
        """Agent hits tool call limit, forced to return."""
        mock_client = AsyncMock()
        # Always request tool calls
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _make_tool_use_response("list_directory", {"path": ""}, f"tool_{i}")
                for i in range(5)
            ] + [_make_text_response("Finally done.")]
        )

        config = AgentConfig(
            role="test_agent",
            system_prompt="Test",
            initial_message="Go.",
            tools=["list_directory"],
            max_tool_calls=3,  # Limit to 3
        )

        with patch("app.pr_analysis.ai.subagents.handle_tool_call", return_value='{"entries": []}'):
            result = await run_agent(mock_client, config, ctx, model="test-model", timeout=60)

        # After 3 tool calls, limit is hit; 4th returns error, then agent returns text
        assert result.tool_calls_made == 3

    @pytest.mark.asyncio
    async def test_tracks_tokens(self, ctx):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _make_tool_use_response("list_directory", {"path": ""}),
                _make_text_response("Done."),
            ]
        )

        config = AgentConfig(
            role="test", system_prompt="Test", initial_message="Go.",
            tools=["list_directory"], max_tool_calls=25,
        )

        with patch("app.pr_analysis.ai.subagents.handle_tool_call", return_value='{}'):
            result = await run_agent(mock_client, config, ctx, model="m", timeout=60)

        # Two API calls: 200+100 + 100+50 = 450
        assert result.total_tokens == 450
