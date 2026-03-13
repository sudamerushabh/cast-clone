"""Tests for Phase 5a configuration and schema validation."""
import pytest
from app.config import Settings
from app.models.db import ProjectGitConfig, PrAnalysis


class TestPhase5aConfig:
    def test_anthropic_api_key_default_empty(self):
        s = Settings(database_url="postgresql+asyncpg://x:x@localhost/x")
        assert s.anthropic_api_key == ""

    def test_anthropic_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        # Clear lru_cache so Settings picks up new env
        from app.config import get_settings
        get_settings.cache_clear()
        s = Settings()
        assert s.anthropic_api_key == "sk-ant-test-key"


class TestProjectGitConfigModel:
    def test_table_name(self):
        assert ProjectGitConfig.__tablename__ == "project_git_config"

    def test_fields_exist(self):
        """Verify all required columns are defined."""
        columns = {c.name for c in ProjectGitConfig.__table__.columns}
        expected = {
            "id", "project_id", "platform", "repo_url",
            "api_token_encrypted", "webhook_secret",
            "monitored_branches", "is_active",
            "created_at", "updated_at",
        }
        assert expected.issubset(columns)


class TestPrAnalysisModel:
    def test_table_name(self):
        assert PrAnalysis.__tablename__ == "pr_analyses"

    def test_fields_exist(self):
        columns = {c.name for c in PrAnalysis.__table__.columns}
        expected = {
            "id", "project_id", "platform", "pr_number",
            "pr_title", "pr_author", "source_branch", "target_branch",
            "commit_sha", "status", "risk_level",
            "changed_node_count", "blast_radius_total",
            "impact_summary", "drift_report", "ai_summary",
            "files_changed", "additions", "deletions",
            "analysis_duration_ms", "ai_summary_tokens",
            "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_unique_constraint(self):
        """pr_analyses has a unique constraint on (project_id, pr_number, commit_sha)."""
        constraints = PrAnalysis.__table__.constraints
        unique_cols = []
        for c in constraints:
            if hasattr(c, "columns"):
                col_names = {col.name for col in c.columns}
                if col_names == {"project_id", "pr_number", "commit_sha"}:
                    unique_cols.append(col_names)
        assert len(unique_cols) == 1
