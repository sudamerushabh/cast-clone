"""Tests for summary response schemas."""

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
