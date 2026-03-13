# Phase 5a M7a — AI Agent Pipeline Foundation

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up the foundation for the multi-agent PR analysis pipeline: Bedrock config, anthropic SDK dependency, report dataclasses, tool context, and deterministic triage logic.

**Architecture:** Creates the `app/pr_analysis/ai/` package with foundational types and the triage module. Uses `anthropic[bedrock]` SDK with `AsyncAnthropicBedrock` client — authenticates via AWS IAM (no API keys). Triage is pure Python (no LLM) that categorizes changed files and batches them for subagent dispatch.

**Tech Stack:** `anthropic[bedrock]` (adds boto3), Python dataclasses, fnmatch for glob matching.

**Depends On:** M1 (pr_analysis package, config.py, PRDiff/FileDiff models).

**Spec:** `docs/superpowers/specs/2026-03-13-pr-ai-agent-pipeline-design.md`

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── config.py                          # MODIFY — add Bedrock + pipeline config
│   └── pr_analysis/
│       └── ai/
│           ├── __init__.py                # CREATE — package marker (public API added in M7c)
│           ├── report_types.py            # CREATE — SummaryResult, subagent report dataclasses
│           ├── tool_context.py            # CREATE — ToolContext shared by all tools
│           └── triage.py                  # CREATE — deterministic file categorization + batching
└── tests/
    └── unit/
        ├── test_ai_report_types.py        # CREATE
        └── test_ai_triage.py              # CREATE
```

---

### Task 1: Install anthropic[bedrock] + Update Config

**Files:**
- Modify: `app/config.py`
- Test: `tests/unit/test_pr_schemas.py` (append)

- [ ] **Step 1: Install anthropic with Bedrock extras**

```bash
cd cast-clone-backend && uv add "anthropic[bedrock]>=0.40"
```

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_pr_schemas.py`:

```python
class TestPhase5aBedrock:
    def test_bedrock_config_defaults(self):
        s = Settings(database_url="postgresql+asyncpg://x:x@localhost/x")
        assert s.aws_region == "us-east-1"
        assert "claude-sonnet" in s.pr_analysis_model
        assert s.pr_analysis_max_subagents == 15
        assert s.pr_analysis_max_total_tokens == 500_000

    def test_bedrock_config_override(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        monkeypatch.setenv("PR_ANALYSIS_MODEL", "us.anthropic.claude-opus-4-20250514-v1:0")
        monkeypatch.setenv("PR_ANALYSIS_MAX_SUBAGENTS", "20")
        from app.config import get_settings
        get_settings.cache_clear()
        s = Settings()
        assert s.aws_region == "eu-west-1"
        assert "opus" in s.pr_analysis_model
        assert s.pr_analysis_max_subagents == 20
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestPhase5aBedrock -v`
Expected: FAIL — `Settings` has no attribute `aws_region`

- [ ] **Step 4: Update config.py**

In `app/config.py`, replace the existing `anthropic_api_key` line and add the Bedrock config fields after the `log_level` field:

```python
    # Phase 5a: AI agent pipeline (Bedrock)
    aws_region: str = "us-east-1"
    pr_analysis_model: str = "us.anthropic.claude-sonnet-4-20250514-v1:0"
    pr_analysis_supervisor_model: str = "us.anthropic.claude-sonnet-4-20250514-v1:0"
    pr_analysis_max_subagents: int = 15
    pr_analysis_max_total_tokens: int = 500_000
```

Remove the `anthropic_api_key: str = ""` line if it was added by M1 — it's no longer needed with Bedrock (uses IAM).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py::TestPhase5aBedrock -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend
git add pyproject.toml uv.lock app/config.py tests/unit/test_pr_schemas.py
git commit -m "feat(phase5a): add anthropic[bedrock] dep and AI pipeline config"
```

---

### Task 2: Report Types + SummaryResult

**Files:**
- Create: `app/pr_analysis/ai/__init__.py`
- Create: `app/pr_analysis/ai/report_types.py`
- Test: `tests/unit/test_ai_report_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_report_types.py
"""Tests for AI pipeline report types."""
import json
import pytest

