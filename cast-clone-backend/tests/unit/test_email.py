"""Unit tests for email service — template rendering, dedup, encryption, cadence."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email import (
    EXPIRY_REMINDER_DAYS,
    LICENSE_FLENTAS_BCC_ADDRESS,
    SUBJECT_MAP,
    _build_template_context,
    _sanitize_subject,
    decrypt_password,
    encrypt_password,
    render_subject,
)
from app.services.license import (
    LicenseCustomer,
    LicenseInfo,
    LicensePayload,
    LicenseState,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_license_info() -> LicenseInfo:
    now = int(time.time())
    return LicenseInfo(
        iss="flentas-license-authority",
        sub="test-install-id",
        aud="test-install-id",
        iat=now,
        nbf=now,
        exp=now + 365 * 86400,
        jti="lic_test123",
        license=LicensePayload(
            version=1,
            tier=2,
            loc_limit=500000,
            customer=LicenseCustomer(
                name="Test Customer",
                email="test@acme.com",
                organization="Acme Corp",
            ),
            issued_by="operator",
            notes="",
        ),
    )


# ---------------------------------------------------------------------------
# Encryption tests
# ---------------------------------------------------------------------------


class TestEncryption:
    def test_round_trip(self):
        """Encrypt then decrypt returns original plaintext."""
        plaintext = "my-smtp-password-123"
        encrypted = encrypt_password(plaintext)
        assert isinstance(encrypted, bytes)
        assert encrypted != plaintext.encode()
        decrypted = decrypt_password(encrypted)
        assert decrypted == plaintext

    def test_empty_password(self):
        encrypted = encrypt_password("")
        assert decrypt_password(encrypted) == ""

    def test_different_plaintexts_produce_different_ciphertext(self):
        a = encrypt_password("password-a")
        b = encrypt_password("password-b")
        assert a != b


# ---------------------------------------------------------------------------
# Subject rendering tests
# ---------------------------------------------------------------------------


class TestSubjectRendering:
    def test_scheduled_subject(self, sample_license_info: LicenseInfo):
        context = _build_template_context("scheduled", sample_license_info, 85000)
        subject = render_subject("scheduled", context)
        assert "LOC usage report" in subject
        assert datetime.now(UTC).strftime("%B %Y") in subject

    def test_threshold_warn_subject(self, sample_license_info: LicenseInfo):
        context = _build_template_context("threshold_warn", sample_license_info, 450000)
        subject = render_subject("threshold_warn", context)
        assert "Approaching your LOC limit" in subject

    def test_expiry_subject(self, sample_license_info: LicenseInfo):
        context = _build_template_context("expiry_7d", sample_license_info, 100000)
        subject = render_subject("expiry_7d", context)
        assert "7 days" in subject

    def test_test_subject(self, sample_license_info: LicenseInfo):
        context = _build_template_context("test", sample_license_info, 100000)
        subject = render_subject("test", context)
        assert "Test email" in subject

    def test_unknown_trigger_type(self, sample_license_info: LicenseInfo):
        context = _build_template_context("unknown_type", sample_license_info, 100000)
        subject = render_subject("unknown_type", context)
        assert "unknown_type" in subject

    def test_subject_sanitization(self):
        """Control characters are stripped from subjects."""
        dirty = "Hello\r\nWorld\x00Test"
        clean = _sanitize_subject(dirty)
        assert "\r" not in clean
        assert "\n" not in clean
        assert "\x00" not in clean
        assert "HelloWorldTest" == clean

    def test_all_trigger_types_have_subjects(self):
        """Every trigger type in SUBJECT_MAP produces a non-empty subject."""
        for trigger_type in SUBJECT_MAP:
            context = {"month": "April 2026", "pct": 85.0}
            subject = render_subject(trigger_type, context)
            assert len(subject) > 0


# ---------------------------------------------------------------------------
# Template context tests
# ---------------------------------------------------------------------------


class TestTemplateContext:
    def test_context_with_license(self, sample_license_info: LicenseInfo):
        context = _build_template_context("scheduled", sample_license_info, 420000)
        assert context["trigger_type"] == "scheduled"
        assert context["customer"]["name"] == "Test Customer"
        assert context["customer"]["organization"] == "Acme Corp"
        assert context["loc"]["used"] == 420000
        assert context["loc"]["limit"] == 500000
        assert context["loc"]["percent"] == 84.0
        assert context["tier"]["value"] == 2

    def test_context_without_license(self):
        context = _build_template_context("scheduled", None, 0)
        assert context["customer"]["name"] == ""
        assert context["loc"]["limit"] == 0
        assert context["loc"]["percent"] == 0.0

    def test_zero_loc_limit_avoids_division_by_zero(
        self, sample_license_info: LicenseInfo
    ):
        sample_license_info.license.loc_limit = 0
        context = _build_template_context("threshold_warn", sample_license_info, 100000)
        assert context["loc"]["percent"] == 0.0


# ---------------------------------------------------------------------------
# State change handler tests
# ---------------------------------------------------------------------------


class TestOnLicenseStateChange:
    @pytest.mark.asyncio
    async def test_forward_transition_fires_report(
        self, sample_license_info: LicenseInfo
    ):
        from app.services.email import on_license_state_change

        with patch(
            "app.services.email.send_loc_report", new_callable=AsyncMock
        ) as mock_send:
            await on_license_state_change(
                LicenseState.LICENSED_HEALTHY,
                LicenseState.LICENSED_WARN,
                sample_license_info,
            )
            mock_send.assert_called_once_with("threshold_warn", sample_license_info)

    @pytest.mark.asyncio
    async def test_reverse_transition_is_noop(self, sample_license_info: LicenseInfo):
        from app.services.email import on_license_state_change

        with patch(
            "app.services.email.send_loc_report", new_callable=AsyncMock
        ) as mock_send:
            await on_license_state_change(
                LicenseState.LICENSED_WARN,
                LicenseState.LICENSED_HEALTHY,
                sample_license_info,
            )
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_grace_to_blocked_fires(self, sample_license_info: LicenseInfo):
        from app.services.email import on_license_state_change

        with patch(
            "app.services.email.send_loc_report", new_callable=AsyncMock
        ) as mock_send:
            await on_license_state_change(
                LicenseState.LICENSED_GRACE,
                LicenseState.LICENSED_BLOCKED,
                sample_license_info,
            )
            mock_send.assert_called_once_with("threshold_blocked", sample_license_info)


# ---------------------------------------------------------------------------
# Cadence matcher tests
# ---------------------------------------------------------------------------


class TestCadenceMatcher:
    @pytest.mark.asyncio
    async def test_monthly_match(self):
        """When now matches cadence day+hour, scheduled_report_tick fires."""
        from app.models.db import EmailConfig
        from app.services.email import scheduled_report_tick

        now = datetime.now(UTC)
        mock_config = MagicMock(spec=EmailConfig)
        mock_config.enabled = True
        mock_config.cadence = "monthly"
        mock_config.cadence_day = now.day
        mock_config.cadence_hour_utc = now.hour
        mock_config.recipients = ["test@example.com"]

        mock_session = MagicMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.email._get_email_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch("app.services.email.get_current_license", return_value=None),
            patch(
                "app.services.email.send_loc_report", new_callable=AsyncMock
            ) as mock_send,
            patch(
                "app.services.postgres.get_background_session",
                return_value=mock_session_ctx,
            ),
        ):
            await scheduled_report_tick()
            mock_send.assert_called_once_with("scheduled", None)

    @pytest.mark.asyncio
    async def test_cadence_off_skips(self):
        from app.models.db import EmailConfig
        from app.services.email import scheduled_report_tick

        mock_config = MagicMock(spec=EmailConfig)
        mock_config.enabled = True
        mock_config.cadence = "off"

        mock_session = MagicMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.email._get_email_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "app.services.email.send_loc_report", new_callable=AsyncMock
            ) as mock_send,
            patch(
                "app.services.postgres.get_background_session",
                return_value=mock_session_ctx,
            ),
        ):
            await scheduled_report_tick()
            mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Expiry reminder tests
# ---------------------------------------------------------------------------


class TestExpiryReminder:
    @pytest.mark.asyncio
    async def test_fires_at_7_days(self, sample_license_info: LicenseInfo):
        """When license expires in exactly 7 days, reminder fires."""
        from app.services.email import expiry_reminder_tick

        # Set exp to 7 days + 12 hours from now so .days rounds to 7
        sample_license_info.exp = int(datetime.now(UTC).timestamp()) + 7 * 86400 + 43200

        with (
            patch(
                "app.services.email.get_current_license",
                return_value=sample_license_info,
            ),
            patch(
                "app.services.email.send_loc_report", new_callable=AsyncMock
            ) as mock_send,
        ):
            await expiry_reminder_tick()
            mock_send.assert_called_once()
            assert mock_send.call_args[0][0] == "expiry_7d"

    @pytest.mark.asyncio
    async def test_no_fire_at_8_days(self, sample_license_info: LicenseInfo):
        """8 days is not in the reminder set — no email."""
        from app.services.email import expiry_reminder_tick

        # Set exp to 8 days + 12 hours from now so .days rounds to 8
        sample_license_info.exp = int(datetime.now(UTC).timestamp()) + 8 * 86400 + 43200

        with (
            patch(
                "app.services.email.get_current_license",
                return_value=sample_license_info,
            ),
            patch(
                "app.services.email.send_loc_report", new_callable=AsyncMock
            ) as mock_send,
        ):
            await expiry_reminder_tick()
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_license_skips(self):
        from app.services.email import expiry_reminder_tick

        with (
            patch("app.services.email.get_current_license", return_value=None),
            patch(
                "app.services.email.send_loc_report", new_callable=AsyncMock
            ) as mock_send,
        ):
            await expiry_reminder_tick()
            mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Flentas BCC constant
# ---------------------------------------------------------------------------


class TestFlentasBcc:
    def test_bcc_address_is_set(self):
        assert LICENSE_FLENTAS_BCC_ADDRESS == "usage-reports@flentas.com"

    def test_expiry_reminder_days(self):
        assert EXPIRY_REMINDER_DAYS == frozenset({30, 14, 7, 1})
