"""Tests for the ApiKey ORM model."""
from app.models.db import ApiKey


def test_api_key_model_defaults():
    key = ApiKey(
        key_hash="abc123hash",
        name="My Key",
        user_id="user-1",
    )
    assert key.key_hash == "abc123hash"
    assert key.name == "My Key"
    assert key.user_id == "user-1"
    assert key.is_active is True
    assert key.last_used_at is None


def test_api_key_tablename():
    assert ApiKey.__tablename__ == "api_keys"
