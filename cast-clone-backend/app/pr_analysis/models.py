"""Data models for PR analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GitPlatform(str, Enum):
    """Supported Git hosting platforms."""

    github = "github"
    gitlab = "gitlab"
    bitbucket = "bitbucket"
    gitea = "gitea"


@dataclass
class DiffHunk:
    """A single hunk from a unified diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int

    @property
    def new_end(self) -> int:
        """Return the last line number in the new file covered by this hunk."""
        return self.new_start + self.new_count - 1


@dataclass
class FileDiff:
    """Diff information for a single file."""

    path: str
    status: str  # added, modified, deleted, renamed
    old_path: str | None
    additions: int
    deletions: int
    hunks: list[DiffHunk]


@dataclass
class PRDiff:
    """Aggregated diff for an entire pull request."""

    files: list[FileDiff]
    total_additions: int
    total_deletions: int
    total_files_changed: int


@dataclass
class PullRequestEvent:
    """Incoming pull request event from a webhook or polling."""

    platform: GitPlatform
    repo_url: str
    pr_number: int
    pr_title: str
    pr_description: str | None
    author: str
    source_branch: str
    target_branch: str
    action: str  # opened, synchronize, closed, etc.
    commit_sha: str
    created_at: str
    raw_payload: dict = field(default_factory=dict)


@dataclass
class ChangedNode:
    """A graph node that was directly changed in the PR."""

    fqn: str
    name: str
    type: str  # class, method, function, etc.
    path: str
    line: int
    end_line: int
    language: str
    change_type: str  # added, modified, deleted
    fan_in: int = 0
    is_hub: bool = False


@dataclass
class AffectedNode:
    """A graph node affected by the PR via dependency relationships."""

    fqn: str
    name: str
    type: str
    file: str
    depth: int


@dataclass
class CrossTechImpact:
    """Cross-technology impact detected (e.g., API endpoint -> frontend call)."""

    kind: str  # api_endpoint, message_queue, database_table, etc.
    name: str
    detail: str


@dataclass
class ModuleDependency:
    """A module-level dependency relationship."""

    from_module: str
    to_module: str


@dataclass
class AggregatedImpact:
    """Full impact analysis results for a PR."""

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
    """Architecture drift analysis for a PR."""

    potential_new_module_deps: list[ModuleDependency]
    circular_deps_affected: list[list[str]]
    new_files_outside_modules: list[str]

    @property
    def has_drift(self) -> bool:
        """Return True if any drift was detected."""
        return bool(
            self.potential_new_module_deps
            or self.circular_deps_affected
            or self.new_files_outside_modules
        )
