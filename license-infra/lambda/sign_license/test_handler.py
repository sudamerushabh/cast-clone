"""Unit tests for the sign_license Lambda handler."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(body: dict | str | None = None) -> dict:
    """Build a minimal API Gateway proxy-integration event."""
    event: dict = {"httpMethod": "POST", "path": "/sign"}
    if body is not None:
        event["body"] = json.dumps(body) if isinstance(body, dict) else body
    return event


VALID_BODY: dict = {
    "installation_id": "inst_abc123",
    "customer_name": "Acme Corp",
    "customer_email": "admin@acme.com",
    "customer_organization": "Acme",
    "tier": 1,
    "loc_limit": 500_000,
    "expires_in_days": 365,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def _keypair():
    """Generate an Ed25519 keypair and return (private_pem, public_key)."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode()
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_pem, public_key, public_pem


@pytest.fixture(autouse=True)
def _setup(monkeypatch, _keypair):
    """Set env vars, mock Secrets Manager, and clear the handler cache."""
    private_pem, public_key, public_pem = _keypair

    monkeypatch.setenv("SIGNING_KEY_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:key")
    monkeypatch.setenv("ISSUER", "test-issuer")

    # We need to patch module-level constants that were read at import time
    import handler

    monkeypatch.setattr(handler, "SIGNING_KEY_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:key")
    monkeypatch.setattr(handler, "ISSUER", "test-issuer")
    monkeypatch.setattr(handler, "_signing_key_pem", None)

    mock_sm = MagicMock()
    mock_sm.get_secret_value.return_value = {"SecretString": private_pem}

    with patch.object(handler, "boto3") as mock_boto3:
        mock_boto3.client.return_value = mock_sm
        yield {
            "private_pem": private_pem,
            "public_key": public_key,
            "public_pem": public_pem,
            "mock_sm": mock_sm,
            "mock_boto3": mock_boto3,
        }

    # Reset cache after test
    handler._signing_key_pem = None


@pytest.fixture()
def ctx(_setup):
    """Expose test context dict as a named fixture for explicit use."""
    return _setup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignLicenseHandler:
    """Tests for handler.handler()."""

    def test_happy_path_returns_valid_jwt(self, ctx):
        """POST with valid body -> 200, valid JWT returned."""
        import handler

        resp = handler.handler(_make_event(VALID_BODY), None)

        assert resp["statusCode"] == 200

        body = json.loads(resp["body"])
        assert "token" in body
        assert "jti" in body
        assert "expires_at" in body

        # Decode and verify signature
        decoded = jwt.decode(
            body["token"],
            ctx["public_key"],
            algorithms=["EdDSA"],
            audience=VALID_BODY["installation_id"],
            issuer="test-issuer",
        )

        assert decoded["sub"] == VALID_BODY["installation_id"]
        assert decoded["iss"] == "test-issuer"
        assert decoded["license"]["tier"] == VALID_BODY["tier"]
        assert decoded["license"]["loc_limit"] == VALID_BODY["loc_limit"]
        assert decoded["license"]["customer"]["name"] == VALID_BODY["customer_name"]
        assert decoded["license"]["customer"]["email"] == VALID_BODY["customer_email"]
        assert decoded["license"]["customer"]["organization"] == VALID_BODY["customer_organization"]

    def test_missing_body_returns_400(self):
        """No body in event -> 400."""
        import handler

        event = {"httpMethod": "POST", "path": "/sign"}
        resp = handler.handler(event, None)

        assert resp["statusCode"] == 400
        assert "Missing request body" in json.loads(resp["body"])["error"]

    def test_invalid_json_returns_400(self):
        """Non-JSON body string -> 400."""
        import handler

        event = _make_event()
        event["body"] = "not-json{{"
        resp = handler.handler(event, None)

        assert resp["statusCode"] == 400
        assert "Invalid JSON" in json.loads(resp["body"])["error"]

    def test_missing_required_field_returns_400(self):
        """Body missing installation_id -> 400 with details."""
        import handler

        body = {**VALID_BODY}
        del body["installation_id"]
        resp = handler.handler(_make_event(body), None)

        assert resp["statusCode"] == 400
        resp_body = json.loads(resp["body"])
        assert resp_body["error"] == "Validation failed"
        assert any("installation_id" in d for d in resp_body["details"])

    def test_invalid_tier_type_returns_400(self):
        """tier='invalid_string' (not int or 'trial') -> 400."""
        import handler

        body = {**VALID_BODY, "tier": "enterprise"}
        resp = handler.handler(_make_event(body), None)

        assert resp["statusCode"] == 400
        resp_body = json.loads(resp["body"])
        assert any("tier" in d for d in resp_body["details"])

    def test_negative_loc_limit_returns_400(self):
        """loc_limit=-1 -> 400."""
        import handler

        body = {**VALID_BODY, "loc_limit": -1}
        resp = handler.handler(_make_event(body), None)

        assert resp["statusCode"] == 400
        resp_body = json.loads(resp["body"])
        assert any("loc_limit" in d for d in resp_body["details"])

    def test_zero_expires_in_days_returns_400(self):
        """expires_in_days=0 -> 400."""
        import handler

        body = {**VALID_BODY, "expires_in_days": 0}
        resp = handler.handler(_make_event(body), None)

        assert resp["statusCode"] == 400
        resp_body = json.loads(resp["body"])
        assert any("expires_in_days" in d for d in resp_body["details"])

    def test_trial_tier_accepted(self, ctx):
        """tier='trial' -> 200, JWT tier claim is 'trial'."""
        import handler

        body = {**VALID_BODY, "tier": "trial"}
        resp = handler.handler(_make_event(body), None)

        assert resp["statusCode"] == 200

        token = json.loads(resp["body"])["token"]
        decoded = jwt.decode(
            token,
            ctx["public_key"],
            algorithms=["EdDSA"],
            audience=VALID_BODY["installation_id"],
            issuer="test-issuer",
        )
        assert decoded["license"]["tier"] == "trial"

    def test_empty_signing_key_returns_500(self, ctx):
        """Secrets Manager returns empty string -> 500."""
        import handler

        ctx["mock_sm"].get_secret_value.return_value = {"SecretString": ""}
        resp = handler.handler(_make_event(VALID_BODY), None)

        assert resp["statusCode"] == 500
        assert "not configured" in json.loads(resp["body"])["error"]

    def test_secrets_manager_error_returns_500(self, ctx):
        """boto3 raises ClientError -> 500."""
        from botocore.exceptions import ClientError
        import handler

        ctx["mock_sm"].get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
            "GetSecretValue",
        )
        resp = handler.handler(_make_event(VALID_BODY), None)

        assert resp["statusCode"] == 500
        assert "Secrets Manager error" in json.loads(resp["body"])["error"]

    def test_optional_notes_defaults_to_empty(self, ctx):
        """Body without 'notes' -> notes defaults to ''."""
        import handler

        body = {**VALID_BODY}
        body.pop("notes", None)
        resp = handler.handler(_make_event(body), None)

        assert resp["statusCode"] == 200

        token = json.loads(resp["body"])["token"]
        decoded = jwt.decode(
            token,
            ctx["public_key"],
            algorithms=["EdDSA"],
            audience=VALID_BODY["installation_id"],
            issuer="test-issuer",
        )
        assert decoded["license"]["notes"] == ""

    def test_jti_format(self):
        """JTI should start with 'lic_' and be 16 chars total."""
        import handler

        resp = handler.handler(_make_event(VALID_BODY), None)

        assert resp["statusCode"] == 200

        jti = json.loads(resp["body"])["jti"]
        assert jti.startswith("lic_")
        assert len(jti) == 16
