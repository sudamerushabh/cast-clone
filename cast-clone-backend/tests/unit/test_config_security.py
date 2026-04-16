from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_auth_disabled_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SECRET_KEY", "test-secret-123")
    settings = Settings()
    assert settings.auth_disabled is False


def test_secret_key_default_rejected_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError, match="must be overridden via SECRET_KEY"):
        Settings()


def test_secret_key_default_allowed_when_auth_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    settings = Settings()
    assert settings.auth_disabled is True


def test_secret_key_empty_string_rejected_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SECRET_KEY", "")
    with pytest.raises(ValidationError, match="must be overridden via SECRET_KEY"):
        Settings()


def test_secret_key_whitespace_only_rejected_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SECRET_KEY", "   ")
    with pytest.raises(ValidationError, match="must be overridden via SECRET_KEY"):
        Settings()


def test_secret_key_uppercase_variant_rejected_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SECRET_KEY", "CHANGE-ME-IN-PRODUCTION")
    with pytest.raises(ValidationError, match="must be overridden via SECRET_KEY"):
        Settings()


def test_secret_key_mixed_case_variant_rejected_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SECRET_KEY", "Change-Me-In-Production")
    with pytest.raises(ValidationError, match="must be overridden via SECRET_KEY"):
        Settings()


def test_secret_key_whitespace_padded_variant_rejected_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SECRET_KEY", "  change-me-in-production  ")
    with pytest.raises(ValidationError, match="must be overridden via SECRET_KEY"):
        Settings()


def test_secret_key_real_looking_secret_accepted_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    # 64 hex chars, e.g. what `openssl rand -hex 32` would produce
    monkeypatch.setenv(
        "SECRET_KEY",
        "a3f1c9d8e2b47056ab1c4d2f9e8b7a6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a",
    )
    settings = Settings()
    assert settings.auth_disabled is False
    assert settings.secret_key.startswith("a3f1c9d8")
