"""Integration-style tests for MCP server components."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mcp.auth import ApiKeyAuthenticator, hash_api_key, generate_api_key


class TestEndToEndKeyAuth:
    @pytest.mark.asyncio
    async def test_create_and_verify_key(self):
        """Simulate creating and verifying a key."""
        raw_key = generate_api_key()
        key_hash = hash_api_key(raw_key)

        mock_key = MagicMock()
        mock_key.id = "key-123"
        mock_key.key_hash = key_hash
        mock_key.is_active = True
        mock_key.user_id = "user-456"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_key
        mock_session.execute.return_value = mock_result

        session_ctx = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        auth = ApiKeyAuthenticator(
            session_factory=lambda: session_ctx,
            cache_ttl_seconds=300,
            batch_update_seconds=60,
        )

        result = await auth.verify_key(raw_key)
        assert result is not None
        assert result["key_id"] == "key-123"

        result2 = await auth.verify_key(raw_key)
        assert result2 is not None
        assert mock_session.execute.call_count == 1


class TestToolDispatchWithContext:
    @pytest.mark.asyncio
    async def test_mcp_tool_uses_shared_layer(self):
        from app.ai.tools import ChatToolContext, search_objects

        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {"fqn": "com.app.OrderService", "name": "OrderService",
             "type": "Class", "language": "Java", "path": "Order.java"},
        ]

        ctx = ChatToolContext(
            graph_store=mock_store,
            app_name="test-app",
            project_id="proj-1",
        )

        result = await search_objects(ctx, query="Order")
        assert len(result) == 1
        assert result[0]["fqn"] == "com.app.OrderService"

        call_args = mock_store.query.call_args
        # query(cypher, params) — params is positional arg index 1
        positional = call_args[0]
        params = positional[1] if len(positional) > 1 else call_args[1]
        assert params.get("app_name") == "test-app"
