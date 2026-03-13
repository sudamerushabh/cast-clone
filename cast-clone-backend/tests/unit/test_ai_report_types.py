"""Tests for AI agent pipeline report types."""

from __future__ import annotations

from app.pr_analysis.ai.report_types import (
    AgentReport,
    CodeChangeReport,
    SummaryResult,
    parse_agent_response,
)


class TestSummaryResult:
    def test_defaults(self) -> None:
        r = SummaryResult(summary="All good", tokens_used=100)
        assert r.summary == "All good"
        assert r.tokens_used == 100
        assert r.agents_run == 0
        assert r.agents_failed == 0
        assert r.total_duration_ms == 0

    def test_custom_values(self) -> None:
        r = SummaryResult(
            summary="Done",
            tokens_used=500,
            agents_run=5,
            agents_failed=1,
            total_duration_ms=12345,
        )
        assert r.agents_run == 5
        assert r.agents_failed == 1
        assert r.total_duration_ms == 12345


class TestAgentReport:
    def test_defaults(self) -> None:
        r = AgentReport(role="code", raw_text="hello")
        assert r.role == "code"
        assert r.parsed is None
        assert r.parse_failed is False

    def test_with_parsed(self) -> None:
        r = AgentReport(role="infra", raw_text="...", parsed={"key": "val"})
        assert r.parsed == {"key": "val"}


class TestParseAgentResponse:
    def test_json_block_in_text(self) -> None:
        text = 'Here is my analysis:\n{"risk": "low", "summary": "ok"}\nDone.'
        report = parse_agent_response("code", text)
        assert report.parsed is not None
        assert report.parsed["risk"] == "low"
        assert report.parse_failed is False

    def test_raw_json(self) -> None:
        text = '{"files": ["a.py"], "count": 1}'
        report = parse_agent_response("code", text)
        assert report.parsed is not None
        assert report.parsed["files"] == ["a.py"]
        assert report.parse_failed is False

    def test_invalid_json(self) -> None:
        text = "This is just plain text with no JSON."
        report = parse_agent_response("code", text)
        assert report.parsed is None
        assert report.parse_failed is True
        assert report.raw_text == text

    def test_last_block_wins(self) -> None:
        text = (
            'First block: {"order": 1}\n'
            'Second block: {"order": 2}\n'
        )
        report = parse_agent_response("code", text)
        assert report.parsed is not None
        assert report.parsed["order"] == 2

    def test_nested_json(self) -> None:
        text = 'Result: {"outer": {"inner": "val"}}'
        report = parse_agent_response("code", text)
        assert report.parsed is not None
        assert report.parsed["outer"] == {"inner": "val"}


class TestCodeChangeReport:
    def test_defaults(self) -> None:
        r = CodeChangeReport()
        assert r.files_analyzed == []
        assert r.functions_changed == []
        assert r.risk_factors == []
        assert r.summary == ""

    def test_custom(self) -> None:
        r = CodeChangeReport(
            files_analyzed=["a.py"],
            summary="Changed a function",
        )
        assert r.files_analyzed == ["a.py"]
        assert r.summary == "Changed a function"
