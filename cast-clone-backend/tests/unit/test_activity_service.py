"""Tests for activity logging service."""

from unittest.mock import AsyncMock

import pytest

from app.services.activity import log_activity


class TestLogActivity:
    @pytest.mark.asyncio
    async def test_log_activity_adds_to_session(self):
        mock_session = AsyncMock()
        await log_activity(
            session=mock_session,
            action="user.login",
            user_id="user-1",
            resource_type="user",
            resource_id="user-1",
            details={"ip": "127.0.0.1"},
        )
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_activity_without_user(self):
        mock_session = AsyncMock()
        await log_activity(
            session=mock_session,
            action="system.startup",
        )
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_activity_swallows_errors(self):
        """Activity logging should never raise -- it's fire-and-forget."""
        mock_session = AsyncMock()
        mock_session.commit.side_effect = Exception("DB error")
        # Should not raise
        await log_activity(
            session=mock_session,
            action="test.action",
        )
