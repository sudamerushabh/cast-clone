# tests/unit/test_summary_service.py
"""Tests for the AI summary service.

Mocks Anthropic client and database -- no external services needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.summaries import (
    assemble_node_context,
    compute_graph_hash,
    generate_summary,
    get_or_create_summary,
)
from app.ai.tools import ChatToolContext


@pytest.fixture
def mock_graph_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def ctx(mock_graph_store: AsyncMock) -> ChatToolContext:
    return ChatToolContext(
        graph_store=mock_graph_store,
        app_name="test-app",
        project_id="proj-123",
        db_session=AsyncMock(),
    )


class TestComputeGraphHash:
    @pytest.mark.asyncio
    async def test_hash_deterministic(self, ctx):
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.Caller"}],
            [{"fqn": "com.app.Callee"}],
        ]
        h1 = await compute_graph_hash(ctx, "com.app.OrderService")

        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.Caller"}],
            [{"fqn": "com.app.Callee"}],
        ]
        h2 = await compute_graph_hash(ctx, "com.app.OrderService")
        assert h1 == h2
        assert len(h1) == 64

    @pytest.mark.asyncio
    async def test_hash_changes_on_neighbor_change(self, ctx):
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.A"}],
            [{"fqn": "com.app.B"}],
        ]
        h1 = await compute_graph_hash(ctx, "com.app.X")

        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.A"}, {"fqn": "com.app.C"}],
            [{"fqn": "com.app.B"}],
        ]
        h2 = await compute_graph_hash(ctx, "com.app.X")
        assert h1 != h2

    @pytest.mark.asyncio
    async def test_hash_order_independent(self, ctx):
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.B"}, {"fqn": "com.app.A"}],
            [],
        ]
        h1 = await compute_graph_hash(ctx, "com.app.X")

        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.A"}, {"fqn": "com.app.B"}],
            [],
        ]
        h2 = await compute_graph_hash(ctx, "com.app.X")
        assert h1 == h2


class TestAssembleNodeContext:
    @pytest.mark.asyncio
    async def test_assembles_details_and_source(self, ctx):
        ctx.graph_store.query_single.return_value = {
            "fqn": "com.app.OrderService",
            "name": "OrderService",
            "type": "Class",
            "language": "Java",
            "path": "src/OrderService.java",
            "line": 1,
            "end_line": 50,
            "loc": 50,
            "complexity": 5,
            "community_id": 1,
        }
        ctx.graph_store.query.side_effect = [
            [
                {"fqn": f"com.app.Caller{i}", "name": f"Caller{i}", "type": "Class"}
                for i in range(5)
            ],
            [
                {"fqn": f"com.app.Callee{i}", "name": f"Callee{i}", "type": "Class"}
                for i in range(3)
            ],
        ]
        result = await assemble_node_context(ctx, "com.app.OrderService")
        assert result["node"]["fqn"] == "com.app.OrderService"
        assert len(result["callers"]) == 5
        assert len(result["callees"]) == 3

    @pytest.mark.asyncio
    async def test_caps_callers_at_20(self, ctx):
        ctx.graph_store.query_single.return_value = {
            "fqn": "com.app.X",
            "name": "X",
            "type": "Class",
            "language": "Java",
            "path": "X.java",
            "line": 1,
            "end_line": 10,
            "loc": 10,
            "complexity": 1,
            "community_id": None,
        }
        ctx.graph_store.query.side_effect = [
            [
                {"fqn": f"com.app.C{i}", "name": f"C{i}", "type": "Class"}
                for i in range(30)
            ],
            [],
        ]
        result = await assemble_node_context(ctx, "com.app.X")
        assert len(result["callers"]) == 20

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_node(self, ctx):
        ctx.graph_store.query_single.return_value = None
        result = await assemble_node_context(ctx, "does.not.exist")
        assert result is None


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_calls_anthropic_and_returns_text(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="OrderService is responsible for...")]
        mock_response.usage.input_tokens = 500
        mock_response.usage.output_tokens = 200

        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response

        node_context = {
            "node": {
                "fqn": "com.app.OrderService",
                "name": "OrderService",
                "type": "Class",
            },
            "callers": [{"fqn": "com.app.A", "name": "A"}],
            "callees": [{"fqn": "com.app.B", "name": "B"}],
        }

        text, tokens = await generate_summary(
            client=mock_client,
            model="us.anthropic.claude-sonnet-4-6",
            max_tokens=512,
            node_context=node_context,
        )
        assert text == "OrderService is responsible for..."
        assert tokens == 700
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_includes_source_code_in_prompt(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Summary text")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response

        node_context = {
            "node": {"fqn": "com.app.X", "name": "X", "type": "Class"},
            "callers": [],
            "callees": [],
            "source_code": "1: public class X {\n2:   void run() {}\n3: }",
        }

        await generate_summary(
            client=mock_client,
            model="model-1",
            max_tokens=512,
            node_context=node_context,
        )
        call_args = mock_client.messages.create.call_args
        user_msg = call_args[1]["messages"][0]["content"]
        assert "public class X" in user_msg


class TestGetOrCreateSummary:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached(self, ctx):
        mock_session = ctx.db_session
        mock_row = MagicMock()
        mock_row.summary = "Cached summary text"
        mock_row.model = "model-1"
        mock_row.graph_hash = "abc123"
        mock_row.tokens_used = 300

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_session.execute.return_value = mock_result

        with patch("app.ai.summaries.compute_graph_hash", return_value="abc123"):
            result = await get_or_create_summary(
                ctx=ctx,
                node_fqn="com.app.OrderService",
                client=AsyncMock(),
                model="model-1",
                max_tokens=512,
            )
        assert result["cached"] is True
        assert result["summary"] == "Cached summary text"

    @pytest.mark.asyncio
    async def test_cache_miss_generates_and_upserts(self, ctx):
        mock_session = ctx.db_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Generated summary")]
        mock_response.usage.input_tokens = 400
        mock_response.usage.output_tokens = 150
        mock_client.messages.create.return_value = mock_response

        with (
            patch("app.ai.summaries.compute_graph_hash", return_value="new_hash"),
            patch(
                "app.ai.summaries.assemble_node_context",
                return_value={
                    "node": {"fqn": "com.app.X", "name": "X", "type": "Class"},
                    "callers": [],
                    "callees": [],
                },
            ),
        ):
            result = await get_or_create_summary(
                ctx=ctx,
                node_fqn="com.app.X",
                client=mock_client,
                model="model-1",
                max_tokens=512,
            )
        assert result["cached"] is False
        assert result["summary"] == "Generated summary"
        assert result["tokens_used"] == 550
        assert mock_session.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_stale_cache_regenerates(self, ctx):
        mock_session = ctx.db_session
        mock_row = MagicMock()
        mock_row.summary = "Old summary"
        mock_row.model = "model-1"
        mock_row.graph_hash = "old_hash"
        mock_row.tokens_used = 200

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_session.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Fresh summary")]
        mock_response.usage.input_tokens = 300
        mock_response.usage.output_tokens = 100
        mock_client.messages.create.return_value = mock_response

        with (
            patch("app.ai.summaries.compute_graph_hash", return_value="new_hash"),
            patch(
                "app.ai.summaries.assemble_node_context",
                return_value={
                    "node": {"fqn": "com.app.X", "name": "X", "type": "Class"},
                    "callers": [],
                    "callees": [],
                },
            ),
        ):
            result = await get_or_create_summary(
                ctx=ctx,
                node_fqn="com.app.X",
                client=mock_client,
                model="model-1",
                max_tokens=512,
            )
        assert result["cached"] is False
        assert result["summary"] == "Fresh summary"

    @pytest.mark.asyncio
    async def test_missing_node_returns_error(self, ctx):
        mock_session = ctx.db_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with (
            patch("app.ai.summaries.compute_graph_hash", return_value="hash"),
            patch("app.ai.summaries.assemble_node_context", return_value=None),
        ):
            result = await get_or_create_summary(
                ctx=ctx,
                node_fqn="does.not.exist",
                client=AsyncMock(),
                model="model-1",
                max_tokens=512,
            )
        assert "error" in result


from app.ai.tools import get_or_generate_summary as tool_get_or_generate_summary


class TestGetOrGenerateSummaryTool:
    @pytest.mark.asyncio
    async def test_tool_delegates_to_service(self, ctx):
        with patch("app.ai.summaries.get_or_create_summary") as mock_svc:
            mock_svc.return_value = {
                "fqn": "com.app.X",
                "summary": "X does things.",
                "cached": True,
                "model": "model-1",
                "tokens_used": 100,
            }
            result = await tool_get_or_generate_summary(ctx, node_fqn="com.app.X")
            assert result["summary"] == "X does things."
            mock_svc.assert_called_once()


class TestFullFlow:
    @pytest.mark.asyncio
    async def test_miss_then_hit(self, ctx):
        """First call generates, second returns cache."""
        mock_session = ctx.db_session

        mock_result_miss = MagicMock()
        mock_result_miss.scalar_one_or_none.return_value = None

        mock_cached = MagicMock()
        mock_cached.summary = "Generated summary"
        mock_cached.model = "model-1"
        mock_cached.graph_hash = "hash123"
        mock_cached.tokens_used = 500
        mock_result_hit = MagicMock()
        mock_result_hit.scalar_one_or_none.return_value = mock_cached

        mock_session.execute.side_effect = [
            mock_result_miss,
            MagicMock(),
            mock_result_hit,
        ]

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Generated summary")]
        mock_response.usage.input_tokens = 300
        mock_response.usage.output_tokens = 200
        mock_client.messages.create.return_value = mock_response

        with (
            patch("app.ai.summaries.compute_graph_hash", return_value="hash123"),
            patch("app.ai.summaries.assemble_node_context", return_value={
                "node": {"fqn": "com.app.X", "name": "X", "type": "Class"},
                "callers": [], "callees": [],
            }),
        ):
            r1 = await get_or_create_summary(
                ctx=ctx, node_fqn="com.app.X",
                client=mock_client, model="model-1", max_tokens=512,
            )
            assert r1["cached"] is False
            assert mock_client.messages.create.call_count == 1

            r2 = await get_or_create_summary(
                ctx=ctx, node_fqn="com.app.X",
                client=mock_client, model="model-1", max_tokens=512,
            )
            assert r2["cached"] is True
            assert mock_client.messages.create.call_count == 1
