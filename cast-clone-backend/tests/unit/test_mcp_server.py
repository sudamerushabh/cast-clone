"""Tests for the MCP server tool registration and context construction.

Tests that all tools are registered and that multi-project context
is handled correctly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class TestMcpToolRegistration:
    def test_all_tools_registered(self):
        """Verify all shared tools are exposed via MCP."""
        from app.mcp.server import mcp

        # FastMCP stores tools internally; list them
        tool_names = set(mcp._tool_manager._tools.keys())

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
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"

    def test_tool_count(self):
        """Verify the expected number of tools are registered."""
        from app.mcp.server import mcp

        tool_names = set(mcp._tool_manager._tools.keys())
        assert len(tool_names) >= 10


class TestMcpContextConstruction:
    @pytest.mark.asyncio
    async def test_project_agnostic_tool(self):
        """list_applications should work without app_name."""
        from app.ai.tools import ChatToolContext

        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {"name": "app1", "module_count": 5},
        ]
        ctx = ChatToolContext(
            graph_store=mock_store,
            app_name="",
            project_id="",
        )
        from app.ai.tools import list_applications

        result = await list_applications(ctx)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_project_specific_tool(self):
        """impact_analysis requires app_name in context."""
        from app.ai.tools import ChatToolContext, impact_analysis

        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "fqn": "com.app.A",
                "name": "A",
                "type": "Class",
                "file": "A.java",
                "depth": 1,
            },
        ]
        ctx = ChatToolContext(
            graph_store=mock_store,
            app_name="my-app",
            project_id="proj-1",
        )
        result = await impact_analysis(ctx, node_fqn="com.app.X")
        assert result["total"] == 1
        # Verify app_name was passed to the query
        call_args = mock_store.query.call_args
        assert "my-app" in str(call_args)
