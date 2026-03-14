"""Unit tests for the AiUsageLog ORM model."""
from __future__ import annotations

from decimal import Decimal

from app.models.db import AiUsageLog


class TestAiUsageLogModel:
    def test_create_instance(self):
        log = AiUsageLog(
            project_id="proj-123",
            user_id="user-456",
            source="chat",
            model="us.anthropic.claude-sonnet-4-6",
            input_tokens=3200,
            output_tokens=850,
            estimated_cost_usd=Decimal("0.022350"),
        )
        assert log.project_id == "proj-123"
        assert log.user_id == "user-456"
        assert log.source == "chat"
        assert log.model == "us.anthropic.claude-sonnet-4-6"
        assert log.input_tokens == 3200
        assert log.output_tokens == 850
        assert log.estimated_cost_usd == Decimal("0.022350")

    def test_tablename(self):
        assert AiUsageLog.__tablename__ == "ai_usage_log"

    def test_default_id_generated(self):
        log = AiUsageLog(
            project_id="p1",
            source="summary",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
        )
        assert log.id is not None
        assert len(log.id) == 36  # UUID format

    def test_nullable_user_id(self):
        """MCP calls may not have a user_id."""
        log = AiUsageLog(
            project_id="p1",
            source="mcp",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
        )
        assert log.user_id is None

    def test_nullable_estimated_cost(self):
        log = AiUsageLog(
            project_id="p1",
            source="chat",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
        )
        assert log.estimated_cost_usd is None
