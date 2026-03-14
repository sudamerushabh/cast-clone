"""Tests for summary response schemas."""

from app.models.db import AiSummary
from app.schemas.summaries import SummaryResponse


class TestSummaryResponse:
    def test_cached_response(self):
        resp = SummaryResponse(
            fqn="com.app.OrderService",
            summary="OrderService handles order processing...",
            cached=True,
            model="us.anthropic.claude-sonnet-4-6",
        )
        assert resp.fqn == "com.app.OrderService"
        assert resp.cached is True
        assert resp.model == "us.anthropic.claude-sonnet-4-6"

    def test_generated_response(self):
        resp = SummaryResponse(
            fqn="com.app.OrderService",
            summary="OrderService handles order processing...",
            cached=False,
            model="us.anthropic.claude-sonnet-4-6",
            tokens_used=350,
        )
        assert resp.cached is False
        assert resp.tokens_used == 350

    def test_tokens_used_optional(self):
        resp = SummaryResponse(
            fqn="com.app.X",
            summary="X does things.",
            cached=True,
            model="model-1",
        )
        assert resp.tokens_used is None


class TestAiSummaryModel:
    def test_create_instance(self):
        summary = AiSummary(
            project_id="proj-123",
            node_fqn="com.app.OrderService",
            summary="OrderService handles order processing...",
            model="us.anthropic.claude-sonnet-4-6",
            graph_hash="abc123",
            tokens_used=350,
        )
        assert summary.project_id == "proj-123"
        assert summary.node_fqn == "com.app.OrderService"
        assert summary.summary == "OrderService handles order processing..."
        assert summary.model == "us.anthropic.claude-sonnet-4-6"
        assert summary.graph_hash == "abc123"
        assert summary.tokens_used == 350

    def test_table_name(self):
        assert AiSummary.__tablename__ == "ai_summaries"

    def test_unique_constraint(self):
        constraints = AiSummary.__table_args__
        found = False
        for c in constraints:
            if hasattr(c, "name") and c.name == "uq_summary_project_node":
                found = True
        assert found, "Expected UniqueConstraint 'uq_summary_project_node'"
