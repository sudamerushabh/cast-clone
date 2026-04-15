"""Unit tests for /api/v1/license/status and /api/v1/license/installation-id."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.license import router
from app.config import Settings, get_settings
from app.services.license import (
    LicenseCustomer,
    LicenseInfo,
    LicensePayload,
    LicenseState,
)


def _make_app(
    *,
    license_state: LicenseState = LicenseState.UNLICENSED,
    license_info: LicenseInfo | None = None,
    installation_id: str = "install-abc-123",
    license_disabled: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.state.license_state = license_state
    app.state.license_info = license_info
    app.state.installation_id = installation_id

    def fake_settings() -> Settings:
        return Settings(license_disabled=license_disabled)

    app.dependency_overrides[get_settings] = fake_settings
    app.include_router(router)
    return app


def _sample_license_info() -> LicenseInfo:
    return LicenseInfo(
        iss="flentas-license-authority",
        sub="test",
        aud="install-abc-123",
        iat=1_700_000_000,
        nbf=1_700_000_000,
        exp=1_800_000_000,
        jti="lic_TEST",
        license=LicensePayload(
            version=1,
            tier=2,
            loc_limit=500_000,
            customer=LicenseCustomer(
                name="ACME", email="ops@acme.com", organization="ACME Corp"
            ),
            issued_by="operator@flentas.com",
            notes="pilot",
        ),
    )


class TestInstallationId:
    def test_returns_installation_id(self) -> None:
        app = _make_app(installation_id="foo-123")
        with TestClient(app) as c:
            r = c.get("/api/v1/license/installation-id")
            assert r.status_code == 200
            assert r.json() == {"installation_id": "foo-123"}

    def test_always_reachable_unlicensed(self) -> None:
        """Must work even when UNLICENSED -- powers onboarding."""
        app = _make_app(license_state=LicenseState.UNLICENSED)
        with TestClient(app) as c:
            r = c.get("/api/v1/license/installation-id")
            assert r.status_code == 200


class TestLicenseStatus:
    @patch("app.api.license.cumulative_loc", new_callable=AsyncMock, return_value=0)
    def test_unlicensed_minimal_payload(self, mock_cum: AsyncMock) -> None:
        """UNLICENSED returns base fields only."""
        app = _make_app(license_state=LicenseState.UNLICENSED, installation_id="foo")
        with TestClient(app) as c:
            r = c.get("/api/v1/license/status")
            assert r.status_code == 200
            body = r.json()
            assert body["state"] == "UNLICENSED"
            assert body["installation_id"] == "foo"
            assert body["license_disabled"] is False
            assert body["tier"] is None
            assert body["loc_used"] is None

    @patch(
        "app.api.license.cumulative_loc",
        new_callable=AsyncMock,
        return_value=100_000,
    )
    def test_healthy_returns_full_payload(self, mock_cum: AsyncMock) -> None:
        """When a license is loaded, all fields are populated."""
        app = _make_app(
            license_state=LicenseState.LICENSED_HEALTHY,
            license_info=_sample_license_info(),
            installation_id="install-abc-123",
        )
        with TestClient(app) as c:
            r = c.get("/api/v1/license/status")
            assert r.status_code == 200
            body = r.json()
            assert body["state"] == "LICENSED_HEALTHY"
            assert body["tier"] == 2
            assert body["loc_limit"] == 500_000
            assert body["loc_used"] == 100_000
            assert body["customer_name"] == "ACME"
            assert body["customer_email"] == "ops@acme.com"
            assert body["customer_organization"] == "ACME Corp"
            assert body["issued_by"] == "operator@flentas.com"
            assert body["expires_at"] == 1_800_000_000
            assert body["issued_at"] == 1_700_000_000
            assert body["notes"] == "pilot"

    @patch("app.api.license.cumulative_loc", new_callable=AsyncMock, return_value=0)
    def test_license_disabled_flag_surfaced(self, mock_cum: AsyncMock) -> None:
        app = _make_app(
            license_disabled=True,
            license_state=LicenseState.LICENSED_HEALTHY,
        )
        with TestClient(app) as c:
            r = c.get("/api/v1/license/status")
            assert r.status_code == 200
            assert r.json()["license_disabled"] is True
