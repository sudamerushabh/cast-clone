"""Fernet-based token encryption for Git connector PATs."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from an arbitrary secret string."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_token(plaintext: str, secret_key: str) -> str:
    f = Fernet(_derive_key(secret_key))
    return f.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str, secret_key: str) -> str:
    f = Fernet(_derive_key(secret_key))
    return f.decrypt(ciphertext.encode()).decode()
