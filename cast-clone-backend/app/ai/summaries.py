# app/ai/summaries.py
"""AI summary generation with PostgreSQL caching.

Generates natural-language explanations of code objects using a single
Claude Sonnet call. Caches results with graph-hash invalidation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from anthropic import AsyncAnthropicBedrock
from openai import AsyncOpenAI
from sqlalchemy import select

from app.ai.tools import ChatToolContext, get_source_code, object_details
from app.models.db import AiSummary
from app.services.ai_provider import EffectiveAiConfig

logger = structlog.get_logger(__name__)

SUMMARY_SYSTEM_PROMPT = (
    "You are an expert software architect. Explain what this code "
    "object does, its role in the architecture, and its key "
    "dependencies.\n\n"
    "Be concise (2-3 paragraphs). Reference specific class/method "
    "names. Focus on: what it does, who calls it, what it calls, "
    "and why it matters."
)


async def compute_graph_hash(ctx: ChatToolContext, node_fqn: str) -> str:
    """Compute SHA-256 hash of a node's graph neighborhood.

    Hash = SHA-256(fan_in:fan_out:sorted_neighbor_fqns)
    Changes when callers/callees change, triggering summary regeneration.
    """
    callers = await ctx.graph_store.query(
        "MATCH (caller)-[:CALLS]->(n {fqn: $fqn, app_name: $app_name}) "
        "RETURN caller.fqn AS fqn",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )
    callees = await ctx.graph_store.query(
        "MATCH (n {fqn: $fqn, app_name: $app_name})-[:CALLS]->(callee) "
        "RETURN callee.fqn AS fqn",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )
    fan_in = len(callers)
    fan_out = len(callees)
    neighbor_fqns = sorted([r["fqn"] for r in callers] + [r["fqn"] for r in callees])
    raw = f"{fan_in}:{fan_out}:{','.join(neighbor_fqns)}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def assemble_node_context(
    ctx: ChatToolContext,
    node_fqn: str,
    neighbor_limit: int = 20,
) -> dict[str, Any] | None:
    """Assemble structured context about a node for the summary prompt.

    Uses shared tool functions to fetch details and source code.
    Caps callers/callees at neighbor_limit (default 20).
    """
    details = await object_details(ctx, node_fqn=node_fqn)
    if details["node"] is None:
        return None

    callers = details["callers"][:neighbor_limit]
    callees = details["callees"][:neighbor_limit]

    result: dict[str, Any] = {
        "node": details["node"],
        "callers": callers,
        "callees": callees,
    }

    source = await get_source_code(ctx, node_fqn=node_fqn)
    if source.get("code"):
        result["source_code"] = source["code"]

    return result


async def generate_summary(
    client: AsyncAnthropicBedrock | AsyncOpenAI,
    model: str,
    max_tokens: int,
    node_context: dict[str, Any],
    ai_config: EffectiveAiConfig | None = None,
) -> tuple[str, int]:
    """Make a single AI call to generate a node summary.

    Supports both Anthropic (Bedrock) and OpenAI providers.
    Returns (summary_text, total_tokens_used).
    """
    user_content = json.dumps(node_context, default=str)

    if isinstance(client, AsyncOpenAI):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        }
        if ai_config and ai_config.temperature != 1.0:
            kwargs["temperature"] = ai_config.temperature
        response = await client.chat.completions.create(**kwargs)
        summary_text = response.choices[0].message.content or ""
        usage = response.usage
        tokens_used = (
            (
                (usage.prompt_tokens or 0)
                + (usage.completion_tokens or 0)
            )
            if usage
            else 0
        )
        return summary_text, tokens_used

    # Anthropic / Bedrock path
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    summary_text = response.content[0].text
    tokens_used = response.usage.input_tokens + response.usage.output_tokens
    return summary_text, tokens_used


async def get_or_create_summary(
    ctx: ChatToolContext,
    node_fqn: str,
    client: AsyncAnthropicBedrock | AsyncOpenAI,
    model: str,
    max_tokens: int,
    ai_config: EffectiveAiConfig | None = None,
) -> dict[str, Any]:
    """Get cached summary or generate a new one.

    Cache invalidation: compares SHA-256 graph hash of the node's
    neighborhood. If hash matches cached value, returns cache.
    Otherwise regenerates and upserts.
    """
    session = ctx.db_session
    current_hash = await compute_graph_hash(ctx, node_fqn)

    # Check cache
    result = await session.execute(
        select(AiSummary).where(
            AiSummary.project_id == ctx.project_id,
            AiSummary.node_fqn == node_fqn,
        )
    )
    cached = result.scalar_one_or_none()

    if cached and cached.graph_hash == current_hash:
        logger.info("summary.cache_hit", node_fqn=node_fqn)
        return {
            "fqn": node_fqn,
            "summary": cached.summary,
            "cached": True,
            "model": cached.model,
            "tokens_used": cached.tokens_used,
        }

    # Cache miss or stale -- generate
    node_context = await assemble_node_context(ctx, node_fqn)
    if node_context is None:
        return {"fqn": node_fqn, "error": f"Node not found: {node_fqn}"}

    logger.info(
        "summary.generating",
        node_fqn=node_fqn,
        reason="stale" if cached else "miss",
    )
    summary_text, tokens_used = await generate_summary(
        client=client,
        model=model,
        max_tokens=max_tokens,
        node_context=node_context,
        ai_config=ai_config,
    )

    # Upsert via SQLAlchemy dialect-specific insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = (
        pg_insert(AiSummary)
        .values(
            project_id=ctx.project_id,
            node_fqn=node_fqn,
            summary=summary_text,
            model=model,
            graph_hash=current_hash,
            tokens_used=tokens_used,
        )
        .on_conflict_do_update(
            index_elements=["project_id", "node_fqn"],
            set_={
                "summary": summary_text,
                "model": model,
                "graph_hash": current_hash,
                "tokens_used": tokens_used,
            },
        )
    )
    await session.execute(stmt)
    await session.commit()

    return {
        "fqn": node_fqn,
        "summary": summary_text,
        "cached": False,
        "model": model,
        "tokens_used": tokens_used,
    }


TRACE_SUMMARY_SYSTEM_PROMPT = (
    "You are an expert software architect analyzing a code "
    "execution trace.\n"
    "Describe the flow in 2-3 concise paragraphs:\n"
    "- Name specific classes and methods\n"
    "- State which architectural layers are involved\n"
    "- Mention database tables touched and whether they are "
    "read or written\n"
    "- Note any patterns: fan-out, circular calls, "
    "cross-layer shortcuts\n"
    "Use markdown formatting. Be specific, not generic."
)


def compute_trace_hash(trace_context: dict[str, Any]) -> str:
    """Compute SHA-256 hash of trace topology for caching."""
    center = trace_context["center"]["fqn"]
    up = sorted(n["fqn"] for n in trace_context["upstream"])
    down = sorted(
        n["fqn"] for n in trace_context["downstream"]
    )
    raw = f"{center}:{','.join(up)}:{','.join(down)}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def generate_trace_summary_text(
    client: AsyncAnthropicBedrock | AsyncOpenAI,
    model: str,
    max_tokens: int,
    trace_context: dict[str, Any],
    ai_config: EffectiveAiConfig | None = None,
) -> tuple[str, int]:
    """Call the LLM to generate a trace flow summary.

    Same dual-provider pattern as generate_summary().
    Returns (summary_text, tokens_used).
    """
    user_content = json.dumps(trace_context, default=str)

    if isinstance(client, AsyncOpenAI):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": TRACE_SUMMARY_SYSTEM_PROMPT,
                },
                {"role": "user", "content": user_content},
            ],
        }
        if ai_config and ai_config.temperature != 1.0:
            kwargs["temperature"] = ai_config.temperature
        response = await client.chat.completions.create(
            **kwargs
        )
        text = response.choices[0].message.content or ""
        usage = response.usage
        tokens = (
            (
                (usage.prompt_tokens or 0)
                + (usage.completion_tokens or 0)
            )
            if usage
            else 0
        )
        return text, tokens

    # Anthropic / Bedrock path
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=TRACE_SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    text = response.content[0].text
    tokens = (
        response.usage.input_tokens
        + response.usage.output_tokens
    )
    return text, tokens
