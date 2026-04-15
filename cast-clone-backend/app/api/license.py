"""License status and installation-id endpoints.

Both endpoints are always reachable — no auth, no license gate — because
the UNLICENSED onboarding flow needs them (the user must see their
installation_id and current state before uploading a license).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.services.license import LicenseInfo, LicenseState
from app.services.loc_usage import cumulative_loc

router = APIRouter(prefix="/api/v1/license", tags=["license"])


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
    customer_name: str | None = None
    customer_email: str | None = None
    customer_organization: str | None = None
    issued_by: str | None = None
    expires_at: int | None = None
    issued_at: int | None = None
    notes: str | None = None


class InstallationIdResponse(BaseModel):
    installation_id: str


@router.get("/status", response_model=LicenseStatusResponse)
async def get_license_status(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> LicenseStatusResponse:
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
    return LicenseStatusResponse(
        **base,
        tier=info.license.tier,
        loc_limit=info.license.loc_limit,
        loc_used=loc_used,
        customer_name=info.license.customer.name,
        customer_email=info.license.customer.email,
        customer_organization=info.license.customer.organization,
        issued_by=info.license.issued_by,
        expires_at=info.exp,
        issued_at=info.iat,
        notes=info.license.notes or None,
    )


@router.get("/installation-id", response_model=InstallationIdResponse)
async def get_installation_id(request: Request) -> InstallationIdResponse:
    return InstallationIdResponse(
        installation_id=getattr(request.app.state, "installation_id", ""),
    )
