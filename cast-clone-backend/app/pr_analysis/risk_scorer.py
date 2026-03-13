"""Risk classification for PR impact analysis."""

from __future__ import annotations

from app.pr_analysis.models import AggregatedImpact


def classify_risk(impact: AggregatedImpact) -> str:
    """Classify PR risk as High, Medium, or Low based on impact factors."""
    score = 0

    # Blast radius size
    if impact.total_blast_radius > 50:
        score += 3
    elif impact.total_blast_radius > 20:
        score += 2
    elif impact.total_blast_radius > 5:
        score += 1

    # Hub node changed
    if any(n.is_hub for n in impact.changed_nodes):
        score += 3

    # Cross-tech impact
    cross_tech_count = len(impact.cross_tech_impacts)
    if cross_tech_count > 3:
        score += 2
    elif cross_tech_count > 0:
        score += 1

    # Fan-in of changed nodes
    max_fan_in = max((n.fan_in for n in impact.changed_nodes), default=0)
    if max_fan_in > 15:
        score += 2
    elif max_fan_in > 5:
        score += 1

    # Layer span
    if len(impact.by_layer) >= 3:
        score += 1

    # Classify
    if score >= 7:
        return "High"
    elif score >= 3:
        return "Medium"
    else:
        return "Low"
