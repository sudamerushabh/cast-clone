"""Tests for webhook signature verification across all git platform clients."""

from __future__ import annotations

import hashlib
import hmac

from app.git.bitbucket import BitbucketPlatformClient
from app.git.gitea import GiteaPlatformClient
from app.git.github import GitHubPlatformClient
from app.git.gitlab import GitLabPlatformClient

SECRET = "test-webhook-secret"
BODY = b'{"action":"opened"}'


def _sha256_hmac(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

class TestGitHubSignatureVerification:
    def setup_method(self) -> None:
        self.client = GitHubPlatformClient()

    def test_valid_signature(self) -> None:
        sig = f"sha256={_sha256_hmac(SECRET, BODY)}"
        headers = {"x-hub-signature-256": sig}
        assert self.client.verify_webhook_signature(headers, BODY, SECRET)

    def test_invalid_signature(self) -> None:
        headers = {"x-hub-signature-256": "sha256=invalid"}
        assert not self.client.verify_webhook_signature(headers, BODY, SECRET)

    def test_missing_header(self) -> None:
        assert not self.client.verify_webhook_signature({}, BODY, SECRET)


# ---------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------

class TestGitLabSignatureVerification:
    def setup_method(self) -> None:
        self.client = GitLabPlatformClient()

    def test_valid_token(self) -> None:
        headers = {"x-gitlab-token": SECRET}
        assert self.client.verify_webhook_signature(headers, BODY, SECRET)

    def test_invalid_token(self) -> None:
        headers = {"x-gitlab-token": "wrong-token"}
        assert not self.client.verify_webhook_signature(headers, BODY, SECRET)

    def test_missing_token(self) -> None:
        assert not self.client.verify_webhook_signature({}, BODY, SECRET)


# ---------------------------------------------------------------------------
# Bitbucket
# ---------------------------------------------------------------------------

class TestBitbucketSignatureVerification:
    def setup_method(self) -> None:
        self.client = BitbucketPlatformClient()

    def test_valid_signature(self) -> None:
        sig = f"sha256={_sha256_hmac(SECRET, BODY)}"
        headers = {"x-hub-signature": sig}
        assert self.client.verify_webhook_signature(headers, BODY, SECRET)

    def test_invalid_signature(self) -> None:
        headers = {"x-hub-signature": "sha256=invalid"}
        assert not self.client.verify_webhook_signature(headers, BODY, SECRET)

    def test_missing_header(self) -> None:
        assert not self.client.verify_webhook_signature({}, BODY, SECRET)


# ---------------------------------------------------------------------------
# Gitea
# ---------------------------------------------------------------------------

class TestGiteaSignatureVerification:
    def setup_method(self) -> None:
        self.client = GiteaPlatformClient()

    def test_valid_signature(self) -> None:
        # Gitea uses raw hex, no sha256= prefix
        sig = _sha256_hmac(SECRET, BODY)
        headers = {"x-gitea-signature": sig}
        assert self.client.verify_webhook_signature(headers, BODY, SECRET)

    def test_invalid_signature(self) -> None:
        headers = {"x-gitea-signature": "invalid"}
        assert not self.client.verify_webhook_signature(headers, BODY, SECRET)

    def test_missing_header(self) -> None:
        assert not self.client.verify_webhook_signature({}, BODY, SECRET)
