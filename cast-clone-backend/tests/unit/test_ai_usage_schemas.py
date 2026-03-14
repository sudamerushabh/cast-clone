"""Unit tests for AI usage response schemas."""
from __future__ import annotations

from datetime import datetime

from app.schemas.ai_usage import (
    UsageLogResponse,
    UsageSummaryResponse,
    UsageBySourceItem,
    UsageByProjectItem,
)


class TestUsageLogResponse:
    def test_from_dict(self):
        resp = UsageLogResponse(
            id="log-1",
            project_id="proj-1",
            user_id="user-1",
            source="chat",
            model="us.anthropic.claude-sonnet-4-6",
            input_tokens=3200,
            output_tokens=850,
            estimated_cost_usd=0.022350,
            created_at=datetime(2026, 3, 13, 10, 0, 0),
        )
        assert resp.source == "chat"
        assert resp.input_tokens == 3200

    def test_nullable_fields(self):
        resp = UsageLogResponse(
            id="log-1",
            project_id="proj-1",
            user_id=None,
            source="mcp",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_usd=None,
            created_at=datetime(2026, 3, 13),
        )
        assert resp.user_id is None
        assert resp.estimated_cost_usd is None


class TestUsageSummaryResponse:
    def test_summary(self):
        resp = UsageSummaryResponse(
            total_input_tokens=100000,
            total_output_tokens=25000,
            total_estimated_cost_usd=1.675,
            by_source=[
                UsageBySourceItem(source="chat", input_tokens=80000, output_tokens=20000, estimated_cost_usd=1.34, count=15),
                UsageBySourceItem(source="summary", input_tokens=20000, output_tokens=5000, estimated_cost_usd=0.335, count=40),
            ],
            by_project=[
                UsageByProjectItem(project_id="p1", project_name="MyApp", input_tokens=100000, output_tokens=25000, estimated_cost_usd=1.675, count=55),
            ],
        )
        assert resp.total_input_tokens == 100000
        assert len(resp.by_source) == 2
        assert len(resp.by_project) == 1


class TestUsageBySourceItem:
    def test_fields(self):
        item = UsageBySourceItem(
            source="pr_analysis",
            input_tokens=50000,
            output_tokens=10000,
            estimated_cost_usd=0.30,
            count=5,
        )
        assert item.source == "pr_analysis"
        assert item.count == 5
