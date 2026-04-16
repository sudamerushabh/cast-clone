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
    input OR the tool name. Tool names are model-controlled and could in
    principle be poisoned via prompt injection; never reflect them into
    the SSE payload. The tool name is logged server-side via structlog.
    """
    raw = await execute_tool_call(
        ctx, "nonexistent_tool_with_secret_name", {"secret": "s3cr3t"}
    )
    assert "s3cr3t" not in raw
    # Tool name must NOT appear in the wire payload.
    assert "nonexistent_tool_with_secret_name" not in raw
    parsed = json.loads(raw)
    assert parsed == {"error": "Unknown tool requested"}


# ---------------------------------------------------------------------------
# Stream-level exception redaction (Bedrock + OpenAI paths)
# ---------------------------------------------------------------------------

_SENSITIVE_STREAM_MARKER = "super-secret-bedrock-endpoint-47.internal"
_SENSITIVE_OPENAI_MARKER = "sk-leakedOpenAIApiKey-deadbeef"


def _make_ai_config(provider: str = "openai") -> object:
    """Build a minimal EffectiveAiConfig for stream tests.

    Real construction requires many fields; we use SimpleNamespace so tests
    don't break when the dataclass grows. The stream code only reads a few
    attributes (provider, chat_model, chat_timeout_seconds, max_tool_calls,
    max_response_tokens, temperature, top_p, thinking_budget_tokens).
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        provider=provider,
        aws_region="us-east-1",
        bedrock_use_iam_role=True,
        aws_access_key_id=None,
        aws_secret_access_key=None,
        openai_api_key=None,
        openai_base_url=None,
        chat_model="test-model",
        pr_analysis_model="test-model",
        summary_model="test-model",
        temperature=1.0,
        top_p=1.0,
        max_response_tokens=1024,
        thinking_budget_tokens=1024,
        chat_timeout_seconds=60,
        max_tool_calls=5,
        cost_input_per_mtok=0.0,
        cost_output_per_mtok=0.0,
    )


async def _collect_stream(gen) -> list[str]:
    events: list[str] = []
    async for evt in gen:
        events.append(evt)
    return events


@pytest.mark.asyncio
async def test_anthropic_stream_exception_redacted(
    ctx: ChatToolContext, monkeypatch
) -> None:
    """Bedrock/Anthropic stream path: an exception raised by the underlying
    ``messages.create`` must NOT reach the SSE consumer. The generic
    ``Chat error. Please try again.`` message is yielded instead.
    """
    # Build a fake client whose messages.create raises with a sensitive
    # string in the exception message.
    class _FakeMessages:
        async def create(self, **_kwargs):
            raise RuntimeError(
                f"bedrock connect failed to {_SENSITIVE_STREAM_MARKER} "
                "with aws_secret=AKIAXXXXXXXXXXXXXXX"
            )

    class _FakeBedrockClient:
        def __init__(self) -> None:
            self.messages = _FakeMessages()

    # Force the Bedrock branch: ai_config=None uses env-var fallback path
    # that calls AsyncAnthropicBedrock(...) directly. Patch that symbol so
    # construction returns our fake.
    monkeypatch.setattr(
        chat_module, "AsyncAnthropicBedrock", lambda **_kw: _FakeBedrockClient()
    )

    events = await _collect_stream(
        chat_module.chat_stream(
            ctx=ctx,
            message="hello",
            history=[],
            system_prompt="you are a test",
            ai_config=None,
        )
    )

    joined = "\n".join(events)
    # No sensitive content must appear in any emitted SSE event.
    assert _SENSITIVE_STREAM_MARKER not in joined
    assert "AKIA" not in joined
    assert "RuntimeError" not in joined
    assert "bedrock connect failed" not in joined

    # A generic error event must have been emitted so the UI can react.
    error_events = [e for e in events if e.startswith("event: error")]
    assert error_events, f"expected an error SSE event, got: {events}"
    # The generic copy pins the redaction contract.
    assert any("Chat error. Please try again." in e for e in error_events)


@pytest.mark.asyncio
async def test_openai_create_client_exception_redacted(
    ctx: ChatToolContext, monkeypatch
) -> None:
    """OpenAI path: if ``create_openai_client`` itself raises during the
    stream (e.g. malformed base_url, missing credentials), the exception
    text — which may contain API keys or internal URLs — must NOT escape
    into the SSE stream. A generic error event is emitted instead.
    """
    def _raising_factory(_config):
        raise RuntimeError(
            f"failed to build OpenAI client with api_key={_SENSITIVE_OPENAI_MARKER} "
            "at /app/services/ai_provider.py:168"
        )

    # chat.py imported the symbol directly — patch it on the chat module.
    monkeypatch.setattr(chat_module, "create_openai_client", _raising_factory)

    events = await _collect_stream(
        chat_module.chat_stream(
            ctx=ctx,
            message="hello",
            history=[],
            system_prompt="you are a test",
            ai_config=_make_ai_config(provider="openai"),
        )
    )

    joined = "\n".join(events)
    assert _SENSITIVE_OPENAI_MARKER not in joined
    assert "sk-" not in joined
    assert "/app/services/ai_provider.py" not in joined
    assert "RuntimeError" not in joined

    error_events = [e for e in events if e.startswith("event: error")]
    assert error_events, f"expected an error SSE event, got: {events}"
    assert any("Chat error. Please try again." in e for e in error_events)
