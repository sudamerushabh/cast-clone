"""Unit tests for /api/v1/license endpoints (status, installation-id, upload)."""

from __future__ import annotations

import time
from io import BytesIO
from unittest.mock import AsyncMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.api.dependencies import require_admin
from app.api.license import router
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


@pytest.fixture
def keypair():
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

_INSTALL_ID = "install-abc-123"
_CONTENT_TYPE = "application/octet-stream"


def _upload_files(data: bytes) -> dict:
    """Build the ``files`` kwarg for a multipart upload."""
    return {"file": ("license.jwt", BytesIO(data), _CONTENT_TYPE)}


def _make_token(
    priv_pem: str,
    *,
    aud: str = _INSTALL_ID,
    exp_offset: int = 365 * 86400,
    loc_limit: int = 500_000,
    tier: int | str = 2,
) -> str:
    """Build a signed license JWT."""
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "test-deployment",
        "aud": aud,
        "iat": now,
        "nbf": now,
        "exp": now + exp_offset,
        "jti": "lic_01TEST",
        "license": {
            "version": 1,
            "tier": tier,
            "loc_limit": loc_limit,
            "customer": {
                "name": "ACME Corp",
                "email": "ops@acme.com",
                "organization": "ACME Corp",
            },
            "issued_by": "operator@flentas.com",
            "notes": "",
        },
    }
    return pyjwt.encode(claims, priv_pem, algorithm="EdDSA", headers={"kid": "v1"})


def _fake_admin() -> User:
    return User(
        id="00000000-0000-0000-0000-000000000000",
        username="test-admin",
        email="admin@test.local",
        password_hash="",
        role="admin",
        is_active=True,
    )


def _fake_member() -> User:
    return User(
        id="00000000-0000-0000-0000-000000000001",
        username="test-member",
        email="member@test.local",
        password_hash="",
        role="member",
        is_active=True,
    )