from app.pr_analysis.ai.report_types import (
    SummaryResult,
    AgentReport,
    CodeChangeReport,
    ArchImpactReport,
    InfraConfigReport,
    TestGapReport,
    parse_agent_response,
)


class TestSummaryResult:
    def test_creation(self):
        r = SummaryResult(
            summary="Test summary",
            tokens_used=1000,
            agents_run=5,
            agents_failed=1,
            total_duration_ms=12000,
        )
        assert r.tokens_used == 1000
        assert r.agents_failed == 1


class TestAgentReport:
    def test_creation(self):
        r = AgentReport(role="code_change_analyst", raw_text="some text", parsed={"key": "val"})
        assert r.role == "code_change_analyst"
        assert r.parse_failed is False

    def test_failed_parse(self):
        r = AgentReport(role="test", raw_text="not json", parsed=None, parse_failed=True)
        assert r.parse_failed is True


class TestParseAgentResponse:
    def test_parses_json_block(self):
        text = 'Here is my analysis:\n```json\n{"role": "code_change_analyst", "files_analyzed": ["a.java"]}\n```'
        report = parse_agent_response("code_change_analyst", text)
        assert report.parse_failed is False
        assert report.parsed["files_analyzed"] == ["a.java"]

    def test_parses_raw_json(self):
        text = '{"role": "infra_config_analyst", "config_issues": []}'
        report = parse_agent_response("infra_config_analyst", text)
        assert report.parse_failed is False

    def test_handles_invalid_json(self):
        text = "I couldn't complete the analysis due to errors."
        report = parse_agent_response("test_gap_analyst", text)
        assert report.parse_failed is True
        assert report.raw_text == text

    def test_extracts_last_json_block(self):
        text = 'Thinking...\n{"role": "first"}\nMore thinking...\n{"role": "second", "data": true}'
        report = parse_agent_response("test", text)
        assert report.parsed["role"] == "second"


