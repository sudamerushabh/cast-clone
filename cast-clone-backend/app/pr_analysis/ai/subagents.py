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


def _serialize_content_for_api(content) -> list[dict]:
    """Serialize response content blocks to plain dicts for the Messages API.

    The SDK returns Pydantic objects (TextBlock, ToolUseBlock) that may
    contain extra fields (e.g. 'caller' in Sonnet 4.6) which the API
    rejects when sent back as conversation history. This function
    converts each block to a minimal dict with only the fields the
    API expects.
    """
    blocks = []
    for block in content:
        if hasattr(block, "type"):
            block_type = block.type if isinstance(block.type, str) else str(block.type)
        elif isinstance(block, dict):
            block_type = block.get("type", "text")
        else:
            blocks.append({"type": "text", "text": str(block)})
            continue

        if block_type == "text":
            text = block.text if hasattr(block, "text") else block.get("text", "")
            blocks.append({"type": "text", "text": text})
        elif block_type == "tool_use":
            b = {
                "type": "tool_use",
                "id": block.id if hasattr(block, "id") else block["id"],
                "name": block.name if hasattr(block, "name") else block["name"],
                "input": block.input if hasattr(block, "input") else block["input"],
            }
            blocks.append(b)
        else:
            # Unknown block type — try model_dump or pass as-is
            if hasattr(block, "model_dump"):
                d = block.model_dump(exclude_none=True)
                d.pop("caller", None)
                blocks.append(d)
            elif isinstance(block, dict):
                d = {k: v for k, v in block.items() if k != "caller"}
                blocks.append(d)
    return blocks


def _summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    """Create a human-readable one-line summary of a tool call's input."""
    if tool_name == "read_file":
        return tool_input.get("path", "?")
    elif tool_name == "search_files":
        return f"pattern={tool_input.get('pattern', '?')}"
    elif tool_name == "grep_content":
        return f"pattern={tool_input.get('pattern', '?')} glob={tool_input.get('glob', '*')}"
    elif tool_name == "list_directory":
        return tool_input.get("path", ".")
    elif tool_name == "query_graph_node":
        return tool_input.get("fqn", "?")
    elif tool_name == "get_node_impact":
        return f"fqn={tool_input.get('fqn', '?')} direction={tool_input.get('direction', '?')}"
    elif tool_name == "find_path":
        return f"{tool_input.get('from_fqn', '?')} → {tool_input.get('to_fqn', '?')}"
    elif tool_name == "dispatch_subagent":
        return f"role={tool_input.get('role', '?')} prompt={str(tool_input.get('prompt', ''))[:80]}"
    else:
        return str(tool_input)[:100]


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
    timeout: int = 300,
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
            remaining = timeout - elapsed
            if remaining <= 0:
                return AgentResult(
                    role=config.role,
                    final_text=f"Agent timed out after {timeout}s",
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens,
                    duration_ms=int(elapsed * 1000),
                    error="timeout",
                )

            # Use streaming to support large max_tokens (>10min generation)
            async with client.messages.stream(
                model=model,
                system=config.system_prompt,
                messages=messages,
                tools=tool_defs if tool_defs else None,
                max_tokens=65536,
            ) as stream:
                response = await asyncio.wait_for(
                    stream.get_final_message(),
                    timeout=max(remaining, 5),
                )

            total_tokens += response.usage.input_tokens + response.usage.output_tokens

            logger.info(
                "agent_llm_response",
                role=config.role,
                stop_reason=response.stop_reason,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                content_blocks=len(response.content),
            )

            # If agent is done (text response) -- return
            if response.stop_reason == "end_turn" or response.stop_reason != "tool_use":
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text += block.text
                logger.info(
                    "agent_finished",
                    role=config.role,
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    summary_len=len(text),
                )
                return AgentResult(
                    role=config.role,
                    final_text=text,
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            # Process tool calls — serialize content to plain dicts
            messages.append({
                "role": "assistant",
                "content": _serialize_content_for_api(response.content),
            })
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    # Log the tool call with a human-readable summary of the input
                    tool_input_summary = _summarize_tool_input(block.name, block.input)
                    if tool_calls_made >= config.max_tool_calls:
                        logger.warning(
                            "agent_tool_limit_reached",
                            role=config.role,
                            tool=block.name,
                            input_summary=tool_input_summary,
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": '{"error": "Tool call limit reached. Please emit your final report now."}',
                            "is_error": True,
                        })
                    else:
                        logger.info(
                            "agent_tool_call",
                            role=config.role,
                            tool=block.name,
                            call_num=tool_calls_made + 1,
                            input_summary=tool_input_summary,
                        )
                        result = await handle_tool_call(ctx, block.name, block.input)
                        result_preview = result[:200] if isinstance(result, str) else str(result)[:200]
                        logger.info(
                            "agent_tool_result",
                            role=config.role,
                            tool=block.name,
                            result_len=len(result) if isinstance(result, str) else 0,
                            result_preview=result_preview,
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                        tool_calls_made += 1

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
