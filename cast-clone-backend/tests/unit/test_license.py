"""Unit tests for app/services/license.py."""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.services import license as license_module
from app.services.license import (
    ISSUER,
    LicenseState,
    LicenseVerificationError,
    decode_and_verify,
    evaluate_state,
    get_license_state,
    load_license,
)


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


def _make_token(
    priv_pem: str,
    *,
    aud: str,
    exp_offset: int = 3600,
    loc_limit: int = 500_000,
    tier: int | str = 2,
) -> str:
    """Build a signed license JWT with adjustable expiry offset (seconds from now)."""
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
    return jwt.encode(claims, priv_pem, algorithm="EdDSA", headers={"kid": "v1"})


# -------- decode_and_verify --------


class TestDecodeAndVerify:
    def test_happy_path(self, keypair: tuple[str, str]) -> None:
        priv, pub = keypair
        token = _make_token(priv, aud="install-123")
        info = decode_and_verify(token, pub, "install-123")
        assert info.aud == "install-123"
        assert info.license.loc_limit == 500_000
        assert info.license.tier == 2

    def test_wrong_audience_rejected(self, keypair: tuple[str, str]) -> None:
        priv, pub = keypair
        token = _make_token(priv, aud="install-123")
        with pytest.raises(LicenseVerificationError):
            decode_and_verify(token, pub, "install-WRONG")

    def test_tampered_signature_rejected(self, keypair: tuple[str, str]) -> None:
        priv, pub = keypair
        token = _make_token(priv, aud="install-123")
        tampered = token[:-4] + "AAAA"
        with pytest.raises(LicenseVerificationError):
            decode_and_verify(tampered, pub, "install-123")

    def test_expired_license_still_decodes(self, keypair: tuple[str, str]) -> None:
        """Expired licenses must still decode; evaluate_state decides."""
        priv, pub = keypair
        token = _make_token(priv, aud="install-123", exp_offset=-3600)
        info = decode_and_verify(token, pub, "install-123")
        assert info.exp < int(time.time())

    def test_empty_public_key_rejected(self, keypair: tuple[str, str]) -> None:
        priv, _ = keypair
        token = _make_token(priv, aud="install-123")
        with pytest.raises(LicenseVerificationError):
            decode_and_verify(token, "", "install-123")

    def test_wrong_issuer_rejected(self, keypair: tuple[str, str]) -> None:
        priv, pub = keypair
        now = int(time.time())
        bad = jwt.encode(
            {
                "iss": "evil-corp",
                "sub": "x",
                "aud": "install-123",
                "iat": now,
                "nbf": now,
                "exp": now + 3600,
                "jti": "lic_X",
                "license": {
                    "version": 1,
                    "tier": 1,
                    "loc_limit": 1000,
                    "customer": {
                        "name": "",
                        "email": "",
                        "organization": "",
                    },
                    "issued_by": "",
                    "notes": "",
                },
            },
            priv,
            algorithm="EdDSA",
            headers={"kid": "v1"},
        )
        with pytest.raises(LicenseVerificationError):
            decode_and_verify(bad, pub, "install-123")


# -------- evaluate_state --------


