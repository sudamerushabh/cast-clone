"""Deny-by-default auth enforcement middleware.

Every request is gated unless the path matches the explicit allowlist.
Per-endpoint dependencies (``Depends(get_current_user)``) still run and
perform the real token validation — this middleware simply refuses to
let un-annotated endpoints silently pass through.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings

_PUBLIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/?$"),
    re.compile(r"^/health/?$"),
    re.compile(r"^/api/v1/health/?$"),
    re.compile(r"^/api/v1/auth/login/?$"),
    re.compile(r"^/api/v1/auth/setup-status/?$"),
    re.compile(r"^/api/v1/auth/setup/?$"),
    re.compile(r"^/api/v1/license/status/?$"),
    re.compile(r"^/api/v1/system/info/?$"),
    re.compile(r"^/docs/?$"),
    re.compile(r"^/redoc/?$"),
    re.compile(r"^/openapi\.json$"),
    re.compile(r"^/favicon\.ico$"),
)


def _is_public(path: str) -> bool:
    return any(p.match(path) for p in _PUBLIC_PATTERNS)


class AuthEnforcerMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:  # noqa: ANN001
        super().__init__(app)
        self._settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if self._settings.auth_disabled:
            return await call_next(request)

        if _is_public(request.url.path):
            return await call_next(request)

        # WebSocket upgrades are validated per-endpoint (see app/api/websocket.py).
        if request.scope["type"] == "websocket":
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return JSONResponse(
                {"detail": "Not authenticated"},
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
