# Phase 5a M1 — Foundation (Models, Config, Schemas, Data Types)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add database models, configuration settings, Pydantic schemas, and shared data types required by all Phase 5a milestones.

**Architecture:** Two new SQLAlchemy models (`ProjectGitConfig`, `PrAnalysis`) in the existing `db.py`. New Pydantic schemas for webhook payloads, PR analysis responses, and git config CRUD. Shared dataclasses for the PR analysis pipeline (`PullRequestEvent`, `PRDiff`, `FileDiff`, `DiffHunk`). New config fields for the Anthropic API key.

**Tech Stack:** SQLAlchemy 2.0 (async, mapped_column), Pydantic v2, Python dataclasses.

**Depends On:** Nothing (foundation milestone).

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── config.py                       # MODIFY — add anthropic_api_key
│   ├── models/
│   │   └── db.py                       # MODIFY — add ProjectGitConfig, PrAnalysis
│   ├── schemas/
│   │   ├── webhooks.py                 # CREATE — webhook payload response models
│   │   ├── pull_requests.py            # CREATE — PR analysis request/response models
│   │   └── git_config.py              # CREATE — git config CRUD models
│   └── pr_analysis/
│       ├── __init__.py                 # CREATE — package marker
│       └── models.py                   # CREATE — PullRequestEvent, PRDiff, FileDiff, DiffHunk, AggregatedImpact, etc.
└── tests/
    └── unit/
        ├── test_pr_analysis_models.py  # CREATE — data type tests
        └── test_pr_schemas.py          # CREATE — schema validation tests
```

---

### Task 1: Add Config Settings

**Files:**
- Modify: `app/config.py`
- Test: `tests/unit/test_pr_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pr_schemas.py
"""Tests for Phase 5a configuration and schema validation."""
import pytest
from app.config import Settings


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestPhase5aConfig -v`
Expected: FAIL — `Settings` has no attribute `anthropic_api_key`

- [ ] **Step 3: Add config fields**

In `app/config.py`, add inside the `Settings` class after the `log_level` field:

```python
    # Phase 5a: AI-powered PR analysis
    anthropic_api_key: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestPhase5aConfig -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/config.py tests/unit/test_pr_schemas.py
git commit -m "feat(phase5a): add anthropic_api_key to config"
```

---

### Task 2: Create PR Analysis Data Models

**Files:**
- Create: `app/pr_analysis/__init__.py`
- Create: `app/pr_analysis/models.py`
- Test: `tests/unit/test_pr_analysis_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pr_analysis_models.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_analysis_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pr_analysis'`

- [ ] **Step 3: Create the package and models**

```python
# app/pr_analysis/__init__.py
"""PR Analysis engine — Phase 5a."""
```

