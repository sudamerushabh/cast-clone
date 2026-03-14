"""Tests for API key Pydantic schemas."""

import pytest
from pydantic import ValidationError
from app.schemas.api_keys import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
)


class TestApiKeyCreateRequest:
    def test_valid(self):
        req = ApiKeyCreateRequest(name="My Integration Key")
        assert req.name == "My Integration Key"

    def test_name_too_short(self):
        with pytest.raises(ValidationError):
            ApiKeyCreateRequest(name="")

    def test_name_too_long(self):
        with pytest.raises(ValidationError):
            ApiKeyCreateRequest(name="x" * 101)


class TestApiKeyCreateResponse:
    def test_includes_raw_key(self):
        resp = ApiKeyCreateResponse(
            id="key-1",
            name="My Key",
            raw_key="clk_abc123",
            created_at="2026-01-01T00:00:00Z",
        )
        assert resp.raw_key == "clk_abc123"
        assert resp.id == "key-1"


class TestApiKeyResponse:
    def test_no_raw_key(self):
        resp = ApiKeyResponse(
            id="key-1",
            name="My Key",
            is_active=True,
            created_at="2026-01-01T00:00:00Z",
            last_used_at=None,
        )
        assert not hasattr(resp, "raw_key") or "raw_key" not in resp.model_fields
        assert resp.is_active is True
