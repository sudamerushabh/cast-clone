"""JWT license validator and state machine.

Decodes Ed25519-signed license JWTs, evaluates the current license state
based on expiry and cumulative LOC usage, and exposes an in-memory cache
for the currently-loaded license.

This module does NOT handle endpoint gating (CHAN-17), file upload
atomicity (CHAN-20), or lifespan wiring (CHAN-16).
"""

from __future__ import annotations

import asyncio
import enum
import time
from pathlib import Path
from typing import Literal

import jwt  # PyJWT
import structlog
from pydantic import BaseModel, Field

from app.config import Settings
from app.services.loc_usage import cumulative_loc

logger = structlog.get_logger(__name__)

ISSUER = "flentas-license-authority"
LICENSE_VERSION = 1
GRACE_DAYS = 14
WARN_PCT = 0.9  # cumulative_loc >= 90% of loc_limit -> WARN
EXPIRY_WARN_DAYS = 30  # within 30 days of exp -> WARN


class LicenseState(enum.StrEnum):
    UNLICENSED = "UNLICENSED"
    LICENSED_HEALTHY = "LICENSED_HEALTHY"
    LICENSED_WARN = "LICENSED_WARN"
    LICENSED_GRACE = "LICENSED_GRACE"
    LICENSED_BLOCKED = "LICENSED_BLOCKED"


class LicenseCustomer(BaseModel):
    name: str
    email: str  # not EmailStr -- we don't want to reject licenses on email quirks
    organization: str


class LicensePayload(BaseModel):
    """The ``license`` claim body -- the license-specific metadata."""

    version: int = Field(ge=1)
    tier: int | Literal["trial"]
    loc_limit: int = Field(ge=0)
    customer: LicenseCustomer
    issued_by: str
    notes: str = ""


class LicenseInfo(BaseModel):
    """Decoded, verified license. Pydantic for ergonomic serialization to API."""

    iss: str
    sub: str
    aud: str
    iat: int
    nbf: int
    exp: int
    jti: str
    license: LicensePayload


# ---------------------------------------------------------------------------
# Module-level cache (singleton for this process)
# ---------------------------------------------------------------------------
_current_license: LicenseInfo | None = None
_load_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class LicenseError(Exception):
    """Base class for license errors."""


class LicenseVerificationError(LicenseError):
    """Signature / format / audience / issuer mismatch."""


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------
def decode_and_verify(
    token: str, public_key_pem: str, expected_aud: str
) -> LicenseInfo:
    """Verify JWT signature, iss, aud, exp, nbf. Return LicenseInfo on success.

    Raises :class:`LicenseVerificationError` on any failure.
    """
    if not public_key_pem:
        raise LicenseVerificationError("license_public_key_v1 is not configured")
    try:
        claims = jwt.decode(
            token,
            public_key_pem,
            algorithms=["EdDSA"],
            audience=expected_aud,
            issuer=ISSUER,
            options={
                "require": ["iss", "aud", "exp", "nbf", "iat", "jti", "sub"],
            },
        )
    except jwt.ExpiredSignatureError:
        # Expiration does NOT raise here -- state machine will classify as
        # GRACE/BLOCKED. Re-decode without exp verification to retrieve claims.
        claims = jwt.decode(
            token,
            public_key_pem,
            algorithms=["EdDSA"],
            audience=expected_aud,
            issuer=ISSUER,
            options={
                "require": ["iss", "aud", "exp", "nbf", "iat", "jti", "sub"],
                "verify_exp": False,
            },
        )
    except jwt.PyJWTError as exc:
        raise LicenseVerificationError(
            f"license signature/format invalid: {exc}"
        ) from exc

    try:
        return LicenseInfo(**claims)
    except Exception as exc:
        raise LicenseVerificationError(
            f"license claims malformed: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
def evaluate_state(
    info: LicenseInfo | None,
    *,
    cumulative: int,
    now_ts: int | None = None,
) -> LicenseState:
    """Pure function: ``(info, cumulative_loc, now)`` -> ``LicenseState``.

    Priority order: BLOCKED > GRACE > WARN > HEALTHY.
    """
    if info is None:
        return LicenseState.UNLICENSED

    now_ts = now_ts if now_ts is not None else int(time.time())
    exp = info.exp
    limit = info.license.loc_limit

    # Hard block: past grace period OR over LOC limit
    grace_cutoff = exp + GRACE_DAYS * 86400
    if now_ts >= grace_cutoff:
        return LicenseState.LICENSED_BLOCKED
    if limit > 0 and cumulative >= limit:
        return LicenseState.LICENSED_BLOCKED

    # In grace period: expired but within 14 days
    if now_ts >= exp:
        return LicenseState.LICENSED_GRACE

    # Warn conditions (not blocked, not grace)
    warn_cutoff_loc = limit * WARN_PCT if limit > 0 else float("inf")
    within_expiry_warn = exp - now_ts <= EXPIRY_WARN_DAYS * 86400
    if cumulative >= warn_cutoff_loc or within_expiry_warn:
        return LicenseState.LICENSED_WARN

    return LicenseState.LICENSED_HEALTHY


# ---------------------------------------------------------------------------
# Load / cache / read helpers
# ---------------------------------------------------------------------------
async def load_license(
    settings: Settings, installation_id: str
) -> tuple[LicenseInfo | None, LicenseState]:
    """Read the license file, verify, populate module cache, return ``(info, state)``.

    * If file missing -> UNLICENSED, cache cleared.
    * If file present but verification fails -> UNLICENSED, cache cleared, error logged.
    * If file valid -> cache populated, state evaluated via :func:`cumulative_loc`.

    Called from lifespan (CHAN-16) at boot, and from upload endpoint (CHAN-20)
    after replace.
    """
    global _current_license  # noqa: PLW0603
    async with _load_lock:
        path = Path(settings.license_file_path)
        if not path.exists():
            _current_license = None
            await logger.ainfo("license.load.missing", path=str(path))
            return (None, LicenseState.UNLICENSED)

        try:
            token = path.read_text(encoding="utf-8").strip()
            info = decode_and_verify(
                token,
                settings.license_public_key_v1,
                expected_aud=installation_id,
            )
        except LicenseVerificationError as exc:
            _current_license = None
            await logger.aerror(
                "license.load.verification_failed",
                path=str(path),
                error=str(exc),
            )
            return (None, LicenseState.UNLICENSED)

        _current_license = info
        used = await cumulative_loc()
        state = evaluate_state(info, cumulative=used)
        await logger.ainfo(
            "license.load.ok",
            tier=info.license.tier,
            state=state.value,
            loc_limit=info.license.loc_limit,
            loc_used=used,
            aud=info.aud,
            jti=info.jti,
        )
        return (info, state)


async def get_license_state() -> LicenseState:
    """Read the cached license and evaluate state against current cumulative LOC."""
    if _current_license is None:
        return LicenseState.UNLICENSED
    used = await cumulative_loc()
    return evaluate_state(_current_license, cumulative=used)


def get_current_license() -> LicenseInfo | None:
    """Return the cached license (read-only)."""
    return _current_license
