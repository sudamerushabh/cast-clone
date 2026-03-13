"""Tests for auth Pydantic schemas."""
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from app.schemas.auth import (
    LoginResponse,
    UserResponse,
    SetupRequest,
    SetupStatusResponse,
    UserCreateRequest,
)


class TestLoginResponse:
    def test_valid(self):
        resp = LoginResponse(access_token="abc.def.ghi")
        assert resp.access_token == "abc.def.ghi"
        assert resp.token_type == "bearer"


class TestUserResponse:
    def test_valid(self):
        now = datetime.now(timezone.utc)
        resp = UserResponse(
            id="u1",
            username="admin",
            email="admin@example.com",
            role="admin",
            is_active=True,
            created_at=now,
            last_login=None,
        )
        assert resp.username == "admin"
        assert resp.last_login is None


class TestSetupRequest:
    def test_valid(self):
        req = SetupRequest(
            username="admin",
            email="admin@example.com",
            password="strongpass123",
        )
        assert req.username == "admin"

    def test_username_too_short(self):
        with pytest.raises(ValidationError):
            SetupRequest(username="ab", email="a@b.com", password="strongpass123")

    def test_password_too_short(self):
        with pytest.raises(ValidationError):
            SetupRequest(username="admin", email="a@b.com", password="short")


class TestUserCreateRequest:
    def test_valid(self):
        req = UserCreateRequest(
            username="newuser",
            email="new@example.com",
            password="password123",
            role="member",
        )
        assert req.role == "member"

    def test_invalid_role(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(
                username="newuser",
                email="new@example.com",
                password="password123",
                role="superadmin",
            )

    def test_defaults_to_member(self):
        req = UserCreateRequest(
            username="newuser",
            email="new@example.com",
            password="password123",
        )
        assert req.role == "member"


class TestSetupStatusResponse:
    def test_valid(self):
        resp = SetupStatusResponse(needs_setup=True)
        assert resp.needs_setup is True
