# app/ai/chat.py
"""Agentic chat service — runs a Claude Sonnet agent loop with SSE streaming.

The agent has access to architecture graph tools and streams thinking blocks,
tool calls, and responses as SSE events.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator

import structlog
from anthropic import AsyncAnthropicBedrock

from app.ai.tool_definitions import get_chat_tool_definitions
from app.ai.tools import (
    ChatToolContext,
    application_stats,
    find_path,
    get_architecture,
    get_source_code,
    impact_analysis,
    list_applications,
    list_transactions,
    object_details,
    search_objects,
    transaction_graph,
)
from app.config import get_settings
from app.schemas.chat import PageContext

logger = structlog.get_logger(__name__)

# Map tool names to handler functions
_TOOL_HANDLERS = {
    "list_applications": lambda ctx, inp: list_applications(ctx),
    "application_stats": lambda ctx, inp: application_stats(
        ctx, app_name=inp.get("app_name")
    ),
    "get_architecture": lambda ctx, inp: get_architecture(
        ctx, level=inp.get("level", "module")
    ),
    "search_objects": lambda ctx, inp: search_objects(
        ctx, query=inp["query"], type_filter=inp.get("type_filter")
    ),
    "object_details": lambda ctx, inp: object_details(ctx, node_fqn=inp["node_fqn"]),
    "impact_analysis": lambda ctx, inp: impact_analysis(
        ctx,
        node_fqn=inp["node_fqn"],
        depth=inp.get("depth", 5),
        direction=inp.get("direction", "both"),
    ),
    "find_path": lambda ctx, inp: find_path(
        ctx, from_fqn=inp["from_fqn"], to_fqn=inp["to_fqn"]
    ),
    "list_transactions": lambda ctx, inp: list_transactions(ctx),
    "transaction_graph": lambda ctx, inp: transaction_graph(
        ctx, transaction_name=inp["transaction_name"]
    ),
    "get_source_code": lambda ctx, inp: get_source_code(ctx, node_fqn=inp["node_fqn"]),
}


def build_system_prompt(
    app_name: str,
    frameworks: list[str],
    languages: list[str],
    page_context: PageContext | None,
) -> str:
    """Build the system prompt with optional page context."""
    parts = [
        f'You are an expert software architect analyzing the application "{app_name}".',
    ]
    if frameworks:
        parts.append(f"The application is built with {', '.join(frameworks)}.")
    if languages:
        parts.append(f"Languages: {', '.join(languages)}.")
    parts.append(
        "You have access to the application's complete "
        "architecture graph via the provided tools."
    )

    if page_context:
        ctx_parts = []
        if page_context.view:
            ctx_parts.append(f"the {page_context.view} view")
        if page_context.level:
            ctx_parts.append(f"at {page_context.level} level")
        if page_context.page:
            ctx_parts.append(f"on the {page_context.page} page")

        location = " ".join(ctx_parts) if ctx_parts else page_context.page
        parts.append(f"\nThe user is currently viewing {location}.")
        if page_context.selected_node_fqn:
            parts.append(
                f"They have selected the node: {page_context.selected_node_fqn}"
            )
        parts.append(
            "Use this context to make your answers "
            "more relevant to what they're looking at."
        )

    parts.append(
        "\nWhen answering questions:\n"
        "- Use tools to look up real data. Don't guess about the architecture.\n"
        "- Be specific — reference actual class names, method names, and file paths.\n"
        "- Include FQNs when mentioning code objects so the UI can link to them.\n"
        "- If a question is ambiguous, search first to find "
        "relevant nodes, then get details."
    )
    return "\n".join(parts)


async def execute_tool_call(
    ctx: ChatToolContext, tool_name: str, tool_input: dict
) -> str:
    """Execute a tool call and return a JSON string result."""
    handler = _TOOL_HANDLERS.get(tool_name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        result = await handler(ctx, tool_input)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("chat_tool_failed", tool=tool_name, error=str(exc))
        return json.dumps({"error": f"Tool {tool_name} failed: {str(exc)}"})


def _serialize_content(content) -> list[dict]:
    """Serialize response content blocks to plain dicts for the API."""
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
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id if hasattr(block, "id") else block["id"],
                    "name": block.name if hasattr(block, "name") else block["name"],
                    "input": block.input if hasattr(block, "input") else block["input"],
                }
            )
        elif block_type == "thinking":
            blocks.append(
                {
                    "type": "thinking",
                    "thinking": block.thinking
                    if hasattr(block, "thinking")
                    else block.get("thinking", ""),
                }
            )
    return blocks


def _sse_event(event: str, data: dict) -> str:
    """Format an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def chat_stream(
    ctx: ChatToolContext,
    message: str,
    history: list[dict],
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    """Run the agentic chat loop and yield SSE events.

    Yields events:
        thinking  — extended thinking content
        tool_use  — tool name + input
        tool_result — summarized tool result
        text      — streaming text response
        done      — completion with token usage
        error     — error message
    """
    settings = get_settings()
    client = AsyncAnthropicBedrock(aws_region=settings.aws_region)
    tool_defs = get_chat_tool_definitions()

    messages = list(history) + [{"role": "user", "content": message}]
    tool_calls_made = 0
    total_input_tokens = 0
    total_output_tokens = 0
    start = time.monotonic()

    try:
        while True:
            elapsed = time.monotonic() - start
            if elapsed > settings.chat_timeout_seconds:
                yield _sse_event("error", {"message": "Chat timed out"})
                break

            response = await asyncio.wait_for(
                client.messages.create(
                    model=settings.chat_model,
                    max_tokens=settings.chat_max_response_tokens,
                    system=system_prompt,
                    tools=tool_defs,
                    messages=messages,
                    thinking={
                        "type": "enabled",
                        "budget_tokens": settings.chat_thinking_budget_tokens,
                    },
                ),
                timeout=max(settings.chat_timeout_seconds - elapsed, 10),
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Emit events for each content block
            for block in response.content:
                if hasattr(block, "type"):
                    block_type = (
                        block.type if isinstance(block.type, str) else str(block.type)
                    )
                else:
                    continue

                if block_type == "thinking":
                    thinking_text = block.thinking if hasattr(block, "thinking") else ""
                    if thinking_text:
                        yield _sse_event("thinking", {"content": thinking_text})

                elif block_type == "text" and hasattr(block, "text") and block.text:
                    yield _sse_event("text", {"content": block.text})

                elif block_type == "tool_use":
                    yield _sse_event(
                        "tool_use",
                        {
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        },
                    )

            # If no tool calls, we're done
            if response.stop_reason != "tool_use":
                break

            # Process tool calls
            messages.append(
                {"role": "assistant", "content": _serialize_content(response.content)}
            )
            tool_results = []

            for block in response.content:
                block_type = (
                    block.type
                    if hasattr(block, "type") and isinstance(block.type, str)
                    else ""
                )
                if block_type != "tool_use":
                    continue

                if tool_calls_made >= settings.chat_max_tool_calls:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(
                                {
                                    "error": "Tool call limit reached. "
                                    "Please provide your answer now."
                                }
                            ),
                            "is_error": True,
                        }
                    )
                    yield _sse_event(
                        "tool_result",
                        {
                            "tool_use_id": block.id,
                            "content_summary": "Tool limit reached",
                        },
                    )
                    continue

                result = await execute_tool_call(ctx, block.name, block.input)
                tool_calls_made += 1

                # Truncate large results for the SSE event (frontend display)
                summary = result[:500] + "..." if len(result) > 500 else result
                yield _sse_event(
                    "tool_result",
                    {
                        "tool_use_id": block.id,
                        "content_summary": summary,
                    },
                )

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        yield _sse_event(
            "done",
            {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "tool_calls": tool_calls_made,
                "duration_ms": int((time.monotonic() - start) * 1000),
            },
        )

    except TimeoutError:
        yield _sse_event("error", {"message": "Chat request timed out"})
    except asyncio.CancelledError:
        logger.info("chat_stream_cancelled")
        raise
    except Exception as exc:
        logger.error("chat_stream_error", error=str(exc), exc_info=True)
        yield _sse_event("error", {"message": f"Chat error: {str(exc)}"})
