"""Supervisor agent -- synthesizes subagent reports into final summary.

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
from app.pr_analysis.ai.subagents import AgentConfig, AgentResult, run_agent
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

    messages: list[dict] = [{"role": "user", "content": initial_message}]
    tool_calls_made = 0
    total_tokens = 0
    subagents_dispatched = 0

    try:
        while True:
            elapsed = time.monotonic() - start
            if elapsed > _SUPERVISOR_TIMEOUT:
                return AgentResult(
                    role="supervisor",
                    final_text="Supervisor timed out -- partial analysis available from subagent reports.",
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
        return json.dumps({"error": f"Invalid tool names: {sorted(invalid)}. Valid: {sorted(VALID_TOOL_NAMES)}"})

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
    pr_desc = ev.pr_description[:1000] if ev.pr_description else "None"
    sections.append(
        f"## Pull Request\n"
        f"- **Title:** {ev.pr_title}\n"
        f"- **Author:** {ev.author}\n"
        f"- **Branch:** {ev.source_branch} -> {ev.target_branch}\n"
        f"- **Description:** {pr_desc}\n"
        f"- **Risk Classification:** {sup_input.risk_level}"
    )

    # Impact summary
    impact = sup_input.impact
    sections.append(
        f"## Impact Data (from deterministic analysis)\n"
        f"- **Total blast radius:** {impact.total_blast_radius} unique affected nodes\n"
        f"- **Changed nodes:** {len(impact.changed_nodes)}\n"
        f"- **By type:** {json.dumps(impact.by_type)}\n"
        f"- **By depth:** {json.dumps({str(k): v for k, v in impact.by_depth.items()})}\n"
        f"- **Cross-tech impacts:** {len(impact.cross_tech_impacts)}\n"
        f"- **Transactions affected:** {len(impact.transactions_affected)}"
    )

    # Drift
    drift = sup_input.drift
    if drift.has_drift:
        sections.append(
            f"## Architecture Drift Detected\n"
            f"- New module deps: {len(drift.potential_new_module_deps)}\n"
            f"- Circular deps involved: {len(drift.circular_deps_affected)}\n"
            f"- Files outside modules: {len(drift.new_files_outside_modules)}"
        )

    # Subagent reports
    sections.append("## Specialist Agent Reports\n")
    for i, report in enumerate(sup_input.subagent_reports):
        if report.parse_failed:
            sections.append(
                f"### Report {i + 1}: {report.role} (PARSE FAILED -- raw text)\n{report.raw_text[:3000]}\n"
            )
        else:
            sections.append(
                f"### Report {i + 1}: {report.role}\n```json\n{json.dumps(report.parsed, indent=2)[:5000]}\n```\n"
            )

    sections.append(
        "## Your Task\n"
        "Synthesize the above reports and data into a comprehensive PR analysis "
        "following your system prompt structure. Use your tools to investigate "
        "anything that seems incomplete or contradictory."
    )

    return "\n\n".join(sections)