```python
# app/pr_analysis/models.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_analysis_models.py -v`
Expected: PASS (all 11 tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/__init__.py app/pr_analysis/models.py tests/unit/test_pr_analysis_models.py
git commit -m "feat(phase5a): add PR analysis data models and pipeline types"
```

---

### Task 3: Add Database Models

**Files:**
- Modify: `app/models/db.py`
- Test: `tests/unit/test_pr_schemas.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pr_schemas.py`:

```python
from app.models.db import ProjectGitConfig, PrAnalysis


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
        unique_names = [
            c.name for c in constraints
            if hasattr(c, "columns") and len(c.columns) == 3
        ]
        # Just verify the constraint exists (by column count)
        unique_cols = []
        for c in constraints:
            if hasattr(c, "columns"):
                col_names = {col.name for col in c.columns}
                if col_names == {"project_id", "pr_number", "commit_sha"}:
                    unique_cols.append(col_names)
        assert len(unique_cols) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestProjectGitConfigModel -v`
Expected: FAIL — `ImportError: cannot import name 'ProjectGitConfig'`

- [ ] **Step 3: Add models to db.py**

Add to the end of `app/models/db.py` (after `AnalysisRun`):

```python
class ProjectGitConfig(Base):
    __tablename__ = "project_git_config"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    webhook_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    monitored_branches: Mapped[list | None] = mapped_column(
        JSONB, default=lambda: ["main", "master", "develop"]
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship()


class PrAnalysis(Base):
    __tablename__ = "pr_analyses"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "pr_number", "commit_sha", name="uq_pr_project_commit"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pr_title: Mapped[str] = mapped_column(String(500), nullable=False)
    pr_description: Mapped[str | None] = mapped_column(Text)
    pr_author: Mapped[str] = mapped_column(String(200), nullable=False)
    source_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    pr_url: Mapped[str | None] = mapped_column(String(500))

    # Analysis results
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | analyzing | completed | failed | stale
    risk_level: Mapped[str | None] = mapped_column(String(10))
    changed_node_count: Mapped[int | None] = mapped_column(Integer)
    blast_radius_total: Mapped[int | None] = mapped_column(Integer)
    impact_summary: Mapped[dict | None] = mapped_column(JSONB)
    drift_report: Mapped[dict | None] = mapped_column(JSONB)
    ai_summary: Mapped[str | None] = mapped_column(Text)

    # Diff metadata
    files_changed: Mapped[int | None] = mapped_column(Integer)
    additions: Mapped[int | None] = mapped_column(Integer)
    deletions: Mapped[int | None] = mapped_column(Integer)

    # Graph version tracking
    graph_analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id"), nullable=True
    )

    # Timing / cost
    analysis_duration_ms: Mapped[int | None] = mapped_column(Integer)
    ai_summary_tokens: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py -v`
Expected: PASS (all tests including Task 1 config tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/models/db.py tests/unit/test_pr_schemas.py
git commit -m "feat(phase5a): add ProjectGitConfig and PrAnalysis ORM models"
```

---

### Task 4: Create Pydantic Schemas — Git Config

**Files:**
- Create: `app/schemas/git_config.py`
- Test: `tests/unit/test_pr_schemas.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pr_schemas.py`:

```python
from app.schemas.git_config import (
    GitConfigCreate,
    GitConfigResponse,
    GitConfigUpdate,
    WebhookUrlResponse,
)


class TestGitConfigSchemas:
    def test_create_schema_validates(self):
        c = GitConfigCreate(
            platform="github",
            repo_url="https://github.com/org/repo",
            api_token="ghp_abc123",
            monitored_branches=["main", "develop"],
        )
        assert c.platform == "github"

    def test_create_schema_rejects_invalid_platform(self):
        with pytest.raises(Exception):  # Pydantic ValidationError
            GitConfigCreate(
                platform="svn",
                repo_url="https://example.com",
                api_token="token",
            )

    def test_response_masks_token(self):
        r = GitConfigResponse(
            id="abc",
            project_id="proj1",
            platform="github",
            repo_url="https://github.com/org/repo",
            monitored_branches=["main"],
            is_active=True,
            created_at="2026-03-13T00:00:00Z",
            updated_at="2026-03-13T00:00:00Z",
        )
        # No api_token field exposed
        data = r.model_dump()
        assert "api_token" not in data
        assert "api_token_encrypted" not in data

    def test_webhook_url_response(self):
        r = WebhookUrlResponse(
            webhook_url="https://codelens.example.com/api/v1/webhooks/github/proj1",
            webhook_secret="whsec_abc123",
        )
        assert "github" in r.webhook_url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestGitConfigSchemas -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create the schema**

```python
# app/schemas/git_config.py
"""Pydantic schemas for Git integration configuration."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GitConfigCreate(BaseModel):
    platform: Literal["github", "gitlab", "bitbucket", "gitea"]
    repo_url: str = Field(max_length=500)
    api_token: str = Field(min_length=1)
    monitored_branches: list[str] = ["main", "master", "develop"]


class GitConfigUpdate(BaseModel):
    repo_url: str | None = Field(default=None, max_length=500)
    api_token: str | None = None
    monitored_branches: list[str] | None = None
    is_active: bool | None = None


class GitConfigResponse(BaseModel):
    id: str
    project_id: str
    platform: str
    repo_url: str
    monitored_branches: list[str] | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebhookUrlResponse(BaseModel):
    webhook_url: str
    webhook_secret: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestGitConfigSchemas -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/schemas/git_config.py tests/unit/test_pr_schemas.py
git commit -m "feat(phase5a): add git config Pydantic schemas"
```

---

### Task 5: Create Pydantic Schemas — Pull Requests

**Files:**
- Create: `app/schemas/pull_requests.py`
- Test: `tests/unit/test_pr_schemas.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pr_schemas.py`:

```python
from app.schemas.pull_requests import (
    PrAnalysisResponse,
    PrAnalysisListResponse,
    PrImpactResponse,
    PrDriftResponse,
)


class TestPullRequestSchemas:
    def test_pr_analysis_response(self):
        r = PrAnalysisResponse(
            id="abc",
            project_id="proj1",
            platform="github",
            pr_number=42,
            pr_title="Fix bug",
            pr_author="alice",
            source_branch="fix/bug",
            target_branch="main",
            commit_sha="abc123",
            status="completed",
            risk_level="Medium",
            changed_node_count=5,
            blast_radius_total=47,
            files_changed=3,
            additions=20,
            deletions=5,
            ai_summary="This PR modifies...",
            created_at="2026-03-13T00:00:00Z",
            updated_at="2026-03-13T00:00:00Z",
        )
        assert r.pr_number == 42
        assert r.risk_level == "Medium"

    def test_pr_list_response(self):
        r = PrAnalysisListResponse(items=[], total=0, limit=20, offset=0)
        assert r.total == 0

    def test_pr_impact_response(self):
        r = PrImpactResponse(
            pr_analysis_id="abc",
            changed_nodes=[],
            downstream_affected=[],
            upstream_dependents=[],
            total_blast_radius=0,
            by_type={},
            by_depth={},
            by_layer={},
            cross_tech_impacts=[],
            transactions_affected=[],
        )
        assert r.total_blast_radius == 0

    def test_pr_drift_response(self):
        r = PrDriftResponse(
            pr_analysis_id="abc",
            has_drift=False,
            potential_new_module_deps=[],
            circular_deps_affected=[],
            new_files_outside_modules=[],
        )
        assert r.has_drift is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestPullRequestSchemas -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create the schema**

```python
# app/schemas/pull_requests.py
"""Pydantic schemas for PR analysis API endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PrChangedNodeResponse(BaseModel):
    fqn: str
    name: str
    type: str
    path: str
    line: int
    end_line: int
    language: str | None = None
    change_type: str
    fan_in: int = 0
    is_hub: bool = False


class PrAffectedNodeResponse(BaseModel):
    fqn: str
    name: str
    type: str
    file: str | None = None
    depth: int


class PrCrossTechResponse(BaseModel):
    kind: str
    name: str
    detail: str


class PrModuleDepResponse(BaseModel):
    from_module: str
    to_module: str


class PrAnalysisResponse(BaseModel):
    id: str
    project_id: str
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
    files_changed: int | None = None
    additions: int | None = None
    deletions: int | None = None
    ai_summary: str | None = None
    analysis_duration_ms: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PrAnalysisListResponse(BaseModel):
    items: list[PrAnalysisResponse]
    total: int
    limit: int
    offset: int


class PrImpactResponse(BaseModel):
    pr_analysis_id: str
    changed_nodes: list[PrChangedNodeResponse] = []
    downstream_affected: list[PrAffectedNodeResponse] = []
    upstream_dependents: list[PrAffectedNodeResponse] = []
    total_blast_radius: int = 0
    by_type: dict[str, int] = {}
    by_depth: dict[int, int] = {}
    by_layer: dict[str, int] = {}
    cross_tech_impacts: list[PrCrossTechResponse] = []
    transactions_affected: list[str] = []


class PrDriftResponse(BaseModel):
    pr_analysis_id: str
    has_drift: bool
    potential_new_module_deps: list[PrModuleDepResponse] = []
    circular_deps_affected: list[list[str]] = []
    new_files_outside_modules: list[str] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestPullRequestSchemas -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/schemas/pull_requests.py tests/unit/test_pr_schemas.py
git commit -m "feat(phase5a): add PR analysis Pydantic response schemas"
```

---

### Task 6: Create Pydantic Schemas — Webhooks

**Files:**
- Create: `app/schemas/webhooks.py`
- Test: `tests/unit/test_pr_schemas.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pr_schemas.py`:

```python
from app.schemas.webhooks import WebhookResponse


class TestWebhookSchemas:
    def test_webhook_response(self):
        r = WebhookResponse(
            status="accepted",
            pr_analysis_id="abc-123",
        )
        assert r.status == "accepted"

    def test_webhook_response_ignored(self):
        r = WebhookResponse(status="ignored", message="Not a PR event")
        assert r.pr_analysis_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestWebhookSchemas -v`
Expected: FAIL

- [ ] **Step 3: Create the schema**

```python
# app/schemas/webhooks.py
"""Pydantic schemas for webhook receiver responses."""
from __future__ import annotations

from pydantic import BaseModel


class WebhookResponse(BaseModel):
    status: str  # "accepted", "ignored", "error"
    message: str | None = None
    pr_analysis_id: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestWebhookSchemas -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/schemas/webhooks.py tests/unit/test_pr_schemas.py
git commit -m "feat(phase5a): add webhook response schema"
```

---

## Success Criteria

- [ ] `app/config.py` has `anthropic_api_key` field
- [ ] `app/models/db.py` has `ProjectGitConfig` and `PrAnalysis` models with correct columns and constraints
- [ ] `app/pr_analysis/models.py` has all pipeline dataclasses (`PullRequestEvent`, `PRDiff`, `FileDiff`, `DiffHunk`, `AggregatedImpact`, `DriftReport`, etc.)
- [ ] `app/schemas/git_config.py`, `app/schemas/pull_requests.py`, `app/schemas/webhooks.py` all exist with validated Pydantic v2 models
- [ ] All tests pass: `uv run pytest tests/unit/test_pr_analysis_models.py tests/unit/test_pr_schemas.py -v`
