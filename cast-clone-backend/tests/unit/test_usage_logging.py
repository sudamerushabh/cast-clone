"""Unit tests for AI usage logging helper."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.usage_logging import log_ai_usage, estimate_cost


class TestEstimateCost:
    def test_basic_cost(self):
        """3.0 per Mtok input + 15.0 per Mtok output."""
        cost = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            input_price_per_mtok=3.0,
            output_price_per_mtok=15.0,
        )
        assert cost == Decimal("18.000000")

    def test_small_usage(self):
        cost = estimate_cost(
            input_tokens=3200,
            output_tokens=850,
            input_price_per_mtok=3.0,
            output_price_per_mtok=15.0,
        )
        # 3200/1M * 3.0 = 0.0096, 850/1M * 15.0 = 0.01275 → total = 0.02235
        expected = Decimal("0.022350")
        assert cost == expected

    def test_zero_tokens(self):
        cost = estimate_cost(0, 0, 3.0, 15.0)
        assert cost == Decimal("0.000000")


class TestLogAiUsage:
    @pytest.mark.asyncio
    async def test_creates_log_entry(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        await log_ai_usage(
            session=mock_session,
            project_id="proj-123",
            user_id="user-456",
            source="chat",
            model="us.anthropic.claude-sonnet-4-6",
            input_tokens=3200,
            output_tokens=850,
        )

        mock_session.add.assert_called_once()
        log_entry = mock_session.add.call_args[0][0]
        assert log_entry.project_id == "proj-123"
        assert log_entry.source == "chat"
        assert log_entry.input_tokens == 3200
        assert log_entry.output_tokens == 850
        assert log_entry.estimated_cost_usd is not None
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_no_user_id(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        await log_ai_usage(
            session=mock_session,
            project_id="proj-123",
            user_id=None,
            source="mcp",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
        )

        log_entry = mock_session.add.call_args[0][0]
        assert log_entry.user_id is None

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self):
        """Usage logging should never break the main flow."""
        mock_session = AsyncMock()
        mock_session.commit.side_effect = Exception("DB error")

        # Should not raise
        await log_ai_usage(
            session=mock_session,
            project_id="proj-123",
            user_id="user-1",
            source="chat",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
        )
