"""Tests for Fernet token encryption/decryption."""

from __future__ import annotations

import pytest

from app.services.crypto import decrypt_token, encrypt_token


class TestCrypto:
    def test_encrypt_then_decrypt_roundtrip(self):
        secret = "my-secret-key"
        plaintext = "ghp_abc123def456"
        encrypted = encrypt_token(plaintext, secret)
        assert encrypted != plaintext
        assert decrypt_token(encrypted, secret) == plaintext

    def test_different_secrets_produce_different_ciphertext(self):
        plaintext = "ghp_abc123"
        enc1 = encrypt_token(plaintext, "secret-a")
        enc2 = encrypt_token(plaintext, "secret-b")
        assert enc1 != enc2

    def test_decrypt_with_wrong_key_fails(self):
        encrypted = encrypt_token("my-token", "correct-key")
        with pytest.raises(Exception):
            decrypt_token(encrypted, "wrong-key")

    def test_empty_token_roundtrip(self):
        encrypted = encrypt_token("", "key")
        assert decrypt_token(encrypted, "key") == ""
