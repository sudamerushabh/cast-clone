"""Tests for PR analysis data models."""

from __future__ import annotations

from app.pr_analysis.models import (
    AffectedNode,
    AggregatedImpact,
    ChangedNode,
    CrossTechImpact,
    DiffHunk,
    DriftReport,
    FileDiff,
    GitPlatform,
    ModuleDependency,
    PRDiff,
    PullRequestEvent,
)


class TestGitPlatform:
    def test_enum_values(self) -> None:
        assert GitPlatform.github == "github"
        assert GitPlatform.gitlab == "gitlab"
        assert GitPlatform.bitbucket == "bitbucket"
        assert GitPlatform.gitea == "gitea"

    def test_enum_is_str(self) -> None:
        assert isinstance(GitPlatform.github, str)

    def test_enum_members_count(self) -> None:
        assert len(GitPlatform) == 4


class TestDiffHunk:
    def test_creation(self) -> None:
        hunk = DiffHunk(old_start=10, old_count=5, new_start=12, new_count=7)
        assert hunk.old_start == 10
        assert hunk.old_count == 5
        assert hunk.new_start == 12
        assert hunk.new_count == 7

    def test_new_end_property(self) -> None:
        hunk = DiffHunk(old_start=1, old_count=3, new_start=1, new_count=5)
        assert hunk.new_end == 5  # 1 + 5 - 1

    def test_new_end_single_line(self) -> None:
        hunk = DiffHunk(old_start=1, old_count=1, new_start=1, new_count=1)
        assert hunk.new_end == 1


class TestFileDiff:
    def test_creation(self) -> None:
        hunk = DiffHunk(old_start=1, old_count=2, new_start=1, new_count=3)
        fd = FileDiff(
            path="src/main.py",
            status="modified",
            old_path=None,
            additions=3,
            deletions=2,
            hunks=[hunk],
        )
        assert fd.path == "src/main.py"
        assert fd.status == "modified"
        assert fd.old_path is None
        assert fd.additions == 3
        assert fd.deletions == 2
        assert len(fd.hunks) == 1

    def test_renamed_file(self) -> None:
        fd = FileDiff(
            path="src/new_name.py",
            status="renamed",
            old_path="src/old_name.py",
            additions=0,
            deletions=0,
            hunks=[],
        )
        assert fd.old_path == "src/old_name.py"


class TestPRDiff:
    def test_creation(self) -> None:
        diff = PRDiff(
            files=[],
            total_additions=10,
            total_deletions=5,
            total_files_changed=3,
        )
        assert diff.total_additions == 10
        assert diff.total_deletions == 5
        assert diff.total_files_changed == 3
        assert diff.files == []


class TestPullRequestEvent:
    def test_creation(self) -> None:
        event = PullRequestEvent(
            platform=GitPlatform.github,
            repo_url="https://github.com/org/repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="Fixes issue #1",
            author="dev",
            source_branch="fix/bug",
            target_branch="main",
            action="opened",
            commit_sha="abc123",
            created_at="2025-01-01T00:00:00Z",
        )
        assert event.platform == GitPlatform.github
        assert event.pr_number == 42
        assert event.raw_payload == {}

    def test_raw_payload_default(self) -> None:
        event = PullRequestEvent(
            platform=GitPlatform.gitlab,
            repo_url="https://gitlab.com/org/repo",
            pr_number=1,
            pr_title="MR",
            pr_description=None,
            author="dev",
            source_branch="feature",
            target_branch="main",
            action="opened",
            commit_sha="def456",
            created_at="2025-01-01T00:00:00Z",
        )
        assert event.raw_payload == {}
        # Ensure default_factory gives a new dict each time
        event.raw_payload["key"] = "value"
        event2 = PullRequestEvent(
            platform=GitPlatform.github,
            repo_url="url",
            pr_number=2,
            pr_title="t",
            pr_description=None,
            author="a",
            source_branch="b",
            target_branch="m",
            action="opened",
            commit_sha="xyz",
            created_at="2025-01-01T00:00:00Z",
        )
        assert event2.raw_payload == {}


class TestChangedNode:
    def test_creation(self) -> None:
        node = ChangedNode(
            fqn="com.example.Foo.bar",
            name="bar",
            type="method",
            path="src/Foo.java",
            line=10,
            end_line=20,
            language="java",
            change_type="modified",
        )
        assert node.fqn == "com.example.Foo.bar"
        assert node.fan_in == 0
        assert node.is_hub is False

    def test_hub_node(self) -> None:
        node = ChangedNode(
            fqn="com.example.Hub",
            name="Hub",
            type="class",
            path="src/Hub.java",
            line=1,
            end_line=100,
            language="java",
            change_type="modified",
            fan_in=25,
            is_hub=True,
        )
        assert node.fan_in == 25
        assert node.is_hub is True


class TestAffectedNode:
    def test_creation(self) -> None:
        node = AffectedNode(
            fqn="com.example.Baz",
            name="Baz",
            type="class",
            file="src/Baz.java",
            depth=2,
        )
        assert node.depth == 2
        assert node.file == "src/Baz.java"


class TestCrossTechImpact:
    def test_creation(self) -> None:
        impact = CrossTechImpact(
            kind="api_endpoint",
            name="GET /api/users",
            detail="Called by frontend UserList component",
        )
        assert impact.kind == "api_endpoint"


class TestModuleDependency:
    def test_creation(self) -> None:
        dep = ModuleDependency(from_module="service", to_module="repository")
        assert dep.from_module == "service"
        assert dep.to_module == "repository"


class TestAggregatedImpact:
    def test_creation(self) -> None:
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
        assert impact.changed_nodes == []


class TestDriftReport:
    def test_no_drift(self) -> None:
        report = DriftReport(
            potential_new_module_deps=[],
            circular_deps_affected=[],
            new_files_outside_modules=[],
        )
        assert report.has_drift is False

    def test_has_drift_new_deps(self) -> None:
        report = DriftReport(
            potential_new_module_deps=[
                ModuleDependency(from_module="a", to_module="b")
            ],
            circular_deps_affected=[],
            new_files_outside_modules=[],
        )
        assert report.has_drift is True

    def test_has_drift_circular(self) -> None:
        report = DriftReport(
            potential_new_module_deps=[],
            circular_deps_affected=[["a", "b", "a"]],
            new_files_outside_modules=[],
        )
        assert report.has_drift is True

    def test_has_drift_new_files(self) -> None:
        report = DriftReport(
            potential_new_module_deps=[],
            circular_deps_affected=[],
            new_files_outside_modules=["orphan.py"],
        )
        assert report.has_drift is True
