"""Unit tests for the MCP Bearer-auth ASGI middleware."""

from __future__ import annotations

import pytest

from app.mcp.auth_middleware import McpAuthMiddleware


class _FakeAuthenticator:
    """Stand-in for ApiKeyAuthenticator — uses an in-memory token set."""

    def __init__(self, valid_tokens: set[str]) -> None:
        self._valid = valid_tokens

    async def verify_key(self, token: str) -> dict[str, str] | None:
        if token in self._valid:
            return {"key_id": f"key-{token}", "user_id": f"user-{token}"}
        return None


class _CapturingSend:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)


class _DummyApp:
    def __init__(self) -> None:
        self.called = False
        self.received_scope: dict | None = None

    async def __call__(self, scope: dict, receive, send) -> None:
        self.called = True
        self.received_scope = scope
        await send({"type": "http.response.start", "status": 200, "headers": ()})
        await send(
            {"type": "http.response.body", "body": b"", "more_body": False}
        )


@pytest.mark.asyncio
async def test_rejects_missing_authorization() -> None:
    app = _DummyApp()
    mw = McpAuthMiddleware(app, _FakeAuthenticator({"valid"}))
    send = _CapturingSend()
    await mw({"type": "http", "path": "/", "headers": []}, None, send)

    assert app.called is False
    assert send.messages[0]["status"] == 401
    assert any(
        h == (b"www-authenticate", b"Bearer")
        for h in send.messages[0]["headers"]
    )
    assert b"missing_bearer_token" in send.messages[1]["body"]


@pytest.mark.asyncio
async def test_rejects_non_bearer_scheme() -> None:
    app = _DummyApp()
    mw = McpAuthMiddleware(app, _FakeAuthenticator({"valid"}))
    send = _CapturingSend()
    await mw(
        {
            "type": "http",
            "path": "/",
            "headers": [(b"authorization", b"Basic dXg6cHc=")],
        },
        None,
        send,
    )

    assert app.called is False
    assert send.messages[0]["status"] == 401
    assert b"missing_bearer_token" in send.messages[1]["body"]


@pytest.mark.asyncio
async def test_rejects_invalid_token() -> None:
    app = _DummyApp()
    mw = McpAuthMiddleware(app, _FakeAuthenticator({"valid"}))
    send = _CapturingSend()
    await mw(
        {
            "type": "http",
            "path": "/",
            "headers": [(b"authorization", b"Bearer wrong")],
        },
        None,
        send,
    )

    assert app.called is False
    assert send.messages[0]["status"] == 401
    assert b"invalid_api_key" in send.messages[1]["body"]


@pytest.mark.asyncio
async def test_passes_valid_token_through() -> None:
    app = _DummyApp()
    mw = McpAuthMiddleware(app, _FakeAuthenticator({"valid"}))
    send = _CapturingSend()
    await mw(
        {
            "type": "http",
            "path": "/",
            "headers": [(b"authorization", b"Bearer valid")],
        },
        None,
        send,
    )

    assert app.called is True
    assert send.messages[0]["status"] == 200
    # Verified key identity is attached to scope.state for downstream handlers.
    assert app.received_scope is not None
    assert app.received_scope["state"]["api_key"] == {
        "key_id": "key-valid",
        "user_id": "user-valid",
    }


@pytest.mark.asyncio
async def test_non_http_scope_passes_through() -> None:
    app = _DummyApp()
    mw = McpAuthMiddleware(app, _FakeAuthenticator({"valid"}))
    send = _CapturingSend()
    # Lifespan scope — no authorization check, passes straight through.
    await mw({"type": "lifespan"}, None, send)

    assert app.called is True
