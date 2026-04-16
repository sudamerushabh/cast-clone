"""License signing Lambda handler — EdDSA (Ed25519) JWT issuance."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from uuid import uuid4

import boto3
import jwt
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Module-level cache (survives Lambda container reuse)
# ---------------------------------------------------------------------------
_signing_key_pem: str | None = None

SIGNING_KEY_SECRET_ARN = os.environ.get("SIGNING_KEY_SECRET_ARN", "")
ISSUER = os.environ.get("ISSUER", "flentas-license-authority")

REQUIRED_FIELDS = (
    "installation_id",
    "customer_name",
    "customer_email",
    "customer_organization",
    "tier",
    "loc_limit",
    "expires_in_days",
)

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def _get_signing_key() -> str:
    """Fetch the Ed25519 private key PEM from Secrets Manager (cached)."""
    global _signing_key_pem  # noqa: PLW0603

    if _signing_key_pem is not None:
        return _signing_key_pem

    if not SIGNING_KEY_SECRET_ARN:
        raise RuntimeError("Signing key not configured")

    try:
        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=SIGNING_KEY_SECRET_ARN)
        pem = resp.get("SecretString", "")
    except ClientError as exc:
        logger.exception("Failed to retrieve signing key from Secrets Manager")
        raise RuntimeError(f"Secrets Manager error: {exc}") from exc

    if not pem:
        raise RuntimeError("Signing key not configured")

    _signing_key_pem = pem
    return _signing_key_pem


def _validate_body(body: dict[str, Any]) -> list[str]:
    """Return a list of validation error strings (empty == valid)."""
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in body:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    # Type checks
    if not isinstance(body["installation_id"], str) or not body["installation_id"]:
        errors.append("installation_id must be a non-empty string")

    if not isinstance(body["customer_name"], str) or not body["customer_name"]:
        errors.append("customer_name must be a non-empty string")

    if not isinstance(body["customer_email"], str) or not body["customer_email"]:
        errors.append("customer_email must be a non-empty string")

    if not isinstance(body["customer_organization"], str) or not body["customer_organization"]:
        errors.append("customer_organization must be a non-empty string")

    tier = body["tier"]
    if not (isinstance(tier, int) or tier == "trial"):
        errors.append("tier must be an integer or the string 'trial'")

    loc_limit = body["loc_limit"]
    if not isinstance(loc_limit, int) or loc_limit < 0:
        errors.append("loc_limit must be an integer >= 0")

    expires_in_days = body["expires_in_days"]
    if not isinstance(expires_in_days, int) or expires_in_days <= 0:
        errors.append("expires_in_days must be an integer > 0")

    return errors


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point — signs a license JWT with Ed25519."""

    # --- Parse body --------------------------------------------------------
    raw_body = event.get("body")
    if raw_body is None:
        return _response(400, {"error": "Missing request body"})

    if isinstance(raw_body, str):
        try:
            body: dict[str, Any] = json.loads(raw_body)
        except (json.JSONDecodeError, TypeError):
            return _response(400, {"error": "Invalid JSON in request body"})
    elif isinstance(raw_body, dict):
        body = raw_body
    else:
        return _response(400, {"error": "Invalid request body"})

    # --- Validate ----------------------------------------------------------
    errors = _validate_body(body)
    if errors:
        return _response(400, {"error": "Validation failed", "details": errors})

    # --- Fetch signing key -------------------------------------------------
    try:
        private_key_pem = _get_signing_key()
    except RuntimeError as exc:
        logger.error("Signing key error: %s", exc)
        return _response(500, {"error": str(exc)})

    # --- Build claims ------------------------------------------------------
    now = int(time.time())
    installation_id: str = body["installation_id"]
    expires_in_days: int = body["expires_in_days"]
    exp = now + expires_in_days * 86400
    jti = f"lic_{uuid4().hex[:12]}"

    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": installation_id,
        "aud": installation_id,
        "iat": now,
        "nbf": now,
        "exp": exp,
        "jti": jti,
        "license": {
            "version": 1,
            "tier": body["tier"],
            "loc_limit": body["loc_limit"],
            "customer": {
                "name": body["customer_name"],
                "email": body["customer_email"],
                "organization": body["customer_organization"],
            },
            "issued_by": "operator",
            "notes": body.get("notes", ""),
        },
    }

    # --- Sign JWT ----------------------------------------------------------
    try:
        token: str = jwt.encode(
            claims,
            private_key_pem,
            algorithm="EdDSA",
            headers={"kid": "v1"},
        )
    except Exception as exc:
        logger.exception("JWT signing failed")
        return _response(500, {"error": f"JWT signing failed: {exc}"})

    # --- Return signed token -----------------------------------------------
    logger.info("Issued license %s for %s (tier=%s, exp=%d)", jti, installation_id, body["tier"], exp)

    return _response(200, {
        "token": token,
        "jti": jti,
        "expires_at": exp,
    })
