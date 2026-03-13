"""AI-powered PR analysis agent pipeline.

Public API:
    generate_pr_summary() -- runs the full multi-agent pipeline or falls back
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
                summary="AI analysis unavailable -- pipeline failed. See logs.",
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

    # Stage 1: Triage -- convert PRDiff to the dict format triage_diff expects
    diff_dict = {f.path: f.status for f in diff.files}
    changed_node_dicts = [
        {"fqn": n.fqn, "file": n.path} for n in impact.changed_nodes
    ]

    triage_result = triage_diff(
        diff_dict,
        changed_nodes=changed_node_dicts,
        max_subagents=settings.pr_analysis_max_subagents,
    )

    logger.info(
        "ai_pipeline_triage",
        code_batches=len(triage_result.code_batches),
        total_subagents=triage_result.total_subagents,
    )

    # Stage 2: Dispatch subagents in parallel
    agent_configs: list[AgentConfig] = []

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
        summary = "AI analysis unavailable -- fallback summary failed. See logs."
        tokens = 0

    return SummaryResult(
        summary=summary,
        tokens_used=tokens,
        agents_run=1,
        agents_failed=0 if tokens > 0 else 1,
        total_duration_ms=int((time.monotonic() - start) * 1000),
    )