def _make_app(
    *,
    license_state: LicenseState = LicenseState.UNLICENSED,
    license_info: LicenseInfo | None = None,
    installation_id: str = _INSTALL_ID,
    license_disabled: bool = False,
    pub_pem: str = "",
    license_file_path: str = "/tmp/test-license.jwt",
    admin_user: User | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.license_state = license_state
    app.state.license_info = license_info
    app.state.installation_id = installation_id

    def fake_settings() -> Settings:
        return Settings(
            license_disabled=license_disabled,
            license_public_key_v1=pub_pem,
            license_file_path=license_file_path,
        )

    app.dependency_overrides[get_settings] = fake_settings

    # Override require_admin to return the specified user (or a default admin)
    user = admin_user if admin_user is not None else _fake_admin()

    async def fake_require_admin() -> User:
        # Replicate real require_admin behavior: reject non-admins
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        return user

    app.dependency_overrides[require_admin] = fake_require_admin

    app.include_router(router)
    return app


def _sample_license_info() -> LicenseInfo:
    return LicenseInfo(
        iss="flentas-license-authority",
        sub="test",
        aud=_INSTALL_ID,
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


# ===================================================================
# GET /installation-id
# ===================================================================


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


# ===================================================================
# GET /status
# ===================================================================


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
            installation_id=_INSTALL_ID,
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


# ===================================================================
# POST /upload
# ===================================================================


class TestUploadLicense:
    """Tests for POST /api/v1/license/upload."""

    @patch("app.api.license.cumulative_loc", new_callable=AsyncMock, return_value=0)
    @patch("app.api.license.load_license", new_callable=AsyncMock)
    def test_happy_path_upload(
        self,
        mock_load: AsyncMock,
        mock_cum: AsyncMock,
        keypair: tuple[str, str],
        tmp_path,
    ) -> None:
        """Upload valid JWT -> 200, state transitions to LICENSED_HEALTHY."""
        priv, pub = keypair
        token = _make_token(priv)
        license_path = str(tmp_path / "license.jwt")

        # Simulate load_license returning a healthy state after write
        info = _sample_license_info()
        mock_load.return_value = (info, LicenseState.LICENSED_HEALTHY)

        app = _make_app(
            license_state=LicenseState.UNLICENSED,
            pub_pem=pub,
            license_file_path=license_path,
        )
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/license/upload",
                files=_upload_files(token.encode()),
            )

        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "LICENSED_HEALTHY"
        assert body["customer_name"] == "ACME"
        assert body["installation_id"] == _INSTALL_ID

        # File was written to disk
        written = (tmp_path / "license.jwt").read_text(encoding="utf-8")
        assert written == token

    @patch("app.api.license.cumulative_loc", new_callable=AsyncMock, return_value=0)
    def test_invalid_signature_rejected(
        self,
        mock_cum: AsyncMock,
        keypair: tuple[str, str],
        tmp_path,
    ) -> None:
        """Upload a token signed with the wrong key -> 400, file untouched."""
        priv, pub = keypair
        # Generate a different keypair to sign the token
        other_priv = ed25519.Ed25519PrivateKey.generate()
        other_priv_pem = other_priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        token = _make_token(other_priv_pem)  # signed with wrong key

        license_path = tmp_path / "license.jwt"
        license_path.write_text("ORIGINAL_CONTENT")

        app = _make_app(
            pub_pem=pub,
            license_file_path=str(license_path),
        )
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/license/upload",
                files=_upload_files(token.encode()),
            )

        assert r.status_code == 400
        detail = r.json()["detail"]
        assert detail["error"] == "license_invalid"
        assert "invalid" in detail["message"].lower()
        # Original file preserved
        assert license_path.read_text() == "ORIGINAL_CONTENT"

    @patch("app.api.license.cumulative_loc", new_callable=AsyncMock, return_value=0)
    def test_wrong_audience_rejected(
        self,
        mock_cum: AsyncMock,
        keypair: tuple[str, str],
        tmp_path,
    ) -> None:
        """Valid sig but aud doesn't match installation_id -> 400."""
        priv, pub = keypair
        token = _make_token(priv, aud="install-WRONG")

        license_path = tmp_path / "license.jwt"
        license_path.write_text("ORIGINAL_CONTENT")

        app = _make_app(
            pub_pem=pub,
            license_file_path=str(license_path),
            installation_id=_INSTALL_ID,  # doesn't match "install-WRONG"
        )
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/license/upload",
                files=_upload_files(token.encode()),
            )

        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "license_invalid"
        # Original file preserved
        assert license_path.read_text() == "ORIGINAL_CONTENT"

    def test_non_utf8_bytes_rejected(self, tmp_path) -> None:
        """Upload garbage bytes -> 400."""
        license_path = str(tmp_path / "license.jwt")
        app = _make_app(license_file_path=license_path)
        # Invalid UTF-8 byte sequence
        garbage = b"\x80\x81\x82\xff\xfe"
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/license/upload",
                files=_upload_files(garbage),
            )
        assert r.status_code == 400
        assert "UTF-8" in r.json()["detail"]

    def test_file_too_large_rejected(self, tmp_path) -> None:
        """Synthesize 17KB content -> 413."""
        license_path = str(tmp_path / "license.jwt")
        app = _make_app(license_file_path=license_path)
        # 17KB = 17 * 1024 = 17408 bytes > 16384 limit
        big = b"A" * 17_408
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/license/upload",
                files=_upload_files(big),
            )
        assert r.status_code == 413  # HTTP_413_CONTENT_TOO_LARGE
        assert "too large" in r.json()["detail"].lower()

    @patch("app.api.license.cumulative_loc", new_callable=AsyncMock, return_value=0)
    def test_atomic_preservation_on_invalid_jwt(
        self,
        mock_cum: AsyncMock,
        keypair: tuple[str, str],
        tmp_path,
    ) -> None:
        """Write a pre-existing file, upload invalid JWT -> existing content intact."""
        priv, pub = keypair
        license_path = tmp_path / "license.jwt"
        # Pre-existing valid license on disk
        old_token = _make_token(priv)
        license_path.write_text(old_token)

        # Now upload a tampered token
        tampered = old_token[:-4] + "AAAA"

        app = _make_app(
            pub_pem=pub,
            license_file_path=str(license_path),
        )
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/license/upload",
                files=_upload_files(tampered.encode()),
            )

        assert r.status_code == 400
        # Pre-existing content untouched
        assert license_path.read_text() == old_token

    @patch(
        "app.api.license.cumulative_loc",
        new_callable=AsyncMock,
        return_value=42_000,
    )
    @patch("app.api.license.load_license", new_callable=AsyncMock)
    def test_state_reload_after_upload(
        self,
        mock_load: AsyncMock,
        mock_cum: AsyncMock,
        keypair: tuple[str, str],
        tmp_path,
    ) -> None:
        """After successful upload, GET /status returns the new state."""
        priv, pub = keypair
        token = _make_token(priv, loc_limit=1_000_000)
        license_path = str(tmp_path / "license.jwt")

        info = _sample_license_info()
        mock_load.return_value = (info, LicenseState.LICENSED_HEALTHY)

        app = _make_app(
            license_state=LicenseState.UNLICENSED,
            pub_pem=pub,
            license_file_path=license_path,
        )
        with TestClient(app) as c:
            # Upload
            r = c.post(
                "/api/v1/license/upload",
                files=_upload_files(token.encode()),
            )
            assert r.status_code == 200
            assert r.json()["state"] == "LICENSED_HEALTHY"

            # Subsequent GET /status picks up the new state
            r2 = c.get("/api/v1/license/status")
            assert r2.status_code == 200
            body = r2.json()
            assert body["state"] == "LICENSED_HEALTHY"
            assert body["customer_name"] == "ACME"
            assert body["loc_used"] == 42_000

    def test_admin_required(self, keypair: tuple[str, str], tmp_path) -> None:
        """Non-admin user gets 403 on upload.

        We override require_admin in the test app to inject a member user,
        and the override replicates the real role check.
        """
        priv, pub = keypair
        token = _make_token(priv)
        license_path = str(tmp_path / "license.jwt")

        app = _make_app(
            pub_pem=pub,
            license_file_path=license_path,
            admin_user=_fake_member(),  # member, not admin
        )
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/license/upload",
                files=_upload_files(token.encode()),
            )
        assert r.status_code == 403
        assert "admin" in r.json()["detail"].lower()

    @patch("app.api.license.cumulative_loc", new_callable=AsyncMock, return_value=0)
    def test_missing_installation_id_returns_500(
        self,
        mock_cum: AsyncMock,
        keypair: tuple[str, str],
        tmp_path,
    ) -> None:
        """If installation_id is empty, return 500."""
        priv, pub = keypair
        token = _make_token(priv)
        license_path = str(tmp_path / "license.jwt")

        app = _make_app(
            pub_pem=pub,
            license_file_path=license_path,
            installation_id="",
        )
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/license/upload",
                files=_upload_files(token.encode()),
            )
        assert r.status_code == 500
        assert "Installation ID" in r.json()["detail"]
