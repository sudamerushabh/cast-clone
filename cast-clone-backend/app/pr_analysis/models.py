"""Data models for PR analysis pipeline.

These are internal dataclasses used throughout the analysis pipeline.
They are NOT Pydantic models — Pydantic schemas for API boundaries
are in app/schemas/pull_requests.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GitPlatform(str, Enum):
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    GITEA = "gitea"


@dataclass
class DiffHunk:
    """A contiguous block of changes within a file."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int

    @property
    def new_end(self) -> int:
        return self.new_start + self.new_count - 1


@dataclass
class FileDiff:
    """A single file's diff within a PR."""
    path: str
    status: str  # "added", "modified", "deleted", "renamed"
    old_path: str | None
    additions: int
    deletions: int
    hunks: list[DiffHunk]


@dataclass
class PRDiff:
    """Full diff for a pull request."""
    files: list[FileDiff]
    total_additions: int
    total_deletions: int
    total_files_changed: int


@dataclass
class PullRequestEvent:
    """Normalized PR event — same structure regardless of Git platform."""
    platform: GitPlatform
    repo_url: str
    pr_number: int
    pr_title: str
    pr_description: str
    author: str
    source_branch: str
    target_branch: str
    action: str  # "opened", "updated", "closed", "merged"
    commit_sha: str
    created_at: str
    raw_payload: dict = field(default_factory=dict)


@dataclass
class ChangedNode:
    """A graph node directly modified by the PR."""
    fqn: str
    name: str
    type: str
    path: str
    line: int
    end_line: int
    language: str | None
    change_type: str  # "modified", "deleted", "renamed"
    fan_in: int = 0
    is_hub: bool = False


@dataclass
class AffectedNode:
    """A graph node in the blast radius (not directly changed)."""
    fqn: str
    name: str
    type: str
    file: str | None
    depth: int


@dataclass
class CrossTechImpact:
    """A cross-technology impact (API endpoint, MQ topic, DB table)."""
    kind: str  # "api_endpoint", "message_topic", "database_table"
    name: str
    detail: str  # e.g. "GET /api/orders", "READS orders"


@dataclass
class ModuleDependency:
    """A module-to-module dependency edge."""
    from_module: str
    to_module: str


@dataclass
class AggregatedImpact:
    """Combined impact across all changed nodes in a PR."""
    changed_nodes: list[ChangedNode]
    downstream_affected: list[AffectedNode]
    upstream_dependents: list[AffectedNode]
    total_blast_radius: int
    by_type: dict[str, int]
    by_depth: dict[int, int]
    by_layer: dict[str, int]
    by_module: dict[str, int]
    cross_tech_impacts: list[CrossTechImpact]
    transactions_affected: list[str]


@dataclass
class DriftReport:
    """Architecture drift detected in a PR."""
    potential_new_module_deps: list[ModuleDependency]
    circular_deps_affected: list[list[str]]
    new_files_outside_modules: list[str]

    @property
    def has_drift(self) -> bool:
        return bool(
            self.potential_new_module_deps
            or self.circular_deps_affected
            or self.new_files_outside_modules
        )
