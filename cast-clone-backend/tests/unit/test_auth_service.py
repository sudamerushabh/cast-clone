"""Tests for auth service — password hashing and JWT utilities."""
import pytest
from app.services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)


class TestPasswordHashing:
    def test_hash_password_returns_bcrypt_hash(self):
        hashed = hash_password("mypassword")
        assert hashed.startswith("$2b$")
        assert hashed != "mypassword"

    def test_verify_password_correct(self):
        hashed = hash_password("secret123")
        assert verify_password("secret123", hashed) is True

    def test_verify_password_wrong(self):
        hashed = hash_password("secret123")
        assert verify_password("wrong", hashed) is False

    def test_hash_password_unique_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt uses random salts


class TestJWT:
    SECRET = "test-secret-key-for-jwt"

    def test_create_and_decode_token(self):
        token = create_access_token("user-123", self.SECRET)
        assert isinstance(token, str)
        subject = decode_access_token(token, self.SECRET)
        assert subject == "user-123"

    def test_decode_invalid_token(self):
        result = decode_access_token("not.a.valid.token", self.SECRET)
        assert result is None

    def test_decode_wrong_secret(self):
        token = create_access_token("user-123", self.SECRET)
        result = decode_access_token(token, "wrong-secret")
        assert result is None

    def test_token_with_custom_expiry(self):
        token = create_access_token("user-456", self.SECRET, expires_hours=1)
        subject = decode_access_token(token, self.SECRET)
        assert subject == "user-456"

    def test_expired_token(self):
        token = create_access_token("user-789", self.SECRET, expires_hours=-1)
        result = decode_access_token(token, self.SECRET)
        assert result is None
