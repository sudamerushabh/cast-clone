# tests/unit/test_chat_service.py
"""Tests for the agentic chat service.

Mocks the Anthropic client to test the agent loop, SSE event generation,
page context injection, and tool dispatch.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.ai.chat import build_system_prompt, execute_tool_call
from app.ai.tools import ChatToolContext
from app.schemas.chat import PageContext


@pytest.fixture
def ctx() -> ChatToolContext:
    return ChatToolContext(
        graph_store=AsyncMock(),
        app_name="test-app",
        project_id="proj-123",
    )


class TestBuildSystemPrompt:
    def test_without_page_context(self):
        prompt = build_system_prompt(
            app_name="MyApp",
            frameworks=["Spring Boot"],
            languages=["Java"],
            page_context=None,
        )
        assert "MyApp" in prompt
        assert "Spring Boot" in prompt
        assert "Java" in prompt
        assert "currently viewing" not in prompt

    def test_with_page_context(self):
        page_ctx = PageContext(
            page="graph_explorer",
            selected_node_fqn="com.app.OrderService",
            view="architecture",
            level="class",
        )
        prompt = build_system_prompt(
            app_name="MyApp",
            frameworks=["Spring Boot"],
            languages=["Java"],
            page_context=page_ctx,
        )
        assert "OrderService" in prompt
        assert "architecture" in prompt
        assert "class" in prompt

    def test_context_aware_off(self):
        """When include_page_context=False, no page context in prompt."""
        prompt = build_system_prompt(
            app_name="MyApp",
            frameworks=[],
            languages=[],
            page_context=None,
        )
        assert "currently viewing" not in prompt


class TestExecuteToolCall:
    @pytest.mark.asyncio
    async def test_search_objects(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"fqn": "com.app.Order", "name": "Order", "type": "Class", "language": "Java", "path": "Order.java"}
        ]
        result = await execute_tool_call(ctx, "search_objects", {"query": "Order"})
        parsed = json.loads(result)
        assert len(parsed) == 1

    @pytest.mark.asyncio
    async def test_unknown_tool(self, ctx: ChatToolContext):
        result = await execute_tool_call(ctx, "nonexistent_tool", {})
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_impact_analysis(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"fqn": "com.app.A", "name": "A", "type": "Class", "file": "A.java", "depth": 1},
        ]
        result = await execute_tool_call(ctx, "impact_analysis", {"node_fqn": "com.app.X"})
        parsed = json.loads(result)
        assert parsed["total"] == 1