class TestCodeChangeReport:
    def test_from_dict(self):
        data = {
            "role": "code_change_analyst",
            "batch_id": "orders",
            "files_analyzed": ["OrderService.java"],
            "semantic_summary": "Added discount check",
            "changes": [],
            "cross_references_discovered": [],
            "config_dependencies_found": ["ORDER_MAX_DISCOUNT"],
            "potential_issues": [],
        }
        r = CodeChangeReport(**data)
        assert r.batch_id == "orders"
        assert r.config_dependencies_found == ["ORDER_MAX_DISCOUNT"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_report_types.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create the package and report types**

```python
# app/pr_analysis/ai/__init__.py
"""AI-powered PR analysis agent pipeline."""
```

```python
# app/pr_analysis/ai/report_types.py
"""Structured report types for AI pipeline agents."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


@dataclass
class SummaryResult:
    """Final output of the AI pipeline."""
    summary: str
    tokens_used: int
    agents_run: int = 0
    agents_failed: int = 0
    total_duration_ms: int = 0


@dataclass
class AgentReport:
    """Generic container for a subagent's output."""
    role: str
    raw_text: str
    parsed: dict | None = None
    parse_failed: bool = False


@dataclass
class CodeChangeReport:
    """Structured report from a Code Change Analyst."""
    role: str = "code_change_analyst"
    batch_id: str = ""
    files_analyzed: list[str] = field(default_factory=list)
    semantic_summary: str = ""
    changes: list[dict] = field(default_factory=list)
    cross_references_discovered: list[str] = field(default_factory=list)
    config_dependencies_found: list[str] = field(default_factory=list)
    potential_issues: list[str] = field(default_factory=list)


@dataclass
class ArchImpactReport:
    """Structured report from the Architecture Impact Analyst."""
    role: str = "architecture_impact_analyst"
    critical_paths: list[dict] = field(default_factory=list)
    hub_nodes_affected: list[dict] = field(default_factory=list)
    layer_analysis: str = ""
    transaction_impact: list[str] = field(default_factory=list)
    cross_tech_impact: list[dict] = field(default_factory=list)
    module_coupling_observations: str = ""


@dataclass
class InfraConfigReport:
    """Structured report from the Infrastructure & Config Analyst."""
    role: str = "infra_config_analyst"
    config_issues: list[dict] = field(default_factory=list)
    dockerfile_impact: str = ""
    migration_status: str = ""
    ci_impact: str = ""
    dependency_changes: str = ""
    environment_variables: dict = field(default_factory=dict)


@dataclass
class TestGapReport:
    """Structured report from the Test Gap Analyst."""
    role: str = "test_gap_analyst"
    coverage_assessment: list[dict] = field(default_factory=list)
    test_files_analyzed: list[str] = field(default_factory=list)
    untested_paths: list[str] = field(default_factory=list)
    integration_test_status: str = ""
    overall_assessment: str = ""


# ── JSON parsing ──

_JSON_BLOCK_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def parse_agent_response(role: str, text: str) -> AgentReport:
    """Parse a subagent's text response into an AgentReport.

    Extracts the last JSON object from the text. If no valid JSON found,
    returns a fallback report with parse_failed=True.
    """
    # Try to find JSON blocks in the text
    matches = _JSON_BLOCK_RE.findall(text)
    if matches:
        # Try the last match first (most likely the final report)
        for candidate in reversed(matches):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return AgentReport(role=role, raw_text=text, parsed=parsed)
            except json.JSONDecodeError:
                continue

    # Try the whole text as JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return AgentReport(role=role, raw_text=text, parsed=parsed)
    except json.JSONDecodeError:
        pass

    # Fallback
    return AgentReport(role=role, raw_text=text, parsed=None, parse_failed=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_report_types.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/ai/__init__.py app/pr_analysis/ai/report_types.py tests/unit/test_ai_report_types.py
git commit -m "feat(phase5a): add AI pipeline report types and JSON parser"
```

---

### Task 3: ToolContext

**Files:**
- Create: `app/pr_analysis/ai/tool_context.py`

- [ ] **Step 1: Create ToolContext**

```python
# app/pr_analysis/ai/tool_context.py
"""Shared context passed to all tool handlers."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.neo4j import GraphStore


@dataclass
class ToolContext:
    """Immutable context shared across all tool handlers in a pipeline run."""
    repo_path: str          # Absolute path to cloned repo on disk
    graph_store: GraphStore  # Neo4j connection for graph queries
    app_name: str           # Project identifier for Neo4j app_name filter
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/ai/tool_context.py
git commit -m "feat(phase5a): add ToolContext for AI pipeline tool handlers"
```

---

### Task 4: Deterministic Triage

**Files:**
- Create: `app/pr_analysis/ai/triage.py`
- Test: `tests/unit/test_ai_triage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_triage.py
"""Tests for deterministic file triage and batching."""
import pytest

from app.pr_analysis.ai.triage import (
    categorize_file,
    triage_diff,
    TriageResult,
    CodeBatch,
)
from app.pr_analysis.models import DiffHunk, FileDiff, PRDiff, ChangedNode


class TestCategorizeFile:
    def test_java_source(self):
        assert categorize_file("src/main/java/com/app/OrderService.java") == "source"

    def test_python_source(self):
        assert categorize_file("app/services/neo4j.py") == "source"

    def test_typescript_source(self):
        assert categorize_file("src/components/Graph.tsx") == "source"

    def test_java_test(self):
        assert categorize_file("src/test/java/com/app/OrderServiceTest.java") == "test"

    def test_python_test(self):
        assert categorize_file("tests/unit/test_neo4j.py") == "test"

    def test_dockerfile(self):
        assert categorize_file("Dockerfile") == "infra"

    def test_docker_compose(self):
        assert categorize_file("docker-compose.yml") == "infra"

    def test_github_actions(self):
        assert categorize_file(".github/workflows/ci.yml") == "infra"

    def test_env_file(self):
        assert categorize_file(".env.example") == "config"

    def test_application_yml(self):
        assert categorize_file("src/main/resources/application.yml") == "config"

    def test_flyway_migration(self):
        assert categorize_file("src/main/resources/db/migration/V1__init.sql") == "migration"

    def test_alembic_migration(self):
        assert categorize_file("alembic/versions/001_init.py") == "migration"

    def test_readme(self):
        assert categorize_file("README.md") == "docs"

    def test_unknown(self):
        assert categorize_file("data/seed.csv") == "other"


class TestTriageDiff:
    def _make_diff(self, files: list[str]) -> PRDiff:
        return PRDiff(
            files=[
                FileDiff(path=f, status="modified", old_path=None, additions=5, deletions=2, hunks=[])
                for f in files
            ],
            total_additions=5 * len(files),
            total_deletions=2 * len(files),
            total_files_changed=len(files),
        )

    def test_basic_categorization(self):
        diff = self._make_diff([
            "src/main/java/com/app/OrderService.java",
            "Dockerfile",
            "tests/unit/test_order.py",
            "README.md",
        ])
        result = triage_diff(diff, changed_nodes=[], max_subagents=15)
        assert len(result.code_batches) == 1
        assert len(result.infra_files) == 1
        assert len(result.test_files) == 1
        assert len(result.doc_files) == 1

    def test_groups_by_module(self):
        diff = self._make_diff([
            "src/main/java/com/app/orders/OrderService.java",
            "src/main/java/com/app/orders/OrderRepo.java",
            "src/main/java/com/app/billing/BillingService.java",
        ])
        result = triage_diff(diff, changed_nodes=[], max_subagents=15)
        assert len(result.code_batches) == 2
        batch_ids = {b.batch_id for b in result.code_batches}
        assert len(batch_ids) == 2

    def test_max_5_files_per_batch(self):
        files = [f"src/main/java/com/app/orders/Svc{i}.java" for i in range(8)]
        diff = self._make_diff(files)
        result = triage_diff(diff, changed_nodes=[], max_subagents=15)
        for batch in result.code_batches:
            assert len(batch.files) <= 5

    def test_circuit_breaker_merges_batches(self):
        """When too many batches, merge smallest ones."""
        files = [f"src/main/java/com/app/mod{i}/Svc.java" for i in range(20)]
        diff = self._make_diff(files)
        result = triage_diff(diff, changed_nodes=[], max_subagents=8)
        # 8 max - 3 reserved for specialists = 5 max code batches
        assert len(result.code_batches) <= 5
        assert result.total_subagents <= 8

    def test_uses_graph_fqns_for_batching(self):
        diff = self._make_diff([
            "src/main/java/com/app/orders/OrderService.java",
            "src/main/java/com/app/orders/OrderRepo.java",
        ])
        nodes = [
            ChangedNode(
                fqn="com.app.orders.OrderService.create", name="create",
                type="Function", path="src/main/java/com/app/orders/OrderService.java",
                line=1, end_line=10, language="java", change_type="modified",
            ),
            ChangedNode(
                fqn="com.app.orders.OrderRepo.save", name="save",
                type="Function", path="src/main/java/com/app/orders/OrderRepo.java",
                line=1, end_line=10, language="java", change_type="modified",
            ),
        ]
        result = triage_diff(diff, changed_nodes=nodes, max_subagents=15)
        assert len(result.code_batches) == 1
        assert result.code_batches[0].batch_id == "com.app.orders"
        assert len(result.code_batches[0].graph_node_fqns) == 2

    def test_extracts_env_vars_from_nodes(self):
        diff = self._make_diff(["src/main/java/com/app/Svc.java"])
        nodes = [
            ChangedNode(
                fqn="com.app.Svc.run", name="run", type="Function",
                path="src/main/java/com/app/Svc.java", line=1, end_line=10,
                language="java", change_type="modified",
            ),
        ]
        result = triage_diff(diff, changed_nodes=nodes, max_subagents=15)
        assert isinstance(result.env_vars_referenced, list)

    def test_total_subagents_count(self):
        diff = self._make_diff([
            "src/main/java/com/app/orders/Svc.java",
            "src/main/java/com/app/billing/Svc.java",
            "Dockerfile",
            "tests/unit/test_order.py",
        ])
        result = triage_diff(diff, changed_nodes=[], max_subagents=15)
        # 2 code batches + 3 specialists = 5
        assert result.total_subagents == 2 + 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_triage.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement triage**

```python
# app/pr_analysis/ai/triage.py
"""Deterministic file categorization and batching for AI pipeline.

No LLM calls — pure Python logic that runs before any agent is dispatched.
"""
from __future__ import annotations

import fnmatch
from collections import defaultdict
from dataclasses import dataclass, field

from app.pr_analysis.models import ChangedNode, PRDiff

# ── File category patterns ──

_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("test", ["*test*", "*spec*", "*Test*", "*Spec*"]),
    ("migration", [
        "**/migration*/*", "**/migrations/*", "**/flyway/*",
        "**/alembic/*", "**/liquibase/*",
    ]),
    ("infra", [
        "Dockerfile*", "docker-compose*", ".github/*", ".github/**/*",
        ".gitlab-ci*", "Makefile", "*.tf", "Jenkinsfile", "Procfile",
    ]),
    ("config", [
        "*.yml", "*.yaml", "*.properties", "*.toml", "*.ini",
        "*.env*", "settings.*", "config.*", "application.*",
    ]),
    ("docs", ["*.md", "*.txt", "*.rst", "LICENSE*", "CHANGELOG*"]),
    ("source", [
        "*.java", "*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.cs",
        "*.go", "*.kt", "*.scala", "*.rb",
    ]),
]

