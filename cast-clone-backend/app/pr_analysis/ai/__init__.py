"""AI-powered PR analysis agent pipeline.

Public API:
    generate_pr_summary() -- runs the supervisor-first pipeline or falls back
    to a single-call summary if the pipeline fails or no repo is available.
"""
from __future__ import annotations

import json
import time

import structlog
from anthropic import AsyncAnthropicBedrock

from app.config import get_settings
from app.services.ai_provider import EffectiveAiConfig, create_bedrock_client
from app.pr_analysis.ai.report_types import SummaryResult
from app.pr_analysis.ai.supervisor import SupervisorInput, run_supervisor
from app.pr_analysis.ai.tool_context import ToolContext
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
    source_repo_path: str | None = None,
    ai_config: EffectiveAiConfig | None = None,
) -> SummaryResult:
    """Run the full AI agent pipeline for PR analysis.

    Falls back to single-call summary if:
    - repo_path is empty (no cloned repo)
    - Pipeline fails
    """
    settings = get_settings()
    start = time.monotonic()

    if ai_config:
        client = create_bedrock_client(ai_config)
    else:
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
            source_repo_path=source_repo_path,
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
    source_repo_path: str | None = None,
) -> SummaryResult:
    """Execute the supervisor-first AI pipeline.

    The supervisor receives all data upfront and decides what to investigate.
    It can use tools directly (read_file, search, graph queries) and
    dispatch subagents for deeper investigation when needed.
    """
    # Agents read files from source branch, query graph from target branch
    ctx = ToolContext(
        repo_path=source_repo_path or repo_path,
        target_repo_path=repo_path,
        graph_store=graph_store,
        app_name=app_name,
    )
    model = settings.pr_analysis_supervisor_model

    # Build the full context for the supervisor
    sup_input = SupervisorInput(
        subagent_reports=[],  # No pre-spawned agents
        pr_event=pr_event,
        diff=diff,
        impact=impact,
        drift=drift,
        risk_level=risk_level,
    )

    supervisor_result = await run_supervisor(
        client, sup_input, ctx, model=model, settings=settings,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    agents_failed = 1 if supervisor_result.error else 0

    logger.info(
        "ai_pipeline_completed",
        agents_run=1,
        agents_failed=agents_failed,
        total_tokens=supervisor_result.total_tokens,
        duration_ms=elapsed_ms,
    )

    return SummaryResult(
        summary=supervisor_result.final_text,
        tokens_used=supervisor_result.total_tokens,
        agents_run=1,
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
        async with client.messages.stream(
            model=settings.pr_analysis_model,
            max_tokens=65536,
            system="You are a software architect. Summarize this PR's impact concisely. Focus on what could break.",
            messages=[{"role": "user", "content": context}],
        ) as stream:
            response = await stream.get_final_message()
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
