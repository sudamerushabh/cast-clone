"""SQLAlchemy ORM models for PostgreSQL metadata storage."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class Deployment(Base):
    __tablename__ = "deployment"  # singular — singleton

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), unique=True, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __init__(self, **kwargs: object) -> None:
        if "role" not in kwargs:
            kwargs["role"] = "member"
        if "is_active" not in kwargs:
            kwargs["is_active"] = True
        super().__init__(**kwargs)


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    node_fqn: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    author: Mapped[User] = relationship()


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("project_id", "node_fqn", "tag_name", name="uq_tag_node"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    node_fqn: Mapped[str] = mapped_column(String(500), nullable=False)
    tag_name: Mapped[str] = mapped_column(String(100), nullable=False)
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    author: Mapped[User] = relationship()


class SavedView(Base):
    __tablename__ = "saved_views"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    author: Mapped[User] = relationship()


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(36))
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User | None] = relationship()


class GitConnector(Base):
    __tablename__ = "git_connectors"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    auth_method: Mapped[str] = mapped_column(String(50), nullable=False, default="pat")
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="connected")
    remote_username: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    connector_id: Mapped[str] = mapped_column(
        ForeignKey("git_connectors.id", ondelete="CASCADE"), nullable=False
    )
    repo_full_name: Mapped[str] = mapped_column(String(512), nullable=False)
    repo_clone_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    default_branch: Mapped[str] = mapped_column(
        String(255), nullable=False, default="main"
    )
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(100))
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    local_path: Mapped[str | None] = mapped_column(String(1024))
    clone_status: Mapped[str] = mapped_column(String(50), default="pending")
    clone_error: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    connector: Mapped[GitConnector] = relationship()
    projects: Mapped[list[Project]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="created"
    )  # created | analyzing | analyzed | failed
    repository_id: Mapped[str | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True
    )
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_analyzed_commit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped[Repository | None] = relationship(back_populates="projects")
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def neo4j_app_name(self) -> str:
        """The app_name used in Neo4j node properties — always the project UUID."""
        return self.id


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending | running | completed | failed
    stage: Mapped[str | None] = mapped_column(String(50))
    stage_progress: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    node_count: Mapped[int | None] = mapped_column(Integer)
    edge_count: Mapped[int | None] = mapped_column(Integer)
    report: Mapped[dict | None] = mapped_column(JSON)
    snapshot: Mapped[dict | None] = mapped_column(JSON)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    total_loc: Mapped[int | None] = mapped_column(Integer)

    project: Mapped[Project] = relationship(back_populates="analysis_runs")


class RepositoryGitConfig(Base):
    __tablename__ = "repository_git_config"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    webhook_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    monitored_branches: Mapped[list] = mapped_column(
        JSONB, default=lambda: ["main", "master", "develop"]
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    post_pr_comments: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped[Repository] = relationship()


# Keep old name as alias for backwards compat in imports
ProjectGitConfig = RepositoryGitConfig


class RepositoryLocTracking(Base):
    """Materialized per-repo LOC billing aggregate.

    One row per repository. Updated after each scan completion or branch
    deletion.  ``billable_loc`` = max(latest completed run LOC) across all
    branches for this repo.
    """

    __tablename__ = "repository_loc_tracking"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    billable_loc: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_loc_project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    max_loc_branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    breakdown: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    last_recalculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    repository: Mapped[Repository] = relationship()


class PrAnalysis(Base):
    __tablename__ = "pr_analyses"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "pr_number", "commit_sha", name="uq_pr_repo_commit"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pr_title: Mapped[str] = mapped_column(String(500), nullable=False)
    pr_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_author: Mapped[str] = mapped_column(String(200), nullable=False)
    source_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    changed_node_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blast_radius_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impact_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    drift_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    files_changed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    additions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graph_analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id"), nullable=True
    )
    analysis_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_summary_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comment_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped[Repository] = relationship()


class AiSummary(Base):
    __tablename__ = "ai_summaries"
    __table_args__ = (
        UniqueConstraint("project_id", "node_fqn", name="uq_summary_project_node"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Analysis run that produced this summary. Used for auditing
    # ("this summary was generated against scan X") and for invalidation
    # when the user wants to clear cache after a re-scan.
    analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    node_fqn: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    graph_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    project: Mapped[Project] = relationship()


class AiTraceChatMessage(Base):
    """Follow-up Q&A thread attached to a trace-route summary.

    Messages persist across modal closes/reopens so the user's
    conversation with the AI about a specific node survives. Tied
    to both the project and (optionally) the analysis run that
    produced the graph — when the user re-analyzes and the topology
    changes, history remains visible but new answers reflect the
    new graph.
    """

    __tablename__ = "ai_trace_chat_messages"
    __table_args__ = (
        Index(
            "ix_trace_chat_project_node_created",
            "project_id",
            "node_fqn",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    node_fqn: Mapped[str] = mapped_column(String(500), nullable=False)
    # "user" for questions, "assistant" for AI responses
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Hash of the trace topology at the time this message was created.
    # Lets the UI flag "this Q&A is from a stale view of the code".
    graph_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped[Project] = relationship()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User | None] = relationship()

    def __init__(self, **kwargs: object) -> None:
        if "is_active" not in kwargs:
            kwargs["is_active"] = True
        super().__init__(**kwargs)


class AiUsageLog(Base):
    __tablename__ = "ai_usage_log"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'chat', 'summary', 'mcp', 'pr_analysis'
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped[Project] = relationship()
    user: Mapped[User | None] = relationship()

    def __init__(self, **kwargs: object) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid4())
        super().__init__(**kwargs)


class EmailConfig(Base):
    """Singleton row holding SMTP + email-reporting configuration."""

    __tablename__ = "email_config"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), unique=True, default=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    smtp_host: Mapped[str] = mapped_column(Text, server_default=text("''"), default="")
    smtp_port: Mapped[int] = mapped_column(
        Integer, server_default=text("587"), default=587
    )
    smtp_username: Mapped[str] = mapped_column(
        Text, server_default=text("''"), default=""
    )
    smtp_password_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    smtp_use_tls: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True
    )
    from_address: Mapped[str] = mapped_column(
        Text, server_default=text("''"), default=""
    )
    from_name: Mapped[str] = mapped_column(
        Text, server_default=text("'ChangeSafe'"), default="ChangeSafe"
    )
    recipients: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )
    flentas_bcc_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    cadence: Mapped[str] = mapped_column(
        Text, server_default=text("'off'"), default="off"
    )
    cadence_day: Mapped[int] = mapped_column(
        Integer, server_default=text("1"), default=1
    )
    cadence_hour_utc: Mapped[int] = mapped_column(
        Integer, server_default=text("9"), default=9
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SentEmail(Base):
    """Audit log + dedup record for every outgoing email."""

    __tablename__ = "sent_email"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    license_jti: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    recipients: Mapped[list] = mapped_column(JSONB, nullable=False)
    delivery_status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class AiConfig(Base):
    """Singleton row holding AI provider configuration.

    Stores the active provider (bedrock/openai), encrypted credentials,
    per-purpose model assignments, and advanced inference parameters.
    Env-var settings act as defaults; DB values override when present.
    """

    __tablename__ = "ai_config"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), unique=True, default=True
    )

    # ── Provider ──
    provider: Mapped[str] = mapped_column(
        String(20), server_default=text("'bedrock'"), default="bedrock"
    )  # "bedrock" | "openai"

    # ── Bedrock credentials ──
    aws_region: Mapped[str] = mapped_column(
        String(50), server_default=text("'us-east-1'"), default="us-east-1"
    )
    bedrock_use_iam_role: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True
    )
    aws_access_key_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    aws_secret_access_key_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )

    # ── OpenAI credentials ──
    openai_api_key_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    openai_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Model assignments (per purpose) ──
    chat_model: Mapped[str] = mapped_column(
        String(200),
        server_default=text("'us.anthropic.claude-sonnet-4-6'"),
        default="us.anthropic.claude-sonnet-4-6",
    )
    pr_analysis_model: Mapped[str] = mapped_column(
        String(200),
        server_default=text("'us.anthropic.claude-sonnet-4-6'"),
        default="us.anthropic.claude-sonnet-4-6",
    )
    summary_model: Mapped[str] = mapped_column(
        String(200),
        server_default=text("'us.anthropic.claude-sonnet-4-6'"),
        default="us.anthropic.claude-sonnet-4-6",
    )

    # ── Advanced inference parameters ──
    temperature: Mapped[float] = mapped_column(
        Numeric(4, 3), server_default=text("1.0"), default=1.0
    )
    top_p: Mapped[float] = mapped_column(
        Numeric(4, 3), server_default=text("1.0"), default=1.0
    )
    max_response_tokens: Mapped[int] = mapped_column(
        Integer, server_default=text("4096"), default=4096
    )
    thinking_budget_tokens: Mapped[int] = mapped_column(
        Integer, server_default=text("2048"), default=2048
    )
    chat_timeout_seconds: Mapped[int] = mapped_column(
        Integer, server_default=text("120"), default=120
    )
    max_tool_calls: Mapped[int] = mapped_column(
        Integer, server_default=text("15"), default=15
    )

    # ── Cost tracking (USD per million tokens) ──
    cost_input_per_mtok: Mapped[float] = mapped_column(
        Numeric(8, 4), server_default=text("3.0"), default=3.0
    )
    cost_output_per_mtok: Mapped[float] = mapped_column(
        Numeric(8, 4), server_default=text("15.0"), default=15.0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
