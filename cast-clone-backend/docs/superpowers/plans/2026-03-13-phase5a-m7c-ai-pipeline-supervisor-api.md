# Phase 5a M7c — AI Pipeline Supervisor, Public API & Integration

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Supervisor agent (with `dispatch_subagent`), the public `generate_pr_summary()` entry point with fallback, and update M8 orchestrator to pass the new parameters.

**Architecture:** The supervisor receives all subagent reports, has 50 tool calls including `dispatch_subagent` for ad-hoc follow-ups, and generates the final narrative. The public API function orchestrates the full pipeline: triage → parallel subagents → supervisor → return. Falls back to a single-call summary if the pipeline fails or no repo is available.

**Tech Stack:** `anthropic[bedrock]` (`AsyncAnthropicBedrock`), `asyncio.gather`, structlog.

**Depends On:** M7a (config, report_types, triage), M7b (tools, subagents, prompts).

**Spec:** `docs/superpowers/specs/2026-03-13-pr-ai-agent-pipeline-design.md`

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── pr_analysis/
│       ├── ai/
│       │   ├── __init__.py              # MODIFY — add generate_pr_summary()
│       │   └── supervisor.py            # CREATE — supervisor loop + dispatch
│       └── analyzer.py                  # MODIFY — pass new params to AI pipeline
└── tests/
    └── unit/
        ├── test_ai_supervisor.py        # CREATE
        └── test_ai_pipeline.py          # CREATE — end-to-end pipeline test
```

---

### Task 1: Supervisor Agent

**Files:**
- Create: `app/pr_analysis/ai/supervisor.py`
- Test: `tests/unit/test_ai_supervisor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_supervisor.py
"""Tests for the Supervisor agent."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.pr_analysis.ai.supervisor import run_supervisor, SupervisorInput
from app.pr_analysis.ai.report_types import AgentReport
from app.pr_analysis.ai.tool_context import ToolContext
from app.pr_analysis.models import (
    AggregatedImpact,
    DriftReport,
    PullRequestEvent,
    GitPlatform,
)


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.query = AsyncMock(return_value=[])
    return store


@pytest.fixture
def ctx(tmp_path, mock_store):
    return ToolContext(repo_path=str(tmp_path), graph_store=mock_store, app_name="test")


def _make_text_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=500, output_tokens=300)
    return resp


def _make_event() -> PullRequestEvent:
    return PullRequestEvent(
        platform=GitPlatform.GITHUB,
        repo_url="https://github.com/org/repo",
        pr_number=42,
        pr_title="Fix order processing",
        pr_description="Fixes #123",
        author="alice",
        source_branch="fix/order-bug",
        target_branch="main",
        action="opened",
        commit_sha="abc123",
        created_at="2026-03-13T10:00:00Z",
    )


def _make_impact() -> AggregatedImpact:
    return AggregatedImpact(
        changed_nodes=[], downstream_affected=[], upstream_dependents=[],
        total_blast_radius=10, by_type={"Function": 5}, by_depth={1: 5},
        by_layer={}, by_module={}, cross_tech_impacts=[], transactions_affected=[],
    )


def _make_drift() -> DriftReport:
    return DriftReport(
        potential_new_module_deps=[], circular_deps_affected=[],
        new_files_outside_modules=[],
    )


class TestRunSupervisor:
    @pytest.mark.asyncio
    async def test_generates_summary(self, ctx):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_text_response("## VERDICT\nMedium risk PR...")
        )

        reports = [
            AgentReport(role="code_change_analyst", raw_text="report1", parsed={"role": "code_change_analyst"}),
            AgentReport(role="architecture_impact_analyst", raw_text="report2", parsed={"role": "arch"}),
            AgentReport(role="infra_config_analyst", raw_text="report3", parsed={"role": "infra"}),
            AgentReport(role="test_gap_analyst", raw_text="report4", parsed={"role": "test"}),
        ]

        sup_input = SupervisorInput(
            subagent_reports=reports,
            pr_event=_make_event(),
            impact=_make_impact(),
            drift=_make_drift(),
            risk_level="Medium",
        )

        result = await run_supervisor(mock_client, sup_input, ctx, model="test-model", settings=MagicMock(pr_analysis_max_subagents=15))
        assert "VERDICT" in result.final_text
        assert result.tool_calls_made == 0
        assert result.total_tokens == 800

    @pytest.mark.asyncio
    async def test_includes_failed_agents(self, ctx):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_text_response("Summary with partial data")
        )

        reports = [
            AgentReport(role="code_change_analyst", raw_text="good report", parsed={"role": "code"}),
            AgentReport(role="infra_config_analyst", raw_text="Agent failed: timeout", parsed=None, parse_failed=True),
        ]

        sup_input = SupervisorInput(
            subagent_reports=reports,
            pr_event=_make_event(),
            impact=_make_impact(),
            drift=_make_drift(),
            risk_level="Low",
        )

        result = await run_supervisor(mock_client, sup_input, ctx, model="m", settings=MagicMock(pr_analysis_max_subagents=15))
        # Supervisor should still produce output despite failed subagent
        assert result.final_text == "Summary with partial data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_supervisor.py -v`
Expected: FAIL

- [ ] **Step 3: Implement supervisor**

```python
# app/pr_analysis/ai/supervisor.py
"""Supervisor agent — synthesizes subagent reports into final summary.

