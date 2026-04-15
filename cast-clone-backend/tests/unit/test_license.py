"""Unit tests for app/services/license.py."""

from __future__ import annotations

import os
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.api.license import atomic_write_text
from app.services import license as license_module
from app.services.license import (
    ISSUER,
    LicenseState,
    LicenseVerificationError,
    decode_and_verify,
    evaluate_state,
    get_current_license,
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

    def test_expired_with_wrong_audience_rejected(
        self, keypair: tuple[str, str]
    ) -> None:
        """Regression: expired + wrong aud must raise LicenseVerificationError."""
        priv, pub = keypair
        token = _make_token(priv, aud="install-123", exp_offset=-3600)
        with pytest.raises(LicenseVerificationError):
            decode_and_verify(token, pub, "install-WRONG")

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

    def test_missing_required_claim_rejected(
        self, keypair: tuple[str, str]
    ) -> None:
        """A token missing the required 'jti' claim must be rejected."""
        priv, pub = keypair
        now = int(time.time())
        claims_without_jti = {
            "iss": ISSUER,
            "sub": "test-deployment",
            "aud": "install-123",
            "iat": now,
            "nbf": now,
            "exp": now + 3600,
            # "jti" deliberately omitted
            "license": {
                "version": 1,
                "tier": 1,
                "loc_limit": 1000,
                "customer": {
                    "name": "ACME",
                    "email": "a@b.com",
                    "organization": "ACME",
                },
                "issued_by": "test",
                "notes": "",
            },
        }
        token = jwt.encode(
            claims_without_jti, priv, algorithm="EdDSA", headers={"kid": "v1"}
        )
        with pytest.raises(LicenseVerificationError):
            decode_and_verify(token, pub, "install-123")


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

    def test_zero_loc_limit_means_unlimited(
        self, keypair: tuple[str, str]
    ) -> None:
        """loc_limit=0 means unlimited; even very high cumulative LOC stays HEALTHY."""
        priv, pub = keypair
        token = _make_token(
            priv, aud="x", exp_offset=365 * 86400, loc_limit=0
        )
        info = decode_and_verify(token, pub, "x")
        assert (
            evaluate_state(info, cumulative=999_999)
            == LicenseState.LICENSED_HEALTHY
        )

    def test_trial_tier_accepted(self, keypair: tuple[str, str]) -> None:
        """A token with tier='trial' should decode and evaluate as HEALTHY."""
        priv, pub = keypair
        token = _make_token(
            priv,
            aud="x",
            exp_offset=365 * 86400,
            loc_limit=1_000_000,
            tier="trial",
        )
        info = decode_and_verify(token, pub, "x")
        assert info.license.tier == "trial"
        assert evaluate_state(info, cumulative=100) == LicenseState.LICENSED_HEALTHY

    def test_exactly_at_90_percent_loc_is_warn(
        self, keypair: tuple[str, str]
    ) -> None:
        """cumulative == 90% of loc_limit (exactly) should be LICENSED_WARN."""
        priv, pub = keypair
        token = _make_token(
            priv, aud="x", exp_offset=365 * 86400, loc_limit=100_000
        )
        info = decode_and_verify(token, pub, "x")
        assert (
            evaluate_state(info, cumulative=90_000) == LicenseState.LICENSED_WARN
        )

    def test_just_below_90_percent_loc_is_healthy(
        self, keypair: tuple[str, str]
    ) -> None:
        """cumulative == 89999 with loc_limit=100000 is below 90% -> HEALTHY."""
        priv, pub = keypair
        token = _make_token(
            priv, aud="x", exp_offset=365 * 86400, loc_limit=100_000
        )
        info = decode_and_verify(token, pub, "x")
        assert (
            evaluate_state(info, cumulative=89_999) == LicenseState.LICENSED_HEALTHY
        )

    def test_exactly_at_30_days_before_expiry_is_warn(
        self, keypair: tuple[str, str]
    ) -> None:
        """exp - now_ts == 30 * 86400 (exactly). Condition is <=, so WARN."""
        priv, pub = keypair
        token = _make_token(
            priv, aud="x", exp_offset=365 * 86400, loc_limit=1_000_000
        )
        info = decode_and_verify(token, pub, "x")
        now_ts = info.exp - 30 * 86400
        assert (
            evaluate_state(info, cumulative=0, now_ts=now_ts)
            == LicenseState.LICENSED_WARN
        )

    def test_just_over_30_days_before_expiry_is_healthy(
        self, keypair: tuple[str, str]
    ) -> None:
        """exp - now_ts == 31 * 86400. More than 30 days -> HEALTHY."""
        priv, pub = keypair
        token = _make_token(
            priv, aud="x", exp_offset=365 * 86400, loc_limit=1_000_000
        )
        info = decode_and_verify(token, pub, "x")
        now_ts = info.exp - 31 * 86400
        assert (
            evaluate_state(info, cumulative=0, now_ts=now_ts)
            == LicenseState.LICENSED_HEALTHY
        )

    def test_exactly_at_grace_cutoff_is_blocked(
        self, keypair: tuple[str, str]
    ) -> None:
        """Token expired exactly 14 days ago -> now_ts == grace_cutoff -> BLOCKED."""
        priv, pub = keypair
        token = _make_token(
            priv, aud="x", exp_offset=365 * 86400, loc_limit=1_000_000
        )
        info = decode_and_verify(token, pub, "x")
        grace_cutoff = info.exp + 14 * 86400
        assert (
            evaluate_state(info, cumulative=0, now_ts=grace_cutoff)
            == LicenseState.LICENSED_BLOCKED
        )

    def test_one_second_before_grace_cutoff_is_grace(
        self, keypair: tuple[str, str]
    ) -> None:
        """now_ts == grace_cutoff - 1 -> still within grace -> GRACE."""
        priv, pub = keypair
        token = _make_token(
            priv, aud="x", exp_offset=365 * 86400, loc_limit=1_000_000
        )
        info = decode_and_verify(token, pub, "x")
        grace_cutoff = info.exp + 14 * 86400
        assert (
            evaluate_state(info, cumulative=0, now_ts=grace_cutoff - 1)
            == LicenseState.LICENSED_GRACE
        )


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


class TestGetCurrentLicense:
    def test_returns_none_when_no_cache(self) -> None:
        license_module._current_license = None
        assert get_current_license() is None

    def test_returns_cached_license(self, keypair: tuple[str, str]) -> None:
        priv, pub = keypair
        token = _make_token(priv, aud="install-123")
        info = decode_and_verify(token, pub, "install-123")
        license_module._current_license = info
        assert get_current_license() is not None
        assert get_current_license() is info
        license_module._current_license = None


class TestGetLicenseState:
    @pytest.mark.asyncio
    async def test_returns_unlicensed_when_no_cache(self) -> None:
        license_module._current_license = None
        assert await get_license_state() == LicenseState.UNLICENSED


# -------- atomic_write_text --------


class TestAtomicWriteText:
    def test_creates_new_file(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "new_file.txt"
        atomic_write_text(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "existing.txt"
        target.write_text("old content", encoding="utf-8")
        atomic_write_text(target, "new content")
        assert target.read_text(encoding="utf-8") == "new content"

    def test_cleans_up_on_failure(self, tmp_path: Path, monkeypatch) -> None:
        """If os.replace raises, the tmp file is cleaned up and original preserved."""
        target = tmp_path / "preserved.txt"
        target.write_text("original", encoding="utf-8")

        monkeypatch.setattr(
            os, "replace", lambda *_args, **_kw: (_ for _ in ()).throw(OSError("boom"))
        )
        with pytest.raises(OSError, match="boom"):
            atomic_write_text(target, "should not persist")

        # Original file preserved
        assert target.read_text(encoding="utf-8") == "original"
        # Tmp file cleaned up
        tmp_file = target.with_name(f".{target.name}.tmp")
        assert not tmp_file.exists()
