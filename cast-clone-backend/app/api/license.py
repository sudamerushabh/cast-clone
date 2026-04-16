"""License status, installation-id, and upload endpoints.

GET /status and GET /installation-id are always reachable — no auth, no
license gate — because the UNLICENSED onboarding flow needs them.

POST /upload is admin-only but NOT gated by ``require_license_writable``
so that an UNLICENSED user can upload a license to escape that state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.config import Settings, get_settings
from app.models.db import User
from app.services.activity import log_activity
from app.services.license import (
    LicenseInfo,
    LicenseState,
    LicenseVerificationError,
    decode_and_verify,
    load_license,
)
from app.services.loc_usage import cumulative_loc
from app.services.postgres import get_session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/license", tags=["license"])


class RepoLocBreakdown(BaseModel):
    repository_id: str
    repo_full_name: str
    billable_loc: int
    max_branch: str | None
    branches: dict[str, int]


class LicenseStatusResponse(BaseModel):
    state: Literal[
        "UNLICENSED",
        "LICENSED_HEALTHY",
        "LICENSED_WARN",
        "LICENSED_GRACE",
        "LICENSED_BLOCKED",
    ]
    installation_id: str
    license_disabled: bool
    tier: int | str | None = None
    loc_limit: int | None = None
    loc_used: int | None = None
    loc_breakdown: list[RepoLocBreakdown] = Field(default_factory=list)
    customer_name: str | None = None
    customer_email: str | None = None
    customer_organization: str | None = None
    issued_by: str | None = None
    expires_at: int | None = None
    issued_at: int | None = None
    notes: str | None = None


class InstallationIdResponse(BaseModel):
    installation_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def atomic_write_text(target: Path, content: str) -> None:
    """Atomically replace *target* with *content*.

    Uses a sibling tempfile + ``os.replace()``.  On any error the
    original *target* is preserved.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


async def _build_status_response(
    request: Request,
    settings: Settings,
) -> LicenseStatusResponse:
    """Build a ``LicenseStatusResponse`` from current app state."""
    state: LicenseState = getattr(
        request.app.state, "license_state", LicenseState.UNLICENSED
    )
    info: LicenseInfo | None = getattr(request.app.state, "license_info", None)
    installation_id: str = getattr(request.app.state, "installation_id", "")

    base: dict[str, Any] = {
        "state": state.value,
        "installation_id": installation_id,
        "license_disabled": settings.license_disabled,
    }
    if info is None:
        return LicenseStatusResponse(**base)

    loc_used = await cumulative_loc()

    # Build per-repo LOC breakdown
    from sqlalchemy import select as sa_select

    from app.models.db import Repository, RepositoryLocTracking
    from app.services.postgres import get_background_session

    breakdown_list: list[RepoLocBreakdown] = []
    async with get_background_session() as session:
        result = await session.execute(
            sa_select(RepositoryLocTracking, Repository.repo_full_name)
            .join(Repository, Repository.id == RepositoryLocTracking.repository_id)
            .where(RepositoryLocTracking.billable_loc > 0)
            .order_by(RepositoryLocTracking.billable_loc.desc())
        )
        for tracking, repo_name in result.all():
            breakdown_list.append(
                RepoLocBreakdown(
                    repository_id=tracking.repository_id,
                    repo_full_name=repo_name,
                    billable_loc=tracking.billable_loc,
                    max_branch=tracking.max_loc_branch_name,
                    branches=tracking.breakdown or {},
                )
            )

    return LicenseStatusResponse(
        **base,
        tier=info.license.tier,
        loc_limit=info.license.loc_limit,
        loc_used=loc_used,
        loc_breakdown=breakdown_list,
        customer_name=info.license.customer.name,
        customer_email=info.license.customer.email,
        customer_organization=info.license.customer.organization,
        issued_by=info.license.issued_by,
        expires_at=info.exp,
        issued_at=info.iat,
        notes=info.license.notes or None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=LicenseStatusResponse)
async def get_license_status(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> LicenseStatusResponse:
    return await _build_status_response(request, settings)


@router.get("/installation-id", response_model=InstallationIdResponse)
async def get_installation_id(request: Request) -> InstallationIdResponse:
    return InstallationIdResponse(
        installation_id=getattr(request.app.state, "installation_id", ""),
    )


@router.post("/upload", response_model=LicenseStatusResponse)
async def upload_license(
    request: Request,
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> LicenseStatusResponse:
    """Admin-only: upload a new license JWT, validate, atomically replace, reload state.

    On validation failure the existing license file is preserved.
    """
    installation_id: str = getattr(request.app.state, "installation_id", "")
    if not installation_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Installation ID not initialized",
        )

    # Read uploaded content (license JWTs are under 4 KB)
    raw = await file.read()
    if len(raw) > 16_384:  # 16 KB sanity ceiling
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="License file too large",
        )
    try:
        token = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"License file is not valid UTF-8: {exc}",
        ) from exc

    # Verify BEFORE writing — if it's bad, the existing file stays put
    try:
        decode_and_verify(token, settings.license_public_key_v1, installation_id)
    except LicenseVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "license_invalid",
                "message": str(exc),
            },
        ) from exc

    # Atomic replace
    target = Path(settings.license_file_path)
    try:
        atomic_write_text(target, token)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write license file: {exc}",
        ) from exc

    # Reload state — populates module cache AND returns fresh state
    info, state = await load_license(settings, installation_id)
    request.app.state.license_info = info
    request.app.state.license_state = state

    await log_activity(
        session, "license.uploaded", user_id=_admin.id,
        resource_type="license",
        details={"state": state.value},
    )

    return await _build_status_response(request, settings)
