"""Tests for PR risk classification."""

from __future__ import annotations

import pytest

from app.pr_analysis.models import (
    AggregatedImpact,
    ChangedNode,
    CrossTechImpact,
)
from app.pr_analysis.risk_scorer import classify_risk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(fan_in: int = 0, is_hub: bool = False) -> ChangedNode:
    return ChangedNode(
        fqn="com.app.Svc.method",
        name="method",
        type="Function",
        path="Svc.java",
        line=1,
        end_line=10,
        language="java",
        change_type="modified",
        fan_in=fan_in,
        is_hub=is_hub,
    )


def _make_impact(
    blast_radius: int = 0,
    changed_nodes: list[ChangedNode] | None = None,
    cross_tech_count: int = 0,
    layer_count: int = 1,
) -> AggregatedImpact:
    nodes = changed_nodes or []
    return AggregatedImpact(
        changed_nodes=nodes,
        downstream_affected=[],
        upstream_dependents=[],
        total_blast_radius=blast_radius,
        by_type={},
        by_depth={},
        by_layer={f"Layer{i}": 1 for i in range(layer_count)},
        by_module={},
        cross_tech_impacts=[
            CrossTechImpact(kind="api", name=f"ep{i}", detail="GET /x")
            for i in range(cross_tech_count)
        ],
        transactions_affected=[],
    )


# ---------------------------------------------------------------------------
# Low risk
# ---------------------------------------------------------------------------


class TestLowRisk:
    def test_tiny_blast_radius(self) -> None:
        impact = _make_impact(blast_radius=2)
        assert classify_risk(impact) == "Low"

    def test_small_blast_radius(self) -> None:
        impact = _make_impact(blast_radius=4)
        assert classify_risk(impact) == "Low"

    def test_empty_impact(self) -> None:
        impact = _make_impact()
        assert classify_risk(impact) == "Low"


# ---------------------------------------------------------------------------
# Medium risk
# ---------------------------------------------------------------------------


class TestMediumRisk:
    def test_moderate_blast_radius(self) -> None:
        """blast_radius=10 -> score 1 (>5), not enough alone; add cross_tech."""
        impact = _make_impact(blast_radius=10, cross_tech_count=2)
        # score: 1 (blast) + 1 (cross_tech) = 2 -> still Low
        # Need score >= 3 for Medium, so add fan_in
        impact_with_fan = _make_impact(
            blast_radius=10,
            cross_tech_count=2,
            changed_nodes=[_make_node(fan_in=10)],
        )
        # score: 1 (blast) + 1 (cross_tech) + 1 (fan_in>5) = 3 -> Medium
        assert classify_risk(impact_with_fan) == "Medium"

    def test_cross_tech_with_blast(self) -> None:
        impact = _make_impact(blast_radius=6, cross_tech_count=2)
        # score: 1 (blast>5) + 1 (cross_tech>0) = 2 -> Low
        # Add another factor to push to Medium
        impact = _make_impact(
            blast_radius=6,
            cross_tech_count=2,
            changed_nodes=[_make_node(fan_in=6)],
        )
        # score: 1 + 1 + 1 = 3 -> Medium
        assert classify_risk(impact) == "Medium"

    def test_high_fan_in(self) -> None:
        """fan_in=10 gives +1, combined with blast_radius>5 and cross_tech."""
        impact = _make_impact(
            blast_radius=10,
            changed_nodes=[_make_node(fan_in=10)],
            cross_tech_count=1,
        )
        # score: 1 (blast) + 1 (cross_tech) + 1 (fan_in) = 3 -> Medium
        assert classify_risk(impact) == "Medium"


# ---------------------------------------------------------------------------
# High risk
# ---------------------------------------------------------------------------


class TestHighRisk:
    def test_hub_node_changed(self) -> None:
        """Hub node alone gives +3, add blast>50 for +3, total=6 -> not quite.
        Add layer_count>=3 for +1 -> 7 -> High."""
        impact = _make_impact(
            blast_radius=55,
            changed_nodes=[_make_node(is_hub=True)],
            layer_count=3,
        )
        # score: 3 (blast>50) + 3 (hub) + 1 (layers>=3) = 7 -> High
        assert classify_risk(impact) == "High"

    def test_large_blast_plus_cross_tech(self) -> None:
        impact = _make_impact(
            blast_radius=55,
            changed_nodes=[_make_node(fan_in=20)],
            cross_tech_count=4,
            layer_count=3,
        )
        # score: 3 (blast>50) + 2 (cross_tech>3) + 2 (fan_in>15) + 1 (layers) = 8
        assert classify_risk(impact) == "High"

    def test_many_factors_combined(self) -> None:
        impact = _make_impact(
            blast_radius=60,
            changed_nodes=[_make_node(fan_in=20, is_hub=True)],
            cross_tech_count=5,
            layer_count=4,
        )
        # score: 3 + 3 + 2 + 2 + 1 = 11 -> High
        assert classify_risk(impact) == "High"


# ---------------------------------------------------------------------------
# Boundary tests
# ---------------------------------------------------------------------------


class TestBoundary:
    def test_score_exactly_3_is_medium(self) -> None:
        """blast_radius=6 (+1), cross_tech=1 (+1), fan_in=6 (+1) => score=3 -> Medium."""
        impact = _make_impact(
            blast_radius=6,
            cross_tech_count=1,
            changed_nodes=[_make_node(fan_in=6)],
        )
        assert classify_risk(impact) == "Medium"

    def test_score_exactly_7_is_high(self) -> None:
        """hub (+3), blast>50 (+3), layer>=3 (+1) => score=7 -> High."""
        impact = _make_impact(
            blast_radius=55,
            changed_nodes=[_make_node(is_hub=True)],
            layer_count=3,
        )
        assert classify_risk(impact) == "High"

    def test_score_2_is_low(self) -> None:
        """blast_radius=25 (+2) => score=2 -> Low."""
        impact = _make_impact(blast_radius=25)
        assert classify_risk(impact) == "Low"

    def test_score_6_is_medium(self) -> None:
        """hub (+3) + blast>50 (+3) = 6 -> Medium (not High)."""
        impact = _make_impact(
            blast_radius=55,
            changed_nodes=[_make_node(is_hub=True)],
        )
        assert classify_risk(impact) == "Medium"
