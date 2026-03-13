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
from app.pr_analysis.ai.subagents import AgentConfig, AgentResult, run_agent, _serialize_content_for_api
from app.pr_analysis.ai.tool_context import ToolContext
from app.pr_analysis.ai.tools import (
    VALID_TOOL_NAMES,
    get_tool_definitions,
    handle_tool_call,
)
from app.pr_analysis.models import (
    AggregatedImpact,
    DriftReport,
    PRDiff,
    PullRequestEvent,
)

logger = structlog.get_logger(__name__)

_SUPERVISOR_MAX_TOOL_CALLS = 50
_SUPERVISOR_TIMEOUT = 600  # 10 minutes — supervisor synthesizes large subagent reports


@dataclass
class SupervisorInput:
    """All data the supervisor needs to generate the final summary."""

    subagent_reports: list[AgentReport]
    pr_event: PullRequestEvent
    diff: PRDiff  # Full diff data for supervisor-first design
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

    logger.info(
        "supervisor_started",
        pr_number=sup_input.pr_event.pr_number,
        changed_files=sup_input.diff.total_files_changed,
        changed_nodes=len(sup_input.impact.changed_nodes),
        blast_radius=sup_input.impact.total_blast_radius,
        risk=sup_input.risk_level,
        context_chars=len(initial_message),
    )

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

            async with client.messages.stream(
                model=model,
                system=SUPERVISOR_PROMPT,
                messages=messages,
                tools=all_tool_defs,
                max_tokens=65536,
            ) as stream:
                response = await asyncio.wait_for(
                    stream.get_final_message(),
                    timeout=max(_SUPERVISOR_TIMEOUT - elapsed, 10),
                )

            total_tokens += response.usage.input_tokens + response.usage.output_tokens

            # Log any text the supervisor is thinking
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    logger.info(
                        "supervisor_thinking",
                        text_preview=block.text[:300],
                    )

            logger.info(
                "supervisor_llm_response",
                stop_reason=response.stop_reason,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                tool_calls_in_response=sum(1 for b in response.content if b.type == "tool_use"),
                total_tool_calls=tool_calls_made,
            )

            if response.stop_reason == "end_turn" or response.stop_reason != "tool_use":
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text += block.text
                logger.info(
                    "supervisor_finished",
                    tool_calls_made=tool_calls_made,
                    subagents_dispatched=subagents_dispatched,
                    total_tokens=total_tokens,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    summary_len=len(text),
                )
                return AgentResult(
                    role="supervisor",
                    final_text=text,
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            # Process tool calls — serialize to plain dicts
            messages.append({"role": "assistant", "content": _serialize_content_for_api(response.content)})
            tool_results = []

            from app.pr_analysis.ai.subagents import _summarize_tool_input

            for block in response.content:
                if block.type == "tool_use":
                    tool_summary = _summarize_tool_input(block.name, block.input)
                    if tool_calls_made >= _SUPERVISOR_MAX_TOOL_CALLS:
                        logger.warning("supervisor_tool_limit", tool=block.name)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": '{"error": "Tool call limit (50) reached. Emit your final summary now."}',
                            "is_error": True,
                        })
                    elif block.name == "dispatch_subagent":
                        logger.info(
                            "supervisor_dispatch_subagent",
                            subagent_role=block.input.get("role", "?"),
                            prompt_preview=str(block.input.get("prompt", ""))[:150],
                            subagent_num=subagents_dispatched + 1,
                        )
                        result = await _handle_dispatch(
                            client, block.input, ctx, model, settings, subagents_dispatched,
                        )
                        logger.info(
                            "supervisor_subagent_returned",
                            subagent_role=block.input.get("role", "?"),
                            result_len=len(result),
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                        tool_calls_made += 1
                        subagents_dispatched += 1
                    else:
                        logger.info(
                            "supervisor_tool_call",
                            tool=block.name,
                            call_num=tool_calls_made + 1,
                            input_summary=tool_summary,
                        )
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
    if dispatched_count >= 5:  # Max 5 subagents
        return json.dumps({"error": "Ad-hoc subagent budget exceeded (max 5). Use your existing tools."})

    role = tool_input.get("role", "ad_hoc")
    prompt = tool_input.get("prompt", "")

    logger.info("supervisor_dispatching_subagent", role=role)

    # If no specific tools requested, give all tools
    if not requested_tools:
        requested_tools = list(VALID_TOOL_NAMES)

    config = AgentConfig(
        role=f"adhoc_{role}",
        system_prompt=f"You are a focused investigator. Your task:\n{prompt}\n\nUse your tools to find the answer. Be efficient — aim for 8-12 tool calls max. Return your findings as clear text.",
        initial_message=prompt,
        tools=requested_tools,
        max_tool_calls=25,
    )

    result = await run_agent(client, config, ctx, model=model, timeout=300)
    return result.final_text


def _build_supervisor_context(sup_input: SupervisorInput) -> str:
    """Assemble the initial message for the supervisor from all data."""
    sections = []

    # PR metadata
    ev = sup_input.pr_event
    pr_desc = ev.pr_description[:2000] if ev.pr_description else "None"
    sections.append(
        f"## Pull Request\n"
        f"- **Title:** {ev.pr_title}\n"
        f"- **Author:** {ev.author}\n"
        f"- **Branch:** {ev.source_branch} -> {ev.target_branch}\n"
        f"- **Description:** {pr_desc}\n"
        f"- **Risk Classification:** {sup_input.risk_level}"
    )

    # Diff summary — list of changed files with status
    diff = sup_input.diff
    file_lines = []
    for f in diff.files:
        file_lines.append(f"- `{f.path}` ({f.status}, +{f.additions}/-{f.deletions})")
    sections.append(
        f"## Changed Files ({diff.total_files_changed} files, "
        f"+{diff.total_additions}/-{diff.total_deletions})\n" +
        "\n".join(file_lines)
    )

    # Impact summary
    impact = sup_input.impact
    changed_nodes_list = "\n".join(
        f"- `{n.fqn}` ({n.type}, change: {n.change_type})"
        for n in impact.changed_nodes[:30]
    )
    sections.append(
        f"## Impact Data (deterministic graph analysis)\n"
        f"- **Total blast radius:** {impact.total_blast_radius} unique affected nodes\n"
        f"- **Changed nodes:** {len(impact.changed_nodes)}\n"
        f"- **By type:** {json.dumps(impact.by_type)}\n"
        f"- **By depth:** {json.dumps({str(k): v for k, v in impact.by_depth.items()})}\n"
        f"- **Cross-tech impacts:** {len(impact.cross_tech_impacts)}\n"
        f"- **Transactions affected:** {len(impact.transactions_affected)}\n\n"
        f"### Changed Nodes\n{changed_nodes_list}"
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

    # Include subagent reports if any were provided (supports hybrid usage)
    if sup_input.subagent_reports:
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

    # Instructions
    sections.append(
        "## Your Task\n"
        "Analyze this PR using your tools. Read the changed files, query the graph, "
        "and produce your comprehensive analysis. If you need deeper investigation "
        "of a specific area, use dispatch_subagent to delegate.\n\n"
        "Start by reading the most critical changed files to understand what the PR actually does."
    )

    return "\n\n".join(sections)
