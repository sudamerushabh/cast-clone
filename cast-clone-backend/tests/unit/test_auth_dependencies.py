"""Tests for auth FastAPI dependencies."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.api.dependencies import get_current_user, require_admin
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


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self, mock_user):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_result

        with patch("app.api.dependencies.decode_access_token", return_value="user-1"):
            with patch("app.api.dependencies.get_settings") as mock_settings:
                mock_settings.return_value.secret_key = "test-secret"
                user = await get_current_user(
                    token="valid-token", session=mock_session
                )
        assert user.id == "user-1"

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        mock_session = AsyncMock()

        with patch("app.api.dependencies.decode_access_token", return_value=None):
            with patch("app.api.dependencies.get_settings") as mock_settings:
                mock_settings.return_value.secret_key = "test-secret"
                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(token="bad-token", session=mock_session)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("app.api.dependencies.decode_access_token", return_value="user-1"):
            with patch("app.api.dependencies.get_settings") as mock_settings:
                mock_settings.return_value.secret_key = "test-secret"
                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(
                        token="valid-token", session=mock_session
                    )
        assert exc_info.value.status_code == 401


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