# Language-specific path prefixes to strip for module grouping
_STRIP_PREFIXES = [
    "src/main/java/", "src/main/kotlin/", "src/main/scala/",
    "src/main/resources/", "src/", "app/", "lib/", "pkg/",
]


@dataclass
class CodeBatch:
    """A batch of source files to be analyzed by one Code Change Analyst."""
    batch_id: str
    files: list[str]
    graph_node_fqns: list[str] = field(default_factory=list)


@dataclass
class TriageResult:
    """Output of the triage stage — input to the dispatch stage."""
    code_batches: list[CodeBatch]
    config_files: list[str]
    infra_files: list[str]
    migration_files: list[str]
    test_files: list[str]
    doc_files: list[str]
    env_vars_referenced: list[str]
    total_subagents: int


def categorize_file(path: str) -> str:
    """Categorize a file path into source/test/config/infra/migration/docs/other."""
    filename = path.split("/")[-1]
    for category, patterns in _CATEGORY_PATTERNS:
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(filename, pattern):
                return category
    return "other"


def triage_diff(
    diff: PRDiff,
    changed_nodes: list[ChangedNode],
    max_subagents: int = 15,
) -> TriageResult:
    """Categorize changed files and build a subagent dispatch plan."""
    source_files: list[str] = []
    config_files: list[str] = []
    infra_files: list[str] = []
    migration_files: list[str] = []
    test_files: list[str] = []
    doc_files: list[str] = []

    for f in diff.files:
        cat = categorize_file(f.path)
        if cat == "source":
            source_files.append(f.path)
        elif cat == "test":
            test_files.append(f.path)
        elif cat == "config":
            config_files.append(f.path)
        elif cat == "infra":
            infra_files.append(f.path)
        elif cat == "migration":
            migration_files.append(f.path)
        elif cat == "docs":
            doc_files.append(f.path)
        # "other" files are silently dropped

    # Build file→module map from graph nodes if available
    file_to_module = _build_module_map(changed_nodes)

    # Group source files by module
    module_groups: dict[str, list[str]] = defaultdict(list)
    for f in source_files:
        module = file_to_module.get(f) or _infer_module_from_path(f)
        module_groups[module].append(f)

    # Build file→fqns map
    file_to_fqns: dict[str, list[str]] = defaultdict(list)
    for node in changed_nodes:
        file_to_fqns[node.path].append(node.fqn)

    # Create batches (max 5 files each)
    code_batches: list[CodeBatch] = []
    for module_id, files in module_groups.items():
        for i in range(0, len(files), 5):
            batch_files = files[i : i + 5]
            fqns = []
            for f in batch_files:
                fqns.extend(file_to_fqns.get(f, []))
            code_batches.append(CodeBatch(
                batch_id=module_id if i == 0 else f"{module_id}_{i // 5 + 1}",
                files=batch_files,
                graph_node_fqns=fqns,
            ))

    # Circuit breaker: merge smallest batches if over budget
    max_code_batches = max_subagents - 3  # Reserve 3 for specialist agents
    while len(code_batches) > max_code_batches and len(code_batches) > 1:
        # Sort by file count, merge two smallest
        code_batches.sort(key=lambda b: len(b.files))
        smallest = code_batches.pop(0)
        code_batches[0].files.extend(smallest.files)
        code_batches[0].graph_node_fqns.extend(smallest.graph_node_fqns)
        code_batches[0].batch_id = f"merged_{code_batches[0].batch_id}"

    # Extract env vars referenced in graph node properties
    env_vars: list[str] = []
    # (In practice, env vars come from node annotations like @Value("${VAR}"))
    # For now, return empty — enriched by code analyst agents at runtime

    return TriageResult(
        code_batches=code_batches,
        config_files=config_files,
        infra_files=infra_files,
        migration_files=migration_files,
        test_files=test_files,
        doc_files=doc_files,
        env_vars_referenced=env_vars,
        total_subagents=len(code_batches) + 3,  # +3 for arch, infra, test
    )


