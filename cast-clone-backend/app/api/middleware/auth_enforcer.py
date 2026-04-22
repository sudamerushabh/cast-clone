"""Deny-by-default auth enforcement — pure ASGI middleware.

HTTP requests lacking a Bearer token are rejected with 401 before reaching
any route handler. WebSocket and lifespan scopes are passed through untouched
(WebSocket auth is handled per-endpoint in ``app/api/websocket.py``).

This is implemented as a pure ASGI middleware (not BaseHTTPMiddleware) to
avoid Starlette wrapping streaming responses through an intermediate
``_StreamingResponse`` that silently drops ``BackgroundTask`` instances. See
https://github.com/encode/starlette/issues/1012 for context. Task 9 (chat
SSE redaction) relies on this behaviour.
"""

from __future__ import annotations

import re
from typing import Any

from app.config import Settings

_PUBLIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/?$"),
    re.compile(r"^/health/?$"),
    re.compile(r"^/api/v1/auth/login/?$"),
    re.compile(r"^/api/v1/auth/setup-status/?$"),
    re.compile(r"^/api/v1/auth/setup/?$"),
    re.compile(r"^/docs/?$"),
    re.compile(r"^/redoc/?$"),
    re.compile(r"^/openapi\.json$"),
    re.compile(r"^/favicon\.ico$"),
)
# Patterns MUST be anchored (^...$) and case-sensitive. Starlette URL-decodes
# percent-encoded alphanumerics before path matching but preserves %2F and
# null bytes. Case variation, double-slash, and traversal segments all fall
# through to the 401 branch.


def _is_public(path: str) -> bool:
    return any(p.match(path) for p in _PUBLIC_PATTERNS)


_UNAUTH_RESPONSE_HEADERS = [
    (b"content-type", b"application/json"),
    (b"www-authenticate", b"Bearer"),
]
_UNAUTH_RESPONSE_BODY = b'{"detail":"Not authenticated"}'


async def _send_401(send: Any) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": _UNAUTH_RESPONSE_HEADERS,
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": _UNAUTH_RESPONSE_BODY,
            "more_body": False,
        }
    )


class AuthEnforcerMiddleware:
    """Pure ASGI middleware — no Starlette response wrapping.

    Registered via ``application.add_middleware(AuthEnforcerMiddleware,
    settings=settings)``. FastAPI/Starlette's middleware stack accepts any
    ASGI3 callable, so this class is treated the same as a BaseHTTPMiddleware
    subclass from the registration API's point of view — but because it does
    not wrap the downstream response object, ``BackgroundTask`` instances
    attached to streaming responses survive the trip back to the client.
    """

    def __init__(self, app: Any, settings: Settings) -> None:
        self._app = app
        self._settings = settings

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        # WebSocket and lifespan scopes bypass this middleware entirely.
        # WebSocket auth is enforced per-endpoint; lifespan has no user.
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        if self._settings.auth_disabled:
            await self._app(scope, receive, send)
            return

        path: str = scope["path"]
        if _is_public(path):
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode("latin-1", "ignore")
        if not auth.lower().startswith("bearer "):
            await _send_401(send)
            return

        await self._app(scope, receive, send)
