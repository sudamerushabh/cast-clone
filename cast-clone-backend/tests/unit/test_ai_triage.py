"""Tests for deterministic triage module."""

from __future__ import annotations

from app.pr_analysis.ai.triage import (
    CodeBatch,
    TriageResult,
    categorize_file,
    triage_diff,
)


class TestCategorizeFile:
    def test_java_source(self) -> None:
        assert categorize_file("src/main/java/com/example/Foo.java") == "source"

    def test_python_source(self) -> None:
        assert categorize_file("app/services/neo4j.py") == "source"

    def test_typescript_source(self) -> None:
        assert categorize_file("src/components/App.tsx") == "source"

    def test_test_file_python(self) -> None:
        assert categorize_file("tests/unit/test_foo.py") == "test"

    def test_test_file_js_spec(self) -> None:
        assert categorize_file("src/foo.spec.ts") == "test"

    def test_dockerfile(self) -> None:
        assert categorize_file("Dockerfile") == "infra"

    def test_docker_compose(self) -> None:
        assert categorize_file("docker-compose.yml") == "infra"

    def test_github_actions(self) -> None:
        assert categorize_file(".github/workflows/ci.yml") == "infra"

    def test_env_file(self) -> None:
        assert categorize_file(".env") == "config"

    def test_application_yml(self) -> None:
        assert categorize_file("application.yml") == "config"

    def test_flyway_migration(self) -> None:
        assert categorize_file("db/migrations/V1__init.sql") == "migration"

    def test_alembic_migration(self) -> None:
        assert categorize_file("alembic/versions/001_init.py") == "migration"

    def test_readme(self) -> None:
        assert categorize_file("README.md") == "docs"

    def test_unknown_extension(self) -> None:
        # Unknown extension defaults to source
        assert categorize_file("something.xyz") == "source"


class TestTriageDiff:
    def test_basic_categorization(self) -> None:
        diff = {
            "src/main/java/com/example/Foo.java": "diff content",
            "tests/unit/test_foo.py": "diff content",
            "Dockerfile": "diff content",
            ".env": "diff content",
            "README.md": "diff content",
            "db/migrations/V1__init.sql": "diff content",
        }
        result = triage_diff(diff)
        assert len(result.code_batches) >= 1
        assert len(result.test_files) == 1
        assert len(result.infra_files) == 1
        assert len(result.config_files) == 1
        assert len(result.doc_files) == 1
        assert len(result.migration_files) == 1

    def test_groups_by_module(self) -> None:
        diff = {
            "src/main/java/com/example/service/Foo.java": "+",
            "src/main/java/com/example/service/Bar.java": "+",
            "src/main/java/com/example/repo/Baz.java": "+",
        }
        result = triage_diff(diff)
        # Should have at least 2 batches (service + repo modules)
        modules = {b.batch_id.split("_")[0] for b in result.code_batches}
        assert len(modules) >= 2

    def test_max_5_per_batch(self) -> None:
        # 7 files in the same module => should produce 2 batches
        diff = {f"src/service/File{i}.java": "+" for i in range(7)}
        result = triage_diff(diff)
        for batch in result.code_batches:
            assert len(batch.files) <= 5

    def test_circuit_breaker_merge(self) -> None:
        # Create many single-file modules to exceed limit
        diff = {f"module{i}/File.java": "+" for i in range(20)}
        result = triage_diff(diff, max_subagents=8)
        # max_code_batches = 8 - 3 = 5
        assert len(result.code_batches) <= 5
        assert result.total_subagents <= 8

    def test_uses_graph_fqns(self) -> None:
        diff = {
            "src/main/java/com/example/Foo.java": "+",
        }
        changed_nodes = [
            {"fqn": "com.example.service.Foo", "file": "src/main/java/com/example/Foo.java"},
        ]
        result = triage_diff(diff, changed_nodes=changed_nodes)
        assert len(result.code_batches) >= 1
        # Module should be derived from FQN (first 3 segments)
        batch = result.code_batches[0]
        assert len(batch.graph_node_fqns) >= 1
        assert "com.example.service" in batch.graph_node_fqns[0]

    def test_total_subagents_count(self) -> None:
        diff = {
            "src/service/Foo.java": "+",
            "src/repo/Bar.java": "+",
        }
        result = triage_diff(diff)
        # total_subagents = len(code_batches) + 3
        assert result.total_subagents == len(result.code_batches) + 3

    def test_empty_diff(self) -> None:
        result = triage_diff({})
        assert result.code_batches == []
        assert result.total_subagents == 3  # reserved agents only