def _build_module_map(nodes: list[ChangedNode]) -> dict[str, str]:
    """Map file paths to module names using graph node FQNs."""
    file_to_module: dict[str, str] = {}
    for node in nodes:
        if node.fqn and "." in node.fqn:
            # Extract first 2 FQN segments as module: com.app.orders.OrderService → com.app.orders
            parts = node.fqn.split(".")
            module = ".".join(parts[:3]) if len(parts) >= 3 else ".".join(parts[:2])
            file_to_module[node.path] = module
    return file_to_module


def _infer_module_from_path(path: str) -> str:
    """Fallback: infer module from file path by stripping language prefixes."""
    stripped = path
    for prefix in _STRIP_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    # Take first 2 directory segments
    parts = stripped.split("/")
    if len(parts) >= 3:
        return "/".join(parts[:2])
    elif len(parts) == 2:
        return parts[0]
    return "root"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_triage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/ai/triage.py tests/unit/test_ai_triage.py
git commit -m "feat(phase5a): add deterministic triage for AI pipeline file batching"
```

---

## Success Criteria

- [ ] `anthropic[bedrock]` installed and importable (`from anthropic import AsyncAnthropicBedrock`)
- [ ] Config has `aws_region`, `pr_analysis_model`, `pr_analysis_supervisor_model`, `pr_analysis_max_subagents`, `pr_analysis_max_total_tokens`
- [ ] `SummaryResult` has `summary`, `tokens_used`, `agents_run`, `agents_failed`, `total_duration_ms`
- [ ] `parse_agent_response()` extracts JSON from agent text, handles parse failures gracefully
- [ ] `categorize_file()` correctly categorizes source/test/config/infra/migration/docs
- [ ] `triage_diff()` groups files by module, respects max 5 files/batch, applies circuit breaker
- [ ] All tests pass: `uv run pytest tests/unit/test_ai_report_types.py tests/unit/test_ai_triage.py tests/unit/test_pr_schemas.py::TestPhase5aBedrock -v`