class TestEvaluateState:
    def test_no_license_is_unlicensed(self) -> None:
        assert evaluate_state(None, cumulative=0) == LicenseState.UNLICENSED

    def test_healthy_when_fresh_and_low_loc(
        self, keypair: tuple[str, str]
    ) -> None:
        priv, pub = keypair
        token = _make_token(
            priv, aud="x", exp_offset=365 * 86400, loc_limit=1_000_000
        )
        info = decode_and_verify(token, pub, "x")
        assert evaluate_state(info, cumulative=100) == LicenseState.LICENSED_HEALTHY

    def test_warn_when_loc_near_limit(self, keypair: tuple[str, str]) -> None:
        priv, pub = keypair
        token = _make_token(
            priv, aud="x", exp_offset=365 * 86400, loc_limit=100_000
        )
        info = decode_and_verify(token, pub, "x")
        assert evaluate_state(info, cumulative=95_000) == LicenseState.LICENSED_WARN

    def test_warn_when_expiry_close(self, keypair: tuple[str, str]) -> None:
        priv, pub = keypair
        token = _make_token(
            priv, aud="x", exp_offset=10 * 86400, loc_limit=100_000
        )
        info = decode_and_verify(token, pub, "x")
        assert evaluate_state(info, cumulative=100) == LicenseState.LICENSED_WARN

    def test_grace_when_just_expired(self, keypair: tuple[str, str]) -> None:
        priv, pub = keypair
        token = _make_token(priv, aud="x", exp_offset=-86400)
        info = decode_and_verify(token, pub, "x")
        assert evaluate_state(info, cumulative=100) == LicenseState.LICENSED_GRACE

    def test_blocked_when_past_grace(self, keypair: tuple[str, str]) -> None:
        priv, pub = keypair
        token = _make_token(priv, aud="x", exp_offset=-(15 * 86400))
        info = decode_and_verify(token, pub, "x")
        assert evaluate_state(info, cumulative=100) == LicenseState.LICENSED_BLOCKED

    def test_blocked_when_over_loc(self, keypair: tuple[str, str]) -> None:
        priv, pub = keypair
        token = _make_token(priv, aud="x", exp_offset=3600, loc_limit=1000)
        info = decode_and_verify(token, pub, "x")
        assert evaluate_state(info, cumulative=1001) == LicenseState.LICENSED_BLOCKED

    def test_blocked_when_exactly_at_loc_limit(
        self, keypair: tuple[str, str]
    ) -> None:
        priv, pub = keypair
        token = _make_token(priv, aud="x", exp_offset=3600, loc_limit=1000)
        info = decode_and_verify(token, pub, "x")
        assert evaluate_state(info, cumulative=1000) == LicenseState.LICENSED_BLOCKED


# -------- load_license (integration of file IO + decode + cache) --------


class TestLoadLicense:
    @pytest.mark.asyncio
    async def test_missing_file_is_unlicensed(
        self, tmp_path, keypair: tuple[str, str]
    ) -> None:
        _, pub = keypair

        class S:
            license_file_path = str(tmp_path / "nope.jwt")
            license_public_key_v1 = pub

        license_module._current_license = None
        info, state = await load_license(S(), installation_id="install-123")  # type: ignore[arg-type]
        assert info is None
        assert state == LicenseState.UNLICENSED

    @pytest.mark.asyncio
    async def test_valid_file_populates_cache(
        self, tmp_path, keypair: tuple[str, str], monkeypatch
    ) -> None:
        priv, pub = keypair
        token = _make_token(
            priv, aud="install-123", loc_limit=1_000_000, exp_offset=365 * 86400
        )
        p = tmp_path / "license.jwt"
        p.write_text(token)

        class S:
            license_file_path = str(p)
            license_public_key_v1 = pub

        async def fake_cum() -> int:
            return 0

        monkeypatch.setattr("app.services.license.cumulative_loc", fake_cum)

        license_module._current_license = None
        info, state = await load_license(S(), installation_id="install-123")  # type: ignore[arg-type]
        assert info is not None
        assert info.aud == "install-123"
        assert state == LicenseState.LICENSED_HEALTHY

    @pytest.mark.asyncio
    async def test_bad_signature_clears_cache(
        self, tmp_path, keypair: tuple[str, str]
    ) -> None:
        """A license file with a bad signature should clear the cache."""
        priv, pub = keypair
        token = _make_token(priv, aud="install-123")
        # Use a different keypair's public key to simulate wrong signature
        other_priv = ed25519.Ed25519PrivateKey.generate()
        other_pub_pem = other_priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        p = tmp_path / "license.jwt"
        p.write_text(token)

        class S:
            license_file_path = str(p)
            license_public_key_v1 = other_pub_pem

        license_module._current_license = None
        info, state = await load_license(S(), installation_id="install-123")  # type: ignore[arg-type]
        assert info is None
        assert state == LicenseState.UNLICENSED
        assert license_module._current_license is None


# -------- get_license_state --------


class TestGetLicenseState:
    @pytest.mark.asyncio
    async def test_returns_unlicensed_when_no_cache(self) -> None:
        license_module._current_license = None
        assert await get_license_state() == LicenseState.UNLICENSED
