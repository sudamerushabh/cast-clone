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
    with pytest.raises(ValidationError, match="secret_key"):
        Settings()


def test_secret_key_default_allowed_when_auth_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    settings = Settings()
    assert settings.auth_disabled is True
