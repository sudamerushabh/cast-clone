# tests/unit/test_chat_tools.py
"""Unit tests for the shared AI tool layer.

All tests mock GraphStore — no Neo4j needed.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.ai.tools import (
    ChatToolContext,
    list_applications,
    application_stats,
    search_objects,
    object_details,
    impact_analysis,
    find_path,
    list_transactions,
    get_source_code,
    get_architecture,
)


@pytest.fixture
def mock_graph_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def ctx(mock_graph_store: AsyncMock) -> ChatToolContext:
    return ChatToolContext(
        graph_store=mock_graph_store,
        app_name="test-app",
        project_id="proj-123",
    )


class TestListApplications:
    @pytest.mark.asyncio
    async def test_returns_apps(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"name": "app1", "languages": ["Java"], "total_loc": 5000},
            {"name": "app2", "languages": ["Python"], "total_loc": 3000},
        ]
        result = await list_applications(ctx)
        assert len(result) == 2
        assert result[0]["name"] == "app1"

    @pytest.mark.asyncio
    async def test_empty(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = []
        result = await list_applications(ctx)
        assert result == []


class TestSearchObjects:
    @pytest.mark.asyncio
    async def test_search_by_name(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"fqn": "com.app.OrderService", "name": "OrderService", "type": "Class"},
        ]
        result = await search_objects(ctx, query="Order")
        assert len(result) == 1
        assert result[0]["fqn"] == "com.app.OrderService"

    @pytest.mark.asyncio
    async def test_search_with_type_filter(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = []
        result = await search_objects(ctx, query="Order", type_filter="Function")
        call_args = ctx.graph_store.query.call_args
        assert "type_filter" in call_args[1] or "Function" in str(call_args)


class TestObjectDetails:
    @pytest.mark.asyncio
    async def test_found(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = {
            "fqn": "com.app.OrderService",
            "name": "OrderService",
            "type": "Class",
            "language": "Java",
            "path": "src/OrderService.java",
            "line": 10,
            "end_line": 100,
            "loc": 90,
        }
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.Caller", "name": "Caller", "type": "Class"}],  # callers
            [{"fqn": "com.app.Callee", "name": "Callee", "type": "Class"}],  # callees
        ]
        result = await object_details(ctx, node_fqn="com.app.OrderService")
        assert result["node"]["fqn"] == "com.app.OrderService"
        assert len(result["callers"]) == 1
        assert len(result["callees"]) == 1
        assert result["node"]["fan_in"] == 1
        assert result["node"]["fan_out"] == 1

    @pytest.mark.asyncio
    async def test_not_found(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = None
        result = await object_details(ctx, node_fqn="does.not.exist")
        assert result["node"] is None


class TestImpactAnalysis:
    @pytest.mark.asyncio
    async def test_downstream(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {
                "fqn": "com.app.A",
                "name": "A",
                "type": "Class",
                "file": "A.java",
                "depth": 1,
            },
            {
                "fqn": "com.app.B",
                "name": "B",
                "type": "Function",
                "file": "B.java",
                "depth": 2,
            },
        ]
        result = await impact_analysis(
            ctx, node_fqn="com.app.X", direction="downstream", depth=5
        )
        assert result["total"] == 2
        assert result["by_type"] == {"Class": 1, "Function": 1}

    @pytest.mark.asyncio
    async def test_depth_rejected_above_cap(self, ctx: ChatToolContext):
        # Task 13 / CHAN-67: depth above the cap now raises instead of
        # being silently clamped, to prevent Cypher injection via unvalidated
        # interpolation and to surface caller bugs loudly.
        ctx.graph_store.query.return_value = []
        with pytest.raises(ValueError, match="between 1 and 5"):
            await impact_analysis(
                ctx, node_fqn="com.app.X", direction="downstream", depth=20
            )


class TestFindPath:
    @pytest.mark.asyncio
    async def test_path_found(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {
                "nodes": [
                    {"fqn": "A", "name": "A", "type": "Class"},
                    {"fqn": "B", "name": "B", "type": "Class"},
                ],
                "edges": [{"type": "CALLS", "source": "A", "target": "B"}],
                "path_length": 1,
            }
        ]
        result = await find_path(ctx, from_fqn="A", to_fqn="B")
        assert result["path_length"] == 1

    @pytest.mark.asyncio
    async def test_no_path(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = []
        result = await find_path(ctx, from_fqn="A", to_fqn="Z")
        assert result["path_length"] == 0


class TestGetSourceCode:
    @pytest.mark.asyncio
    async def test_node_found_with_repo(self, ctx: ChatToolContext, tmp_path):
        src = tmp_path / "src" / "OrderService.java"
        src.parent.mkdir(parents=True)
        src.write_text("line1\nline2\nline3\nline4\nline5\n")

        ctx.repo_path = str(tmp_path)
        ctx.graph_store.query_single.return_value = {
            "path": "src/OrderService.java",
            "line": 2,
            "end_line": 4,
        }
        result = await get_source_code(ctx, node_fqn="com.app.OrderService")
        assert result["fqn"] == "com.app.OrderService"
        assert "line2" in result["code"]
        assert "line4" in result["code"]

    @pytest.mark.asyncio
    async def test_node_not_found(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = None
        result = await get_source_code(ctx, node_fqn="does.not.exist")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_repo_path(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = {
            "path": "src/OrderService.java",
            "line": 2,
            "end_line": 4,
        }
        result = await get_source_code(ctx, node_fqn="com.app.OrderService")
        assert result["fqn"] == "com.app.OrderService"
        assert result.get("code") is None


class TestApplicationStats:
    @pytest.mark.asyncio
    async def test_returns_stats(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"type": "Class", "count": 10, "total_loc": 5000},
            {"type": "Function", "count": 50, "total_loc": 3000},
        ]
        result = await application_stats(ctx)
        assert result["app_name"] == "test-app"
        assert result["by_type"]["Class"] == 10
        assert result["total_loc"] == 8000


class TestGetArchitecture:
    @pytest.mark.asyncio
    async def test_module_level(self, ctx: ChatToolContext):
        ctx.graph_store.query.side_effect = [
            [
                {
                    "fqn": "com.app.orders",
                    "name": "orders",
                    "type": "Module",
                    "loc": 1000,
                }
            ],
            [
                {
                    "source": "com.app.orders",
                    "target": "com.app.billing",
                    "kind": "IMPORTS",
                    "weight": 3,
                }
            ],
        ]
        result = await get_architecture(ctx, level="module")
        assert len(result["nodes"]) == 1
        assert len(result["edges"]) == 1


class TestTransactionGraph:
    @pytest.mark.asyncio
    async def test_returns_graph(self, ctx: ChatToolContext):
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.A", "name": "A", "type": "Function", "path": "A.java"}],
            [{"source": "com.app.A", "target": "com.app.B", "kind": "CALLS"}],
        ]
        from app.ai.tools import transaction_graph

        result = await transaction_graph(ctx, transaction_name="POST /orders")
        assert len(result["nodes"]) == 1
        assert len(result["edges"]) == 1


class TestListTransactions:
    @pytest.mark.asyncio
    async def test_returns_transactions(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {
                "name": "POST /orders",
                "http_method": "POST",
                "url_path": "/orders",
                "node_count": 12,
                "depth": 5,
            },
        ]
        result = await list_transactions(ctx)
        assert len(result) == 1
        assert result[0]["name"] == "POST /orders"


from app.ai.tool_definitions import get_chat_tool_definitions


class TestToolDefinitions:
    def test_all_tools_present(self):
        defs = get_chat_tool_definitions()
        names = {d["name"] for d in defs}
        expected = {
            "list_applications",
            "application_stats",
            "get_architecture",
            "search_objects",
            "object_details",
            "impact_analysis",
            "find_path",
            "list_transactions",
            "transaction_graph",
            "get_source_code",
        }
        assert expected.issubset(names)

    def test_each_has_input_schema(self):
        for tool in get_chat_tool_definitions():
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_each_has_description(self):
        for tool in get_chat_tool_definitions():
            assert "description" in tool
            assert len(tool["description"]) > 10
