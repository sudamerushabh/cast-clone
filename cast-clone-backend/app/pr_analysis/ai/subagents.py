"""Shared agentic loop runner for the AI pipeline.

All agents (subagents and supervisor) use this same loop.
Each agent gets its own Anthropic API call chain and tool execution context.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import structlog

from app.pr_analysis.ai.tool_context import ToolContext
from app.pr_analysis.ai.tools import get_tool_definitions, handle_tool_call

logger = structlog.get_logger(__name__)


@dataclass
class AgentConfig:
    """Configuration for an agent run."""
    role: str
    system_prompt: str
    initial_message: str
    tools: list[str]          # Tool names this agent can use
    max_tool_calls: int = 25


@dataclass
class AgentResult:
    """Result of a completed agent run."""
    role: str
    final_text: str
    tool_calls_made: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    error: str | None = None


async def run_agent(
    client,  # AsyncAnthropicBedrock instance
    config: AgentConfig,
    ctx: ToolContext,
    model: str,
    timeout: int = 120,
) -> AgentResult:
    """Run an agentic loop: call LLM -> execute tool calls -> repeat -> return final text.

    Args:
        client: Anthropic Bedrock async client.
        config: Agent role, prompt, tools, limits.
        ctx: Shared tool context (repo path, graph store).
        model: Bedrock model ID.
        timeout: Max wall-clock seconds for this agent.

    Returns:
        AgentResult with the agent's final text and metadata.
    """
    start = time.monotonic()
    messages: list[dict] = [{"role": "user", "content": config.initial_message}]

    # Filter tool definitions to only what this agent can use
    all_defs = get_tool_definitions(include_dispatch=False)
    tool_defs = [d for d in all_defs if d["name"] in config.tools]

    tool_calls_made = 0
    total_tokens = 0

    try:
        while True:
            # Check timeout
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                return AgentResult(
                    role=config.role,
                    final_text=f"Agent timed out after {timeout}s",
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens,
                    duration_ms=int(elapsed * 1000),
                    error="timeout",
                )

            response = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    system=config.system_prompt,
                    messages=messages,
                    tools=tool_defs if tool_defs else None,
                    max_tokens=4096,
                ),
                timeout=max(timeout - elapsed, 5),
            )

            total_tokens += response.usage.input_tokens + response.usage.output_tokens

            # If agent is done (text response) -- return
            if response.stop_reason == "end_turn" or response.stop_reason != "tool_use":
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text += block.text
                return AgentResult(
                    role=config.role,
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
                    if tool_calls_made >= config.max_tool_calls:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": '{"error": "Tool call limit reached. Please emit your final report now."}',
                            "is_error": True,
                        })
                    else:
                        result = await handle_tool_call(ctx, block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                        tool_calls_made += 1

                        logger.debug(
                            "agent_tool_call",
                            role=config.role,
                            tool=block.name,
                            calls_made=tool_calls_made,
                        )

            messages.append({"role": "user", "content": tool_results})

    except asyncio.TimeoutError:
        return AgentResult(
            role=config.role,
            final_text="Agent timed out",
            tool_calls_made=tool_calls_made,
            total_tokens=total_tokens,
            duration_ms=int((time.monotonic() - start) * 1000),
            error="timeout",
        )
    except Exception as exc:
        logger.error("agent_failed", role=config.role, error=str(exc), exc_info=True)
        return AgentResult(
            role=config.role,
            final_text=f"Agent failed: {exc}",
            tool_calls_made=tool_calls_made,
            total_tokens=total_tokens,
            duration_ms=int((time.monotonic() - start) * 1000),
            error=str(exc),
        )