The supervisor has 50 tool calls (vs 25 for subagents) and can dispatch
ad-hoc subagents via dispatch_subagent for follow-up investigations.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

import structlog

from app.pr_analysis.ai.prompts import SUPERVISOR_PROMPT
from app.pr_analysis.ai.report_types import AgentReport
from app.pr_analysis.ai.subagents import AgentResult, run_agent, AgentConfig
from app.pr_analysis.ai.tool_context import ToolContext
from app.pr_analysis.ai.tools import (
    VALID_TOOL_NAMES,
    get_tool_definitions,
    handle_tool_call,
)
from app.pr_analysis.models import (
    AggregatedImpact,
    DriftReport,
    PullRequestEvent,
)

logger = structlog.get_logger(__name__)

_SUPERVISOR_MAX_TOOL_CALLS = 50
_SUPERVISOR_TIMEOUT = 180  # seconds (excludes subagent wait time)


@dataclass
class SupervisorInput:
    """All data the supervisor needs to generate the final summary."""
    subagent_reports: list[AgentReport]
    pr_event: PullRequestEvent
    impact: AggregatedImpact
    drift: DriftReport
    risk_level: str


async def run_supervisor(
    client,
    sup_input: SupervisorInput,
    ctx: ToolContext,
    model: str,
    settings,
) -> AgentResult:
    """Run the supervisor agentic loop with dispatch_subagent support."""
    start = time.monotonic()

    # Build the initial message with all context
    initial_message = _build_supervisor_context(sup_input)

    # Get tool definitions including dispatch_subagent
    all_tool_defs = get_tool_definitions(include_dispatch=True)

    messages = [{"role": "user", "content": initial_message}]
    tool_calls_made = 0
    total_tokens = 0
    subagents_dispatched = 0

    try:
        while True:
            elapsed = time.monotonic() - start
            if elapsed > _SUPERVISOR_TIMEOUT:
                return AgentResult(
                    role="supervisor",
                    final_text="Supervisor timed out — partial analysis available from subagent reports.",
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens,
                    duration_ms=int(elapsed * 1000),
                    error="timeout",
                )

            response = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    system=SUPERVISOR_PROMPT,
                    messages=messages,
                    tools=all_tool_defs,
                    max_tokens=8192,
                ),
                timeout=max(_SUPERVISOR_TIMEOUT - elapsed, 10),
            )

            total_tokens += response.usage.input_tokens + response.usage.output_tokens

            if response.stop_reason == "end_turn" or response.stop_reason != "tool_use":
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text += block.text
                return AgentResult(
                    role="supervisor",
                    final_text=text,
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            # Process tool calls
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    if tool_calls_made >= _SUPERVISOR_MAX_TOOL_CALLS:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": '{"error": "Tool call limit (50) reached. Emit your final summary now."}',
                            "is_error": True,
                        })
                    elif block.name == "dispatch_subagent":
                        # Handle dispatch_subagent specially
                        result = await _handle_dispatch(
                            client, block.input, ctx, model, settings, subagents_dispatched,
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                        tool_calls_made += 1
                        subagents_dispatched += 1
                    else:
                        result = await handle_tool_call(ctx, block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                        tool_calls_made += 1

            messages.append({"role": "user", "content": tool_results})

    except asyncio.TimeoutError:
        return AgentResult(
            role="supervisor",
            final_text="Supervisor timed out",
            tool_calls_made=tool_calls_made,
            total_tokens=total_tokens,
            duration_ms=int((time.monotonic() - start) * 1000),
            error="timeout",
        )
    except Exception as exc:
        logger.error("supervisor_failed", error=str(exc), exc_info=True)
        return AgentResult(
            role="supervisor",
            final_text=f"Supervisor failed: {exc}",
            tool_calls_made=tool_calls_made,
            total_tokens=total_tokens,
            duration_ms=int((time.monotonic() - start) * 1000),
            error=str(exc),
        )


async def _handle_dispatch(
    client, tool_input: dict, ctx: ToolContext, model: str, settings, dispatched_count: int,
) -> str:
    """Handle a dispatch_subagent tool call from the supervisor."""
    # Validate tool names
    requested_tools = tool_input.get("tools", [])
    invalid = set(requested_tools) - VALID_TOOL_NAMES
    if invalid:
        return json.dumps({"error": f"Invalid tool names: {invalid}. Valid: {sorted(VALID_TOOL_NAMES)}"})

    # Check budget
    if dispatched_count >= 3:  # Max 3 ad-hoc subagents
        return json.dumps({"error": "Ad-hoc subagent budget exceeded (max 3). Use your existing tools."})

    role = tool_input.get("role", "ad_hoc")
    prompt = tool_input.get("prompt", "")

    logger.info("supervisor_dispatching_subagent", role=role)

    config = AgentConfig(
        role=f"adhoc_{role}",
        system_prompt=f"You are a focused investigator. Your task:\n{prompt}\n\nUse your tools to find the answer. Return your findings as clear text.",
        initial_message=prompt,
        tools=requested_tools,
        max_tool_calls=25,
    )

    result = await run_agent(client, config, ctx, model=model, timeout=120)
    return result.final_text


def _build_supervisor_context(sup_input: SupervisorInput) -> str:
    """Assemble the initial message for the supervisor from all data."""
    sections = []

    # PR metadata
    ev = sup_input.pr_event
    sections.append(f"""## Pull Request
- **Title:** {ev.pr_title}
- **Author:** {ev.author}
- **Branch:** {ev.source_branch} → {ev.target_branch}
- **Description:** {ev.pr_description[:1000] if ev.pr_description else 'None'}
- **Risk Classification:** {sup_input.risk_level}""")

    # Impact summary
    impact = sup_input.impact
    sections.append(f"""## Impact Data (from deterministic analysis)
- **Total blast radius:** {impact.total_blast_radius} unique affected nodes
- **Changed nodes:** {len(impact.changed_nodes)}
- **By type:** {json.dumps(impact.by_type)}
- **By depth:** {json.dumps(impact.by_depth)}
- **Cross-tech impacts:** {len(impact.cross_tech_impacts)}
- **Transactions affected:** {len(impact.transactions_affected)}""")

    # Drift
    drift = sup_input.drift
    if drift.has_drift:
        sections.append(f"""## Architecture Drift Detected
- New module deps: {len(drift.potential_new_module_deps)}
- Circular deps involved: {len(drift.circular_deps_affected)}
- Files outside modules: {len(drift.new_files_outside_modules)}""")

    # Subagent reports
    sections.append("## Specialist Agent Reports\n")
    for i, report in enumerate(sup_input.subagent_reports):
        if report.parse_failed:
            sections.append(f"### Report {i + 1}: {report.role} (PARSE FAILED — raw text)\n{report.raw_text[:3000]}\n")
        elif report.error if hasattr(report, 'error') else False:
            sections.append(f"### Report {i + 1}: {report.role} (FAILED)\n{report.raw_text[:1000]}\n")
        else:
            sections.append(f"### Report {i + 1}: {report.role}\n```json\n{json.dumps(report.parsed, indent=2)[:5000]}\n```\n")

    sections.append("""## Your Task
Synthesize the above reports and data into a comprehensive PR analysis following your system prompt structure. Use your tools to investigate anything that seems incomplete or contradictory.""")

    return "\n\n".join(sections)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_supervisor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/ai/supervisor.py tests/unit/test_ai_supervisor.py
git commit -m "feat(phase5a): implement supervisor agent with dispatch_subagent"
```

---

### Task 2: Public API — generate_pr_summary()

**Files:**
- Modify: `app/pr_analysis/ai/__init__.py`
- Test: `tests/unit/test_ai_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_pipeline.py
"""End-to-end tests for the AI pipeline public API."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.pr_analysis.ai import generate_pr_summary
from app.pr_analysis.ai.report_types import SummaryResult
from app.pr_analysis.models import (
    AggregatedImpact,
    ChangedNode,
    DiffHunk,
    DriftReport,
    FileDiff,
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)


def _make_event() -> PullRequestEvent:
    return PullRequestEvent(
        platform=GitPlatform.GITHUB,
        repo_url="https://github.com/org/repo",
        pr_number=42,
        pr_title="Fix order processing",
        pr_description="Fixes #123",
        author="alice",
        source_branch="fix/order-bug",
        target_branch="main",
        action="opened",
        commit_sha="abc123",
        created_at="2026-03-13T10:00:00Z",
    )


def _make_diff() -> PRDiff:
    return PRDiff(
        files=[
            FileDiff(
                path="src/main/java/com/app/OrderService.java",
                status="modified", old_path=None, additions=5, deletions=2,
                hunks=[DiffHunk(old_start=10, old_count=3, new_start=10, new_count=6)],
            )
        ],
        total_additions=5, total_deletions=2, total_files_changed=1,
    )


def _make_impact() -> AggregatedImpact:
    return AggregatedImpact(
        changed_nodes=[
            ChangedNode(
                fqn="com.app.OrderService.create", name="create",
                type="Function", path="src/main/java/com/app/OrderService.java",
                line=10, end_line=50, language="java", change_type="modified",
            )
        ],
        downstream_affected=[], upstream_dependents=[],
        total_blast_radius=10, by_type={"Function": 5}, by_depth={1: 5},
        by_layer={}, by_module={}, cross_tech_impacts=[], transactions_affected=[],
    )


def _make_drift() -> DriftReport:
    return DriftReport(
        potential_new_module_deps=[], circular_deps_affected=[],
        new_files_outside_modules=[],
    )


def _mock_text_response(text):
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    return resp


class TestGeneratePrSummary:
    @pytest.mark.asyncio
    async def test_full_pipeline_returns_summary(self, tmp_path):
        # Create a minimal repo
        src = tmp_path / "src" / "main" / "java" / "com" / "app"
        src.mkdir(parents=True)
        (src / "OrderService.java").write_text("public class OrderService {}")

        mock_store = AsyncMock()
        mock_store.query = AsyncMock(return_value=[])
        mock_store.query_single = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_text_response('{"role": "test", "summary": "ok"}')
        )

        with patch("app.pr_analysis.ai.AsyncAnthropicBedrock", return_value=mock_client):
            result = await generate_pr_summary(
                pr_event=_make_event(),
                diff=_make_diff(),
                impact=_make_impact(),
                drift=_make_drift(),
                risk_level="Medium",
                repo_path=str(tmp_path),
                graph_store=mock_store,
                app_name="test-project",
            )

        assert isinstance(result, SummaryResult)
        assert len(result.summary) > 0
        assert result.agents_run >= 1

    @pytest.mark.asyncio
    async def test_fallback_when_no_repo_path(self):
        mock_store = AsyncMock()
        mock_store.query = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_text_response("Simple fallback summary")
        )

        with patch("app.pr_analysis.ai.AsyncAnthropicBedrock", return_value=mock_client):
            result = await generate_pr_summary(
                pr_event=_make_event(),
                diff=_make_diff(),
                impact=_make_impact(),
                drift=_make_drift(),
                risk_level="Low",
                repo_path="",  # No repo
                graph_store=mock_store,
                app_name="test",
            )

        assert isinstance(result, SummaryResult)
        # Falls back to single-call mode
        assert len(result.summary) > 0

    @pytest.mark.asyncio
    async def test_fallback_on_pipeline_failure(self, tmp_path):
        mock_store = AsyncMock()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))

        with patch("app.pr_analysis.ai.AsyncAnthropicBedrock", return_value=mock_client):
            result = await generate_pr_summary(
                pr_event=_make_event(),
                diff=_make_diff(),
                impact=_make_impact(),
                drift=_make_drift(),
                risk_level="Low",
                repo_path=str(tmp_path),
                graph_store=mock_store,
                app_name="test",
            )

        assert isinstance(result, SummaryResult)
        # Should not crash — returns fallback
        assert "unavailable" in result.summary.lower() or len(result.summary) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_pipeline.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the public API**

```python
# app/pr_analysis/ai/__init__.py
"""AI-powered PR analysis agent pipeline.

Public API:
    generate_pr_summary() — runs the full multi-agent pipeline or falls back
    to a single-call summary if the pipeline fails or no repo is available.
"""
from __future__ import annotations

import asyncio
import json
import time

import structlog
from anthropic import AsyncAnthropicBedrock

from app.config import get_settings
from app.pr_analysis.ai.report_types import (
    AgentReport,
    SummaryResult,
    parse_agent_response,
)
from app.pr_analysis.ai.subagents import AgentConfig, AgentResult, run_agent
from app.pr_analysis.ai.supervisor import SupervisorInput, run_supervisor
from app.pr_analysis.ai.tool_context import ToolContext
from app.pr_analysis.ai.triage import triage_diff
from app.pr_analysis.ai.prompts import (
    CODE_CHANGE_ANALYST_PROMPT,
    ARCHITECTURE_IMPACT_ANALYST_PROMPT,
    INFRA_CONFIG_ANALYST_PROMPT,
    TEST_GAP_ANALYST_PROMPT,
)
from app.pr_analysis.models import (
    AggregatedImpact,
    DriftReport,
    PRDiff,
    PullRequestEvent,
)
from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)


async def generate_pr_summary(
    pr_event: PullRequestEvent,
    diff: PRDiff,
    impact: AggregatedImpact,
    drift: DriftReport,
    risk_level: str,
    repo_path: str,
    graph_store: GraphStore,
    app_name: str,
) -> SummaryResult:
    """Run the full AI agent pipeline for PR analysis.

    Falls back to single-call summary if:
    - repo_path is empty (no cloned repo)
    - Pipeline fails
    """
    settings = get_settings()
    start = time.monotonic()

    client = AsyncAnthropicBedrock(aws_region=settings.aws_region)

    # If no repo path, fall back to single-call
    if not repo_path:
        logger.info("ai_pipeline_fallback", reason="no_repo_path")
        return await _single_call_fallback(
            client, pr_event, impact, drift, risk_level, settings,
        )

    try:
        return await _run_pipeline(
            client, pr_event, diff, impact, drift, risk_level,
            repo_path, graph_store, app_name, settings, start,
        )
    except Exception as exc:
        logger.error("ai_pipeline_failed", error=str(exc), exc_info=True)
        # Try single-call fallback
        try:
            return await _single_call_fallback(
                client, pr_event, impact, drift, risk_level, settings,
            )
        except Exception:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return SummaryResult(
                summary="AI analysis unavailable — pipeline failed. See logs.",
                tokens_used=0,
                agents_run=0,
                agents_failed=0,
                total_duration_ms=elapsed_ms,
            )


async def _run_pipeline(
    client,
    pr_event: PullRequestEvent,
    diff: PRDiff,
    impact: AggregatedImpact,
    drift: DriftReport,
    risk_level: str,
    repo_path: str,
    graph_store: GraphStore,
    app_name: str,
    settings,
    start: float,
) -> SummaryResult:
    """Execute the full multi-agent pipeline."""
    ctx = ToolContext(repo_path=repo_path, graph_store=graph_store, app_name=app_name)
    model = settings.pr_analysis_model
    supervisor_model = settings.pr_analysis_supervisor_model

    # Stage 1: Triage
    triage_result = triage_diff(
        diff,
        changed_nodes=impact.changed_nodes,
        max_subagents=settings.pr_analysis_max_subagents,
    )

    logger.info(
        "ai_pipeline_triage",
        code_batches=len(triage_result.code_batches),
        total_subagents=triage_result.total_subagents,
    )

    # Stage 2: Dispatch subagents in parallel
    agent_configs = []

    # Code Change Analysts
    for batch in triage_result.code_batches:
        agent_configs.append(AgentConfig(
            role=f"code_change_analyst_{batch.batch_id}",
            system_prompt=CODE_CHANGE_ANALYST_PROMPT,
            initial_message=(
                f"Analyze this batch of changed files (module: {batch.batch_id}):\n"
                f"Files: {json.dumps(batch.files)}\n"
                f"Graph node FQNs: {json.dumps(batch.graph_node_fqns)}\n\n"
                f"Read each file and produce your JSON report."
            ),
            tools=["read_file", "search_files", "grep_content", "list_directory", "query_graph_node"],
            max_tool_calls=25,
        ))

    # Architecture Impact Analyst
    agent_configs.append(AgentConfig(
        role="architecture_impact_analyst",
        system_prompt=ARCHITECTURE_IMPACT_ANALYST_PROMPT,
        initial_message=(
            f"Analyze the architecture impact of this PR.\n\n"
            f"Changed node FQNs: {json.dumps([n.fqn for n in impact.changed_nodes])}\n"
            f"Total blast radius: {impact.total_blast_radius}\n"
            f"By type: {json.dumps(impact.by_type)}\n"
            f"Transactions affected: {json.dumps(impact.transactions_affected)}\n"
            f"Cross-tech impacts: {len(impact.cross_tech_impacts)}\n\n"
            f"Use your tools to trace impact chains and produce your JSON report."
        ),
        tools=["query_graph_node", "get_node_impact", "find_path", "read_file", "search_files", "grep_content"],
        max_tool_calls=25,
    ))

    # Infra & Config Analyst
    agent_configs.append(AgentConfig(
        role="infra_config_analyst",
        system_prompt=INFRA_CONFIG_ANALYST_PROMPT,
        initial_message=(
            f"Analyze infrastructure and configuration impact.\n\n"
            f"Config files detected: {json.dumps(triage_result.config_files)}\n"
            f"Infrastructure files: {json.dumps(triage_result.infra_files)}\n"
            f"Migration files: {json.dumps(triage_result.migration_files)}\n"
            f"Env vars referenced in code: {json.dumps(triage_result.env_vars_referenced)}\n\n"
            f"Search the repo for all config and infra files. Produce your JSON report."
        ),
        tools=["read_file", "search_files", "grep_content", "list_directory"],
        max_tool_calls=25,
    ))

    # Test Gap Analyst
    agent_configs.append(AgentConfig(
        role="test_gap_analyst",
        system_prompt=TEST_GAP_ANALYST_PROMPT,
        initial_message=(
            f"Analyze test coverage gaps for changed code.\n\n"
            f"Changed node FQNs: {json.dumps([n.fqn for n in impact.changed_nodes])}\n"
            f"Test files detected in PR: {json.dumps(triage_result.test_files)}\n\n"
            f"Search for tests related to changed nodes. Produce your JSON report."
        ),
        tools=["read_file", "search_files", "grep_content", "list_directory", "query_graph_node"],
        max_tool_calls=25,
    ))

    # Run all subagents in parallel
    results: list[AgentResult | BaseException] = await asyncio.gather(
        *[run_agent(client, cfg, ctx, model=model, timeout=120) for cfg in agent_configs],
        return_exceptions=True,
    )

    # Parse results into reports
    reports: list[AgentReport] = []
    agents_run = len(results)
    agents_failed = 0
    total_tokens = 0

    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            agents_failed += 1
            reports.append(AgentReport(
                role=agent_configs[i].role,
                raw_text=f"Agent failed: {result}",
                parse_failed=True,
            ))
            logger.error("subagent_failed", role=agent_configs[i].role, error=str(result))
        else:
            total_tokens += result.total_tokens
            report = parse_agent_response(result.role, result.final_text)
            if result.error:
                report.parse_failed = True
                agents_failed += 1
            reports.append(report)
            logger.info(
                "subagent_completed",
                role=result.role,
                tokens=result.total_tokens,
                tool_calls=result.tool_calls_made,
                duration_ms=result.duration_ms,
                error=result.error,
            )

    # Stage 3: Supervisor
    sup_input = SupervisorInput(
        subagent_reports=reports,
        pr_event=pr_event,
        impact=impact,
        drift=drift,
        risk_level=risk_level,
    )

    supervisor_result = await run_supervisor(
        client, sup_input, ctx, model=supervisor_model, settings=settings,
    )
    total_tokens += supervisor_result.total_tokens
    agents_run += 1
    if supervisor_result.error:
        agents_failed += 1

    elapsed_ms = int((time.monotonic() - start) * 1000)

    logger.info(
        "ai_pipeline_completed",
        agents_run=agents_run,
        agents_failed=agents_failed,
        total_tokens=total_tokens,
        duration_ms=elapsed_ms,
    )

    return SummaryResult(
        summary=supervisor_result.final_text,
        tokens_used=total_tokens,
        agents_run=agents_run,
        agents_failed=agents_failed,
        total_duration_ms=elapsed_ms,
    )


async def _single_call_fallback(
    client,
    pr_event: PullRequestEvent,
    impact: AggregatedImpact,
    drift: DriftReport,
    risk_level: str,
    settings,
) -> SummaryResult:
    """Simple single-call summary as fallback when pipeline can't run."""
    start = time.monotonic()

    context = json.dumps({
        "pr_title": pr_event.pr_title,
        "pr_description": (pr_event.pr_description or "")[:500],
        "author": pr_event.author,
        "risk_level": risk_level,
        "blast_radius": impact.total_blast_radius,
        "by_type": impact.by_type,
        "changed_nodes": [n.fqn for n in impact.changed_nodes[:20]],
        "has_drift": drift.has_drift,
    }, indent=2)

    try:
        response = await client.messages.create(
            model=settings.pr_analysis_model,
            max_tokens=2048,
            system="You are a software architect. Summarize this PR's impact concisely. Focus on what could break.",
            messages=[{"role": "user", "content": context}],
        )
        summary = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens
    except Exception as exc:
        logger.error("single_call_fallback_failed", error=str(exc))
        summary = "AI analysis unavailable — fallback summary failed. See logs."
        tokens = 0

    return SummaryResult(
        summary=summary,
        tokens_used=tokens,
        agents_run=1,
        agents_failed=0 if tokens > 0 else 1,
        total_duration_ms=int((time.monotonic() - start) * 1000),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/ai/__init__.py tests/unit/test_ai_pipeline.py
git commit -m "feat(phase5a): implement AI pipeline public API with multi-agent orchestration and fallback"
```

---

### Task 3: Update M8 Orchestrator

**Files:**
- Modify: `app/pr_analysis/analyzer.py`

- [ ] **Step 1: Update generate_pr_summary call in analyzer.py**

The M8 orchestrator (`analyzer.py`) currently calls the old `generate_pr_summary()` with `api_key`. Update it to use the new signature:

Replace the import:
```python
# OLD:
from app.pr_analysis.ai_summary import generate_pr_summary
# NEW:
from app.pr_analysis.ai import generate_pr_summary
```

Replace the call site (inside `run_pr_analysis()`):
```python
        # OLD:
        summary_result = await generate_pr_summary(
            pr_event=pr_event,
            impact=impact,
            drift=drift,
            risk_level=risk_level,
            api_key=anthropic_api_key,
        )

        # NEW:
        summary_result = await generate_pr_summary(
            pr_event=pr_event,
            diff=diff,
            impact=impact,
            drift=drift,
            risk_level=risk_level,
            repo_path=repo_path,
            graph_store=store,
            app_name=app_name,
        )
```

Update `run_pr_analysis()` signature — remove `anthropic_api_key`, add `repo_path`:
```python
async def run_pr_analysis(
    pr_record,
    session: AsyncSession,
    store: GraphStore,
    api_token: str,
    repo_path: str,           # NEW — replaces anthropic_api_key
    app_name: str,
) -> None:
```

Store additional metadata from `SummaryResult`:
```python
        pr_record.ai_summary = summary_result.summary
        pr_record.ai_summary_tokens = summary_result.tokens_used
```

- [ ] **Step 2: Update webhook background task**

In `app/api/webhooks.py`, update `_run_analysis_background` to resolve `repo_path` and remove `anthropic_api_key`:

```python
async def _run_analysis_background(
    pr_analysis_id: str,
    project_id: str,
    api_token_encrypted: str,
    platform: str,
    secret_key: str,
) -> None:
    """Background task wrapper for PR analysis."""
    from app.pr_analysis.analyzer import run_pr_analysis
    from app.services.postgres import get_background_session
    from app.models.db import PrAnalysis, Project, Repository

    async with get_background_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(PrAnalysis).where(PrAnalysis.id == pr_analysis_id)
        )
        pr_record = result.scalar_one_or_none()
        if not pr_record:
            return

        # Resolve repo_path from project's repository
        proj_result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = proj_result.scalar_one_or_none()
        repo_path = ""
        if project and project.repository_id:
            repo_result = await session.execute(
                select(Repository).where(Repository.id == project.repository_id)
            )
            repo = repo_result.scalar_one_or_none()
            if repo and repo.local_path:
                repo_path = repo.local_path

        store = Neo4jGraphStore(get_driver())
        api_token = decrypt_token(api_token_encrypted, secret_key)

        await run_pr_analysis(
            pr_record=pr_record,
            session=session,
            store=store,
            api_token=api_token,
            repo_path=repo_path,
            app_name=project_id,
        )
```

- [ ] **Step 3: Run all tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_analyzer.py tests/unit/test_webhooks_api.py -v`
Expected: PASS (may need to update mocks in test_pr_analyzer.py to match new signature)

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/analyzer.py app/api/webhooks.py
git commit -m "feat(phase5a): wire AI agent pipeline into M8 orchestrator with Bedrock"
```

---

### Task 4: Delete old ai_summary.py (if it exists)

- [ ] **Step 1: Remove the old single-file module**

```bash
cd cast-clone-backend
rm -f app/pr_analysis/ai_summary.py tests/unit/test_ai_summary.py
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend
git add -u
git commit -m "refactor(phase5a): remove old ai_summary.py — replaced by ai/ pipeline package"
```

---

## Success Criteria

- [ ] Supervisor agent synthesizes subagent reports into comprehensive narrative
- [ ] Supervisor can dispatch ad-hoc subagents (max 3)
- [ ] `generate_pr_summary()` runs full pipeline: triage → parallel subagents → supervisor
- [ ] Falls back to single-call summary when no repo_path available
- [ ] Falls back to single-call summary when pipeline fails
- [ ] Returns `SummaryResult` with `agents_run`, `agents_failed`, `total_duration_ms`
- [ ] M8 orchestrator passes `repo_path`, `graph_store`, `app_name` to AI pipeline
- [ ] Webhook background task resolves `repo_path` from Repository record
- [ ] Uses `AsyncAnthropicBedrock` (IAM auth, no API key needed)
- [ ] Old `ai_summary.py` removed
- [ ] All tests pass: `uv run pytest tests/unit/test_ai_supervisor.py tests/unit/test_ai_pipeline.py -v`
