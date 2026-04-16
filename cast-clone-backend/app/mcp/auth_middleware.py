"""ASGI middleware that gates the MCP SSE endpoint with Bearer auth.

Validates the Authorization header against the shared ApiKeyAuthenticator.
Requests without a valid Bearer token are rejected with 401 before reaching
the FastMCP app.

Implemented as a pure ASGI middleware (not ``BaseHTTPMiddleware``) to avoid
Starlette wrapping streaming SSE responses through an intermediate response
object. SSE needs the original upstream streaming behaviour to keep the
connection open for server-sent events.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.mcp.auth import ApiKeyAuthenticator

logger = structlog.get_logger(__name__)


_UNAUTH_RESPONSE_HEADERS = (
    (b"content-type", b"application/json"),
    (b"www-authenticate", b"Bearer"),
)


async def _send_401(send: Any, reason: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": _UNAUTH_RESPONSE_HEADERS,
        }
    )
    body = f'{{"error":"{reason}"}}'.encode()
    await send(
        {
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        }
    )


class McpAuthMiddleware:
    """Pure ASGI middleware enforcing Bearer auth on the MCP SSE transport.

    Every HTTP request is inspected for an ``Authorization: Bearer <key>``
    header. The key is validated against the shared
    :class:`~app.mcp.auth.ApiKeyAuthenticator`, which caches hashes for 5
    minutes and batches ``last_used_at`` updates. Non-HTTP scopes (lifespan)
    pass through untouched.
    """

    def __init__(self, app: Any, authenticator: ApiKeyAuthenticator) -> None:
        self._app = app
        self._authenticator = authenticator

    async def __call__(
        self, scope: dict, receive: Any, send: Any
    ) -> None:
        if scope["type"] != "http":
            # Lifespan / websocket scopes pass through unchanged.
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode("latin-1", "ignore")
        if not auth.lower().startswith("bearer "):
            await logger.awarning(
                "mcp.auth_missing_bearer", path=scope.get("path")
            )
            await _send_401(send, "missing_bearer_token")
            return

        token = auth[7:].strip()
        verified = await self._authenticator.verify_key(token)
        if not verified:
            await logger.awarning(
                "mcp.auth_invalid_token", path=scope.get("path")
            )
            await _send_401(send, "invalid_api_key")
            return

        scope.setdefault("state", {})
        scope["state"]["api_key"] = verified
        await self._app(scope, receive, send)
