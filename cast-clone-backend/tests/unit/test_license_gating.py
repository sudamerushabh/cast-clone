"""Tests for require_license_writable FastAPI dependency (CHAN-17)."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import require_license_writable
from app.config import Settings, get_settings
from app.services.license import LicenseState


def _make_app(state: LicenseState, disabled: bool = False) -> FastAPI:
    """Build a minimal FastAPI app with a controlled license state."""
    app = FastAPI()
    app.state.license_state = state

    def fake_settings() -> Settings:
        s = Settings()
        s.license_disabled = disabled
        return s

    app.dependency_overrides[get_settings] = fake_settings

    @app.post("/write", dependencies=[Depends(require_license_writable)])
    async def write_endpoint() -> dict:
        return {"ok": True}

    @app.get("/read")
    async def read_endpoint() -> dict:
        return {"ok": True}

    return app


class TestLicenseGate:
    @pytest.mark.parametrize(
        "state",
        [
            LicenseState.LICENSED_HEALTHY,
            LicenseState.LICENSED_WARN,
            LicenseState.LICENSED_GRACE,
        ],
    )
    def test_writable_states_allow_writes(self, state: LicenseState) -> None:
        with TestClient(_make_app(state)) as client:
            resp = client.post("/write")
            assert resp.status_code == 200

    @pytest.mark.parametrize(
        "state",
        [
            LicenseState.UNLICENSED,
            LicenseState.LICENSED_BLOCKED,
        ],
    )
    def test_blocked_states_deny_writes(self, state: LicenseState) -> None:
        with TestClient(_make_app(state)) as client:
            resp = client.post("/write")
            assert resp.status_code == 402
            body = resp.json()
            assert body["detail"]["state"] == state.value
            assert body["detail"]["error"] == "license_required"

    def test_blocked_unlicensed_message(self) -> None:
        with TestClient(_make_app(LicenseState.UNLICENSED)) as client:
            resp = client.post("/write")
            body = resp.json()
            assert "Upload a license" in body["detail"]["message"]

    def test_blocked_licensed_blocked_message(self) -> None:
        with TestClient(_make_app(LicenseState.LICENSED_BLOCKED)) as client:
            resp = client.post("/write")
            body = resp.json()
            assert "limit exceeded or expired" in body["detail"]["message"]

    def test_license_disabled_bypasses_gate(self) -> None:
        """LICENSE_DISABLED=true must let writes through even in UNLICENSED."""
        with TestClient(_make_app(LicenseState.UNLICENSED, disabled=True)) as client:
            resp = client.post("/write")
            assert resp.status_code == 200

    def test_reads_never_gated(self) -> None:
        with TestClient(_make_app(LicenseState.LICENSED_BLOCKED)) as client:
            resp = client.get("/read")
            assert resp.status_code == 200

    def test_missing_app_state_defaults_to_unlicensed(self) -> None:
        """If lifespan didn't run, missing state should default to 402."""
        app = FastAPI()

        def fake_settings() -> Settings:
            s = Settings()
            s.license_disabled = False
            return s

        app.dependency_overrides[get_settings] = fake_settings

        @app.post("/write", dependencies=[Depends(require_license_writable)])
        async def write_endpoint() -> dict:
            return {"ok": True}

        with TestClient(app) as client:
            resp = client.post("/write")
            assert resp.status_code == 402
