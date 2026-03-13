"""Tests for Phase 5a PR analysis data models."""
import pytest

from app.pr_analysis.models import (
    DiffHunk,
    FileDiff,
    PRDiff,
    PullRequestEvent,
    GitPlatform,
    ChangedNode,
    AffectedNode,
    CrossTechImpact,
    AggregatedImpact,
    DriftReport,
    ModuleDependency,
)


class TestGitPlatform:
    def test_enum_values(self):
        assert GitPlatform.GITHUB == "github"
        assert GitPlatform.GITLAB == "gitlab"
        assert GitPlatform.BITBUCKET == "bitbucket"
        assert GitPlatform.GITEA == "gitea"


class TestDiffHunk:
    def test_creation(self):
        h = DiffHunk(old_start=10, old_count=5, new_start=10, new_count=8)
        assert h.old_start == 10
        assert h.new_count == 8

    def test_new_end(self):
        h = DiffHunk(old_start=10, old_count=5, new_start=20, new_count=10)
        assert h.new_end == 29  # 20 + 10 - 1


class TestFileDiff:
    def test_creation(self):
        f = FileDiff(
            path="src/main/java/App.java",
            status="modified",
            old_path=None,
            additions=5,
            deletions=2,
            hunks=[DiffHunk(old_start=1, old_count=3, new_start=1, new_count=6)],
        )
        assert f.path == "src/main/java/App.java"
        assert len(f.hunks) == 1

    def test_renamed_file(self):
        f = FileDiff(
            path="new/path.java",
            status="renamed",
            old_path="old/path.java",
            additions=0,
            deletions=0,
            hunks=[],
        )
        assert f.old_path == "old/path.java"


class TestPRDiff:
    def test_creation(self):
        d = PRDiff(
            files=[],
            total_additions=10,
            total_deletions=5,
            total_files_changed=3,
        )
        assert d.total_files_changed == 3


class TestPullRequestEvent:
    def test_creation(self):
        ev = PullRequestEvent(
            platform=GitPlatform.GITHUB,
            repo_url="https://github.com/org/repo",
            pr_number=42,
            pr_title="Fix order processing",
            pr_description="Fixes #123",
            author="alice",
            source_branch="fix/order-bug",
            target_branch="main",
            action="opened",
            commit_sha="abc123def456",
            created_at="2026-03-13T10:00:00Z",
        )
        assert ev.pr_number == 42
        assert ev.platform == GitPlatform.GITHUB
        assert ev.raw_payload == {}


class TestChangedNode:
    def test_creation(self):
        n = ChangedNode(
            fqn="com.app.OrderService.createOrder",
            name="createOrder",
            type="Function",
            path="src/main/java/com/app/OrderService.java",
            line=45,
            end_line=80,
            language="java",
            change_type="modified",
            fan_in=12,
            is_hub=True,
        )
        assert n.is_hub is True
        assert n.fan_in == 12


class TestAggregatedImpact:
    def test_empty_impact(self):
        impact = AggregatedImpact(
            changed_nodes=[],
            downstream_affected=[],
            upstream_dependents=[],
            total_blast_radius=0,
            by_type={},
            by_depth={},
            by_layer={},
            by_module={},
            cross_tech_impacts=[],
            transactions_affected=[],
        )
        assert impact.total_blast_radius == 0


class TestDriftReport:
    def test_no_drift(self):
        d = DriftReport(
            potential_new_module_deps=[],
            circular_deps_affected=[],
            new_files_outside_modules=[],
        )
        assert d.has_drift is False

    def test_has_drift_with_new_deps(self):
        d = DriftReport(
            potential_new_module_deps=[
                ModuleDependency(from_module="orders", to_module="billing")
            ],
            circular_deps_affected=[],
            new_files_outside_modules=[],
        )
        assert d.has_drift is True
