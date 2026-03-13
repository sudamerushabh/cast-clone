"""Tests for the User SQLAlchemy model."""
from app.models.db import User


def test_user_model_has_required_fields():
    """User model should have all required fields for auth."""
    user = User(
        username="testuser",
        email="test@example.com",
        password_hash="hashed_pw",
        role="admin",
    )
    assert user.username == "testuser"
    assert user.email == "test@example.com"
    assert user.password_hash == "hashed_pw"
    assert user.role == "admin"
    assert user.is_active is True


def test_user_model_defaults():
    """User model should default to member role and active."""
    user = User(
        username="member",
        email="member@example.com",
        password_hash="hashed",
    )
    assert user.role == "member"
    assert user.is_active is True


def test_user_tablename():
    """User model should use 'users' table."""
    assert User.__tablename__ == "users"
