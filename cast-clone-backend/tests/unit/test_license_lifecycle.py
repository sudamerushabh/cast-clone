"""End-to-end license lifecycle test through the API layer.

Walks through the full sequence:
  UNLICENSED -> writes blocked -> upload valid JWT -> LICENSED_HEALTHY -> writes succeed
"""

from __future__ import annotations

import time
from io import BytesIO
from unittest.mock import AsyncMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import require_admin, require_license_writable
from app.api.license import router as license_router
from app.config import Settings, get_settings
from app.models.db import User
from app.services.license import (
    ISSUER,
    LicenseCustomer,
    LicenseInfo,
    LicensePayload,
    LicenseState,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_INSTALL_ID = "test-install-001"


@pytest.fixture()
def keypair() -> tuple[str, str]:
    """Generate an Ed25519 keypair for test JWT signing/verification."""
    private = ed25519.Ed25519PrivateKey.generate()
    public = private.public_key()
    priv_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv_pem, pub_pem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_admin() -> User:
    return User(
        id="00000000-0000-0000-0000-000000000000",
        username="test-admin",
        email="admin@test.local",
        password_hash="",
        role="admin",
        is_active=True,
    )


def _make_token(priv_pem: str, *, aud: str = _INSTALL_ID) -> str:
    """Build a signed license JWT targeting the test installation."""
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "test-deployment",
        "aud": aud,
        "iat": now,
        "nbf": now,
        "exp": now + 365 * 86400,
        "jti": "lic_LIFECYCLE",
        "license": {
            "version": 1,
            "tier": 2,
            "loc_limit": 500_000,
            "customer": {
                "name": "ACME Corp",
                "email": "ops@acme.com",
                "organization": "ACME Corp",
            },
            "issued_by": "operator@flentas.com",
            "notes": "lifecycle-test",
        },
    }
    return pyjwt.encode(claims, priv_pem, algorithm="EdDSA", headers={"kid": "v1"})


def _sample_license_info() -> LicenseInfo:
    now = int(time.time())
    return LicenseInfo(
        iss=ISSUER,
        sub="test-deployment",
        aud=_INSTALL_ID,
        iat=now,
        nbf=now,
        exp=now + 365 * 86400,
        jti="lic_LIFECYCLE",
        license=LicensePayload(
            version=1,
            tier=2,
            loc_limit=500_000,
            customer=LicenseCustomer(
                name="ACME Corp",
                email="ops@acme.com",
                organization="ACME Corp",
            ),
            issued_by="operator@flentas.com",
            notes="lifecycle-test",
        ),
    )


def _build_lifecycle_app(pub_pem: str, license_file_path: str) -> FastAPI:
    """Build a FastAPI app with both the license router and a gated write endpoint."""
    app = FastAPI()

    # Initial state: UNLICENSED, no license info loaded
    app.state.license_state = LicenseState.UNLICENSED
    app.state.license_info = None
    app.state.installation_id = _INSTALL_ID

    # Dependency overrides
    def fake_settings() -> Settings:
        return Settings(
            license_public_key_v1=pub_pem,
            license_file_path=license_file_path,
        )

    app.dependency_overrides[get_settings] = fake_settings

    async def fake_require_admin() -> User:
        return _fake_admin()

    app.dependency_overrides[require_admin] = fake_require_admin

    # Include the real license router
    app.include_router(license_router)

    # Add a gated write endpoint to exercise require_license_writable
    @app.post("/write", dependencies=[Depends(require_license_writable)])
    async def write_endpoint() -> dict:
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# Lifecycle test
# ---------------------------------------------------------------------------


@patch("app.api.license.cumulative_loc", new_callable=AsyncMock, return_value=0)
@patch("app.api.license.load_license", new_callable=AsyncMock)
def test_full_license_lifecycle(
    mock_load: AsyncMock,
    mock_cum: AsyncMock,
    keypair: tuple[str, str],
    tmp_path,
) -> None:
    """Walk through UNLICENSED -> upload -> LICENSED_HEALTHY, verifying gating at each step."""
    priv_pem, pub_pem = keypair
    license_path = str(tmp_path / "license.jwt")

    app = _build_lifecycle_app(pub_pem, license_path)

    # Prepare mock: load_license returns healthy state AND updates app.state
    info = _sample_license_info()

    def _load_side_effect(settings, installation_id):
        """Simulate what the real upload handler does: update app.state."""
        # The upload handler itself sets app.state after calling load_license,
        # so this mock just needs to return the right tuple.
        return (info, LicenseState.LICENSED_HEALTHY)

    mock_load.return_value = (info, LicenseState.LICENSED_HEALTHY)

    with TestClient(app) as client:
        # ---------------------------------------------------------------
        # Step 1: Verify UNLICENSED state
        # ---------------------------------------------------------------
        r = client.get("/api/v1/license/status")
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "UNLICENSED"
        assert body["installation_id"] == _INSTALL_ID
        assert body["tier"] is None
        assert body["loc_used"] is None

        r = client.get("/api/v1/license/installation-id")
        assert r.status_code == 200
        assert r.json()["installation_id"] == _INSTALL_ID

        # ---------------------------------------------------------------
        # Step 2: Verify write endpoints are blocked (402)
        # ---------------------------------------------------------------
        r = client.post("/write")
        assert r.status_code == 402
        detail = r.json()["detail"]
        assert detail["error"] == "license_required"
        assert detail["state"] == "UNLICENSED"

        # ---------------------------------------------------------------
        # Step 3: Upload a valid license JWT
        # ---------------------------------------------------------------
        token = _make_token(priv_pem)
        r = client.post(
            "/api/v1/license/upload",
            files={"file": ("license.jwt", BytesIO(token.encode()), "application/octet-stream")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "LICENSED_HEALTHY"
        assert body["customer_name"] == "ACME Corp"
        assert body["installation_id"] == _INSTALL_ID
        assert body["tier"] == 2
        assert body["loc_limit"] == 500_000

        # Verify load_license was called during upload
        mock_load.assert_called_once()

        # ---------------------------------------------------------------
        # Step 4: Verify state changed via GET /status
        # ---------------------------------------------------------------
        r = client.get("/api/v1/license/status")
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "LICENSED_HEALTHY"
        assert body["customer_name"] == "ACME Corp"
        assert body["customer_email"] == "ops@acme.com"
        assert body["customer_organization"] == "ACME Corp"
        assert body["issued_by"] == "operator@flentas.com"
        assert body["loc_used"] == 0
        assert body["notes"] == "lifecycle-test"

        # ---------------------------------------------------------------
        # Step 5: Verify write endpoints now succeed
        # ---------------------------------------------------------------
        r = client.post("/write")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
