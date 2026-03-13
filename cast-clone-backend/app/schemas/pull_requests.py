"""Pydantic v2 schemas for pull request analysis API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PrChangedNodeResponse(BaseModel):
    """A graph node directly changed in the PR."""

    fqn: str
    name: str
    type: str
    path: str
    line: int
    end_line: int
    language: str
    change_type: str
    fan_in: int = 0
    is_hub: bool = False


class PrAffectedNodeResponse(BaseModel):
    """A graph node affected downstream or upstream."""

    fqn: str
    name: str
    type: str
    file: str
    depth: int


class PrCrossTechResponse(BaseModel):
    """A cross-technology impact entry."""

    kind: str
    name: str
    detail: str


class PrModuleDepResponse(BaseModel):
    """A module-level dependency."""

    from_module: str
    to_module: str


class PrAnalysisResponse(BaseModel):
    """Full PR analysis record."""

    id: str
    repository_id: str
    platform: str
    pr_number: int
    pr_title: str
    pr_description: str | None = None
    pr_author: str
    source_branch: str
    target_branch: str
    commit_sha: str
    pr_url: str | None = None
    status: str
    risk_level: str | None = None
    changed_node_count: int | None = None
    blast_radius_total: int | None = None
    impact_summary: dict | None = None
    drift_report: dict | None = None
    ai_summary: str | None = None
    files_changed: int | None = None
    additions: int | None = None
    deletions: int | None = None
    graph_analysis_run_id: str | None = None
    analysis_duration_ms: int | None = None
    ai_summary_tokens: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PrAnalysisListResponse(BaseModel):
    """Paginated list of PR analyses."""

    items: list[PrAnalysisResponse]
    total: int
    limit: int
    offset: int


class PrImpactResponse(BaseModel):
    """Impact analysis results for a PR."""

    pr_analysis_id: str
    changed_nodes: list[PrChangedNodeResponse]
    downstream_affected: list[PrAffectedNodeResponse]
    upstream_dependents: list[PrAffectedNodeResponse]
    total_blast_radius: int
    by_type: dict[str, int]
    by_depth: dict[int, int]
    by_layer: dict[str, int]
    by_module: dict[str, int]
    cross_tech_impacts: list[PrCrossTechResponse]
    transactions_affected: list[str]


class PrDriftResponse(BaseModel):
    """Drift analysis results for a PR."""

    pr_analysis_id: str
    has_drift: bool
    potential_new_module_deps: list[PrModuleDepResponse]
    circular_deps_affected: list[list[str]]
    new_files_outside_modules: list[str]
