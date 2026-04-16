# tests/unit/test_chat_error_redaction.py
"""Ensure tool-call exception strings do not leak to SSE output.

The agentic chat service (app.ai.chat) executes tools inside a streaming
SSE loop. If a tool raises, the exception string historically flowed into
the SSE event payload, leaking internal paths, database hostnames, API
tokens, and stack frames to end users. This test pins the redaction in
place: the full exception must be logged server-side, but the payload
returned to the stream must contain only a generic user-facing message.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.ai import chat as chat_module
from app.ai.chat import execute_tool_call
from app.ai.tools import ChatToolContext

# A string that would only appear if the raw exception's message reached
# the SSE consumer. Used as a canary to detect leaks.
_SENSITIVE_HOSTNAME = "internal-db-hostname"
_POISON_TOOL_NAME = "poison"


def _poison_handler(_ctx, _inp):
    """Tool handler that raises an exception containing internal details."""
    raise RuntimeError(
        f"connection to postgres://{_SENSITIVE_HOSTNAME}:5432/cast failed "
        "at /app/services/postgres.py:42"
    )


@pytest.fixture
def poisoned_registry(monkeypatch):
    """Register a tool whose handler always raises with sensitive content."""
    # The real handler map is an async lambda wrapper; match that shape.
    async def _async_poison(ctx, inp):
        return _poison_handler(ctx, inp)

    # Mutate a fresh copy so we don't leak state across tests.
    patched = dict(chat_module._TOOL_HANDLERS)
    patched[_POISON_TOOL_NAME] = lambda ctx, inp: _async_poison(ctx, inp)
    monkeypatch.setattr(chat_module, "_TOOL_HANDLERS", patched)
    return patched


@pytest.fixture
def ctx() -> ChatToolContext:
    return ChatToolContext(
        graph_store=AsyncMock(),
        app_name="test-app",
        project_id="proj-123",
    )


@pytest.mark.asyncio
async def test_execute_tool_call_redacts_exception_message(
    poisoned_registry, ctx: ChatToolContext
) -> None:
    """A raising tool must not have its exception text leak to the caller.

    ``execute_tool_call`` is the single code path that yields a tool's
    result (or its error payload) into the SSE stream. Any leak here shows
    up in the tool_result event.
    """
    raw = await execute_tool_call(ctx, _POISON_TOOL_NAME, {})

    # The wire format is a JSON string; parse before asserting.
    parsed = json.loads(raw)

    # An error signal must be present so the model knows the tool failed.
    assert "error" in parsed, f"expected error key in payload, got: {parsed}"

    # The error message must be a generic, redacted string.
    assert parsed["error"] == "Tool call failed. Please try again."

    # No exception-derived content anywhere in the raw wire string.
    assert _SENSITIVE_HOSTNAME not in raw
    assert "RuntimeError" not in raw
    assert "/app/" not in raw
    assert "postgres://" not in raw
    assert "5432" not in raw
    # Tool name itself is also no longer formatted into the error (avoids
    # echoing back attacker-controlled tool names if a registry is ever
    # extended dynamically). Pin the current behaviour.
    assert _POISON_TOOL_NAME not in parsed["error"]


@pytest.mark.asyncio
async def test_execute_tool_call_logs_full_exception_server_side(
    poisoned_registry, ctx: ChatToolContext, monkeypatch
) -> None:
    """The raw exception must still reach server logs for debugging.

    Redaction is only for the wire — operators need the full traceback and
    message in logs. We spy on the module-level structlog logger to verify
    ``logger.exception`` is invoked with the structured event name.
    """
    captured: list[tuple[str, dict]] = []

    class _SpyLogger:
        def exception(self, event: str, **kwargs: object) -> None:
            captured.append((event, dict(kwargs)))

        # No-op shims so other chat code paths using the logger don't
        # explode if they run during this test.
        def info(self, *a: object, **kw: object) -> None:
            pass

        def error(self, *a: object, **kw: object) -> None:
            pass

    monkeypatch.setattr(chat_module, "logger", _SpyLogger())

    await execute_tool_call(ctx, _POISON_TOOL_NAME, {})

    assert any(
        event == "chat_tool_failed" for event, _ in captured
    ), f"expected logger.exception('chat_tool_failed', ...) to be called, got {captured}"
    # The structured fields should identify the failing tool and project
    # without leaking the exception message itself into the log event args
    # (structlog adds traceback via exc_info handling).
    _event, fields = next((e, f) for e, f in captured if e == "chat_tool_failed")
    assert fields.get("tool") == _POISON_TOOL_NAME
    assert fields.get("project_id") == "proj-123"


@pytest.mark.asyncio
async def test_unknown_tool_error_does_not_echo_input(ctx: ChatToolContext) -> None:
    """Unknown-tool errors (separate code path) must not echo arbitrary
    input either. The current behaviour names the missing tool, which is
    safe since tool names come from the model's tool_use block, not user
    free text. This test pins that contract so future refactors don't
    accidentally start echoing ``tool_input`` values.
    """
    raw = await execute_tool_call(ctx, "nonexistent_tool", {"secret": "s3cr3t"})
    assert "s3cr3t" not in raw
    parsed = json.loads(raw)
    assert "error" in parsed
