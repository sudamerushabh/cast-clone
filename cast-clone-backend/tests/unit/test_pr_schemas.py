"""Tests for PR analysis config, DB models, and Pydantic schemas."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.models.db import PrAnalysis, ProjectGitConfig
from app.schemas.git_config import (
    GitConfigCreate,
    GitConfigResponse,
    GitConfigUpdate,
    WebhookUrlResponse,
)
from app.schemas.pull_requests import (
    PrAffectedNodeResponse,
    PrAnalysisListResponse,
    PrAnalysisResponse,
    PrChangedNodeResponse,
    PrCrossTechResponse,
    PrDriftResponse,
    PrImpactResponse,
    PrModuleDepResponse,
)
from app.schemas.webhooks import WebhookResponse


# --- Task 1: Config ---


class TestPhase5aBedrock:
    def test_bedrock_config_defaults(self) -> None:
        s = Settings(database_url="postgresql+asyncpg://x:x@localhost/x")
        assert s.aws_region == "us-east-1"
        assert "claude-sonnet" in s.pr_analysis_model
        assert s.pr_analysis_max_subagents == 15
        assert s.pr_analysis_max_total_tokens == 500_000

    def test_bedrock_config_override(self, monkeypatch) -> None:
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        monkeypatch.setenv("PR_ANALYSIS_MODEL", "us.anthropic.claude-opus-4-20250514-v1:0")
        monkeypatch.setenv("PR_ANALYSIS_MAX_SUBAGENTS", "20")
        from app.config import get_settings
        get_settings.cache_clear()
        s = Settings()
        assert s.aws_region == "eu-west-1"
        assert "opus" in s.pr_analysis_model
        assert s.pr_analysis_max_subagents == 20


# --- Task 3: DB Models ---


class TestProjectGitConfigModel:
    def test_tablename(self) -> None:
        assert ProjectGitConfig.__tablename__ == "project_git_config"

    def test_columns_exist(self) -> None:
        cols = {c.name for c in ProjectGitConfig.__table__.columns}
        expected = {
            "id",
            "project_id",
            "platform",
            "repo_url",
            "api_token_encrypted",
            "webhook_secret",
            "monitored_branches",
            "is_active",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(cols)

    def test_project_id_unique(self) -> None:
        col = ProjectGitConfig.__table__.c.project_id
        assert col.unique is True


class TestPrAnalysisModel:
    def test_tablename(self) -> None:
        assert PrAnalysis.__tablename__ == "pr_analyses"

    def test_unique_constraint_name(self) -> None:
        constraint_names = [
            c.name
            for c in PrAnalysis.__table__.constraints
            if hasattr(c, "name") and c.name
        ]
        assert "uq_pr_project_commit" in constraint_names

    def test_columns_exist(self) -> None:
        cols = {c.name for c in PrAnalysis.__table__.columns}
        expected = {
            "id",
            "project_id",
            "platform",
            "pr_number",
            "pr_title",
            "pr_description",
            "pr_author",
            "source_branch",
            "target_branch",
            "commit_sha",
            "pr_url",
            "status",
            "risk_level",
            "changed_node_count",
            "blast_radius_total",
            "impact_summary",
            "drift_report",
            "ai_summary",
            "files_changed",
            "additions",
            "deletions",
            "graph_analysis_run_id",
            "analysis_duration_ms",
            "ai_summary_tokens",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(cols)

    def test_status_default(self) -> None:
        col = PrAnalysis.__table__.c.status
        assert col.default.arg == "pending"


# --- Task 4: Git Config Schemas ---


class TestGitConfigCreate:
    def test_valid(self) -> None:
        schema = GitConfigCreate(
            platform="github",
            repo_url="https://github.com/org/repo",
            api_token="ghp_abc123",
        )
        assert schema.platform == "github"
        assert schema.monitored_branches == ["main", "master", "develop"]

    def test_custom_branches(self) -> None:
        schema = GitConfigCreate(
            platform="gitlab",
            repo_url="https://gitlab.com/org/repo",
            api_token="glpat-abc",
            monitored_branches=["main", "staging"],
        )
        assert schema.monitored_branches == ["main", "staging"]

    def test_invalid_platform(self) -> None:
        with pytest.raises(Exception):
            GitConfigCreate(
                platform="svn",
                repo_url="https://example.com",
                api_token="tok",
            )

    def test_empty_token_rejected(self) -> None:
        with pytest.raises(Exception):
            GitConfigCreate(
                platform="github",
                repo_url="https://github.com/org/repo",
                api_token="",
            )


class TestGitConfigUpdate:
    def test_all_optional(self) -> None:
        schema = GitConfigUpdate()
        assert schema.platform is None
        assert schema.repo_url is None
        assert schema.api_token is None
        assert schema.monitored_branches is None

    def test_partial_update(self) -> None:
        schema = GitConfigUpdate(platform="bitbucket")
        assert schema.platform == "bitbucket"
        assert schema.repo_url is None


class TestGitConfigResponse:
    def test_from_attributes(self) -> None:
        assert GitConfigResponse.model_config.get("from_attributes") is True

    def test_no_api_token_field(self) -> None:
        fields = GitConfigResponse.model_fields
        assert "api_token" not in fields
        assert "api_token_encrypted" not in fields

    def test_serialization(self) -> None:
        now = datetime.now(tz=timezone.utc)
        resp = GitConfigResponse(
            id="abc",
            project_id="proj1",
            platform="github",
            repo_url="https://github.com/org/repo",
            monitored_branches=["main"],
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        data = resp.model_dump()
        assert data["platform"] == "github"
        assert "api_token" not in data


class TestWebhookUrlResponse:
    def test_creation(self) -> None:
        resp = WebhookUrlResponse(
            webhook_url="https://example.com/webhook/abc",
            webhook_secret="secret123",
        )
        assert resp.webhook_url == "https://example.com/webhook/abc"
        assert resp.webhook_secret == "secret123"


# --- Task 5: Pull Request Schemas ---


class TestPrChangedNodeResponse:
    def test_creation(self) -> None:
        node = PrChangedNodeResponse(
            fqn="com.example.Foo",
            name="Foo",
            type="class",
            path="src/Foo.java",
            line=1,
            end_line=50,
            language="java",
            change_type="modified",
        )
        assert node.fan_in == 0
        assert node.is_hub is False


class TestPrAffectedNodeResponse:
    def test_creation(self) -> None:
        node = PrAffectedNodeResponse(
            fqn="com.example.Bar",
            name="Bar",
            type="class",
            file="src/Bar.java",
            depth=3,
        )
        assert node.depth == 3


class TestPrCrossTechResponse:
    def test_creation(self) -> None:
        ct = PrCrossTechResponse(
            kind="api_endpoint",
            name="GET /users",
            detail="REST endpoint",
        )
        assert ct.kind == "api_endpoint"


class TestPrModuleDepResponse:
    def test_creation(self) -> None:
        dep = PrModuleDepResponse(from_module="service", to_module="repo")
        assert dep.from_module == "service"


class TestPrAnalysisResponse:
    def test_from_attributes(self) -> None:
        assert PrAnalysisResponse.model_config.get("from_attributes") is True

    def test_full_creation(self) -> None:
        now = datetime.now(tz=timezone.utc)
        resp = PrAnalysisResponse(
            id="id1",
            project_id="proj1",
            platform="github",
            pr_number=42,
            pr_title="Fix bug",
            pr_author="dev",
            source_branch="fix",
            target_branch="main",
            commit_sha="abc123",
            status="completed",
            created_at=now,
            updated_at=now,
        )
        assert resp.pr_number == 42
        assert resp.pr_description is None
        assert resp.risk_level is None


class TestPrAnalysisListResponse:
    def test_creation(self) -> None:
        resp = PrAnalysisListResponse(items=[], total=0, limit=20, offset=0)
        assert resp.total == 0
        assert resp.limit == 20


class TestPrImpactResponse:
    def test_creation(self) -> None:
        resp = PrImpactResponse(
            pr_analysis_id="id1",
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
        assert resp.pr_analysis_id == "id1"


class TestPrDriftResponse:
    def test_creation(self) -> None:
        resp = PrDriftResponse(
            pr_analysis_id="id1",
            has_drift=False,
            potential_new_module_deps=[],
            circular_deps_affected=[],
            new_files_outside_modules=[],
        )
        assert resp.has_drift is False


# --- Task 6: Webhook Schemas ---


class TestWebhookResponse:
    def test_minimal(self) -> None:
        resp = WebhookResponse(status="accepted")
        assert resp.status == "accepted"
        assert resp.message is None
        assert resp.pr_analysis_id is None

    def test_full(self) -> None:
        resp = WebhookResponse(
            status="accepted",
            message="PR analysis queued",
            pr_analysis_id="analysis-123",
        )
        assert resp.pr_analysis_id == "analysis-123"
