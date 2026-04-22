"""Tests for auth FastAPI dependencies."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.api.dependencies import get_current_user, require_admin
from app.config import Settings
from app.models.db import User


@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.id = "user-1"
    user.username = "testuser"
    user.role = "member"
    user.is_active = True
    return user


@pytest.fixture
def mock_admin():
    user = MagicMock(spec=User)
    user.id = "admin-1"
    user.username = "admin"
    user.role = "admin"
    user.is_active = True
    return user


def _settings(auth_disabled: bool = False) -> Settings:
    return Settings(auth_disabled=auth_disabled, secret_key="test-secret")


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self, mock_user):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_result

        with patch("app.api.dependencies.decode_access_token", return_value="user-1"):
            user = await get_current_user(
                token="valid-token", session=mock_session, settings=_settings()
            )
        assert user.id == "user-1"

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        mock_session = AsyncMock()

        with patch("app.api.dependencies.decode_access_token", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    token="bad-token", session=mock_session, settings=_settings()
                )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_raises_401(self):
        mock_session = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                token=None, session=mock_session, settings=_settings()
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("app.api.dependencies.decode_access_token", return_value="user-1"):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    token="valid-token", session=mock_session, settings=_settings()
                )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_disabled_returns_anonymous_admin(self):
        """When AUTH_DISABLED=true, return synthetic admin without any token."""
        mock_session = AsyncMock()

        user = await get_current_user(
            token=None, session=mock_session, settings=_settings(auth_disabled=True)
        )
        assert user.username == "anonymous"
        assert user.role == "admin"
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_auth_disabled_skips_token_validation(self):
        """When AUTH_DISABLED=true, even an invalid token is ignored."""
        mock_session = AsyncMock()

        user = await get_current_user(
            token="garbage", session=mock_session, settings=_settings(auth_disabled=True)
        )
        assert user.username == "anonymous"


class TestRequireAdmin:
    @pytest.mark.asyncio
    async def test_admin_passes(self, mock_admin):
        result = await require_admin(user=mock_admin)
        assert result.role == "admin"

    @pytest.mark.asyncio
    async def test_member_raises_403(self, mock_user):
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(user=mock_user)
        assert exc_info.value.status_code == 403
