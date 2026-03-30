"""Tests for PR comment markdown formatter."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.pr_analysis.comment_formatter import format_pr_comment


def _make_pr_record(
    risk_level: str = "Medium",
    blast_radius: int = 20,
    files_changed: int = 5,
    additions: int = 100,
    deletions: int = 30,
    changed_node_count: int = 3,
    impact_summary: dict | None = None,
    drift_report: dict | None = None,
    ai_summary: str | None = "This PR modifies the order processing pipeline.",
    pr_number: int = 42,
    repository_id: str = "repo-1",
    id: str = "analysis-1",
) -> MagicMock:
    record = MagicMock()
    record.id = id
    record.repository_id = repository_id
    record.pr_number = pr_number
    record.risk_level = risk_level
    record.blast_radius_total = blast_radius
    record.files_changed = files_changed
    record.additions = additions
    record.deletions = deletions
    record.changed_node_count = changed_node_count
    record.ai_summary = ai_summary
    record.impact_summary = impact_summary or {
        "total_blast_radius": blast_radius,
        "by_type": {"Class": 2, "Function": 10},
        "downstream_count": 15,
        "upstream_count": 5,
        "cross_tech": [],
        "transactions_affected": [],
    }
    record.drift_report = drift_report or {"has_drift": False}
    return record


class TestFormatPrComment:
    def test_contains_risk_level(self):
        record = _make_pr_record(risk_level="High")
        result = format_pr_comment(record)
        assert "High" in result

    def test_contains_blast_radius(self):
        record = _make_pr_record(blast_radius=45)
        result = format_pr_comment(record)
        assert "45" in result

    def test_contains_file_stats(self):
        record = _make_pr_record(files_changed=12, additions=340, deletions=89)
        result = format_pr_comment(record)
        assert "12" in result
        assert "+340" in result
        assert "-89" in result

    def test_contains_ai_summary(self):
        record = _make_pr_record(ai_summary="The order service was refactored.")
        result = format_pr_comment(record)
        assert "The order service was refactored." in result

    def test_no_ai_section_when_empty(self):
        record = _make_pr_record(ai_summary=None)
        result = format_pr_comment(record)
        assert "AI Analysis" not in result

    def test_no_drift_section_when_no_drift(self):
        record = _make_pr_record(drift_report={"has_drift": False})
        result = format_pr_comment(record)
        assert "Architecture Drift" not in result

    def test_drift_section_shown_when_drift(self):
        record = _make_pr_record(drift_report={
            "has_drift": True,
            "potential_new_module_deps": [
                {"from_module": "api", "to_module": "database"}
            ],
            "circular_deps_affected": [["a", "b", "a"]],
            "new_files_outside_modules": [],
        })
        result = format_pr_comment(record)
        assert "Architecture Drift" in result
        assert "api" in result
        assert "database" in result

    def test_no_cross_tech_section_when_empty(self):
        record = _make_pr_record(impact_summary={
            "total_blast_radius": 5,
            "by_type": {},
            "downstream_count": 3,
            "upstream_count": 2,
            "cross_tech": [],
            "transactions_affected": [],
        })
        result = format_pr_comment(record)
        assert "Cross-Technology" not in result

    def test_cross_tech_section_shown(self):
        record = _make_pr_record(impact_summary={
            "total_blast_radius": 5,
            "by_type": {},
            "downstream_count": 3,
            "upstream_count": 2,
            "cross_tech": [
                {"kind": "api_endpoint", "name": "POST /orders", "detail": "used by OrderService"}
            ],
            "transactions_affected": ["CreateOrder"],
        })
        result = format_pr_comment(record)
        assert "Cross-Technology" in result
        assert "POST /orders" in result

    def test_transactions_shown(self):
        record = _make_pr_record(impact_summary={
            "total_blast_radius": 5,
            "by_type": {},
            "downstream_count": 3,
            "upstream_count": 2,
            "cross_tech": [],
            "transactions_affected": ["CreateOrder", "ProcessPayment"],
        })
        result = format_pr_comment(record)
        assert "CreateOrder" in result
        assert "ProcessPayment" in result

    def test_footer_link_with_base_url(self):
        record = _make_pr_record()
        result = format_pr_comment(record, base_url="https://codelens.example.com")
        assert "https://codelens.example.com" in result

    def test_no_footer_link_without_base_url(self):
        record = _make_pr_record()
        result = format_pr_comment(record)
        assert "View full analysis" not in result

    def test_risk_emoji_high(self):
        record = _make_pr_record(risk_level="High")
        result = format_pr_comment(record)
        assert "\U0001f534" in result  # red circle

    def test_risk_emoji_medium(self):
        record = _make_pr_record(risk_level="Medium")
        result = format_pr_comment(record)
        assert "\U0001f7e1" in result  # yellow circle

    def test_risk_emoji_low(self):
        record = _make_pr_record(risk_level="Low")
        result = format_pr_comment(record)
        assert "\U0001f7e2" in result  # green circle
