"""Email reporting service — SMTP send, template render, dedup.

Phase A (CHAN-35): Fernet encryption helpers for SMTP password storage.
Phase B (CHAN-36): Full email service — send, render, dedup, scheduler hooks.
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import aiosmtplib
import structlog
from cryptography.fernet import Fernet
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.db import EmailConfig, SentEmail
from app.services.license import LicenseInfo, LicenseState, get_current_license
from app.services.loc_usage import cumulative_loc

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Flentas BCC address — hardcoded in backend image, not configurable from UI
LICENSE_FLENTAS_BCC_ADDRESS = "usage-reports@flentas.com"

# Subject sanitizer — strip control chars to prevent header injection
_SUBJECT_UNSAFE = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]")

DEDUP_WINDOW_HOURS = 24

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"

# Jinja2 environment with autoescape for HTML safety
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)

# Trigger types that fire threshold alerts (forward transitions only)
_THRESHOLD_TRIGGERS: dict[tuple[LicenseState, LicenseState], str] = {
    (LicenseState.LICENSED_HEALTHY, LicenseState.LICENSED_WARN): "threshold_warn",
    (LicenseState.LICENSED_WARN, LicenseState.LICENSED_GRACE): "threshold_grace",
    (LicenseState.LICENSED_GRACE, LicenseState.LICENSED_BLOCKED): "threshold_blocked",
}

# Expiry reminder days
EXPIRY_REMINDER_DAYS = frozenset({30, 14, 7, 1})

# ---------------------------------------------------------------------------
# Encryption helpers (CHAN-35)
# ---------------------------------------------------------------------------


def _derive_fernet_key(secret_key: str) -> bytes:
    """Derive a 32-byte Fernet key from the app's SECRET_KEY using SHA-256."""
    digest = hashlib.sha256(secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_password(plaintext: str) -> bytes:
    """Encrypt an SMTP password with Fernet keyed off SECRET_KEY."""
    settings = get_settings()
    f = Fernet(_derive_fernet_key(settings.secret_key))
    return f.encrypt(plaintext.encode())


def decrypt_password(ciphertext: bytes) -> str:
    """Decrypt an SMTP password encrypted with encrypt_password()."""
    settings = get_settings()
    f = Fernet(_derive_fernet_key(settings.secret_key))
    return f.decrypt(ciphertext).decode()


# ---------------------------------------------------------------------------
# Pydantic result model
# ---------------------------------------------------------------------------


class SendResult(BaseModel):
    status: str  # "sent" | "failed"
    error: str | None = None


# ---------------------------------------------------------------------------
# Subject rendering
# ---------------------------------------------------------------------------

SUBJECT_MAP: dict[str, str] = {
    "scheduled": "ChangeSafe — LOC usage report for {month}",
    "threshold_warn": "ChangeSafe — Approaching your LOC limit ({pct}%)",
    "threshold_grace": "ChangeSafe — LOC limit reached; grace period started",
    "threshold_blocked": "ChangeSafe — New analyses disabled; contact sales to upgrade",
    "expiry_30d": "ChangeSafe — License expires in 30 days",
    "expiry_14d": "ChangeSafe — License expires in 14 days",
    "expiry_7d": "ChangeSafe — License expires in 7 days",
    "expiry_1d": "ChangeSafe — License expires in 1 day",
    "test": "ChangeSafe — Test email",
}


def _sanitize_subject(subject: str) -> str:
    return _SUBJECT_UNSAFE.sub("", subject).strip()


def render_subject(trigger_type: str, context: dict[str, Any]) -> str:
    template = SUBJECT_MAP.get(trigger_type, f"ChangeSafe — {trigger_type}")
    try:
        rendered = template.format(**context)
    except KeyError:
        rendered = template
    return _sanitize_subject(rendered)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def _build_template_context(
    trigger_type: str,
    license_info: LicenseInfo | None,
    loc_used: int,
) -> dict[str, Any]:
    """Build the context dict passed to Jinja2 templates."""
    loc_limit = license_info.license.loc_limit if license_info else 0
    pct = round(loc_used / loc_limit * 100, 1) if loc_limit > 0 else 0.0
    exp_ts = license_info.exp if license_info else 0
    exp_dt = datetime.fromtimestamp(exp_ts, tz=UTC) if exp_ts else None
    days_remaining = (exp_dt - datetime.now(UTC)).days if exp_dt else 0

    return {
        "trigger_type": trigger_type,
        "customer": {
            "name": license_info.license.customer.name if license_info else "",
            "organization": (
                license_info.license.customer.organization if license_info else ""
            ),
        },
        "tier": {
            "value": license_info.license.tier if license_info else None,
            "label": f"Tier {license_info.license.tier}" if license_info else "N/A",
        },
        "loc": {"used": loc_used, "limit": loc_limit, "percent": pct},
        "expiry": {"at": exp_dt, "days_remaining": days_remaining},
        "state": "",
        "renewal_contact": "sales@flentas.com",
        "deployment_label": "",
        "month": datetime.now(UTC).strftime("%B %Y"),
        "pct": pct,
    }


def _render_email(trigger_type: str, context: dict[str, Any]) -> tuple[str, str]:
    """Render HTML and plain-text bodies. Returns (html, text)."""
    html_tmpl = _jinja_env.get_template("loc_report.html")
    text_tmpl = _jinja_env.get_template("loc_report.txt")
    return html_tmpl.render(**context), text_tmpl.render(**context)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


async def _get_email_config(session: AsyncSession) -> EmailConfig | None:
    result = await session.execute(select(EmailConfig).limit(1))
    return result.scalar_one_or_none()


async def _should_send(
    session: AsyncSession, license_jti: str, trigger_type: str
) -> bool:
    """Dedup check: has this (jti, trigger_type) been sent in the last 24h?"""
    cutoff = datetime.now(UTC) - timedelta(hours=DEDUP_WINDOW_HOURS)
    result = await session.execute(
        select(SentEmail)
        .where(
            SentEmail.license_jti == license_jti,
            SentEmail.trigger_type == trigger_type,
            SentEmail.sent_at >= cutoff,
            SentEmail.delivery_status.in_(["sent"]),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is None


async def _log_sent_email(
    session: AsyncSession,
    *,
    trigger_type: str,
    license_jti: str,
    subject: str,
    recipients: list[str],
    delivery_status: str,
    error_message: str | None = None,
) -> None:
    row = SentEmail(
        trigger_type=trigger_type,
        license_jti=license_jti,
        subject=subject,
        recipients=recipients,
        delivery_status=delivery_status,
        error_message=error_message,
    )
    session.add(row)
    await session.commit()


# ---------------------------------------------------------------------------
# SMTP send
# ---------------------------------------------------------------------------


async def _smtp_send(
    config: EmailConfig,
    *,
    to: list[str],
    bcc: list[str],
    subject: str,
    html_body: str,
    text_body: str,
) -> SendResult:
    """Send a multipart email via aiosmtplib."""
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{config.from_name} <{config.from_address}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    all_recipients = list(set(to + bcc))

    try:
        smtp_password = (
            decrypt_password(config.smtp_password_encrypted)
            if config.smtp_password_encrypted
            else None
        )
        await aiosmtplib.send(
            msg,
            hostname=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_username or None,
            password=smtp_password,
            use_tls=config.smtp_use_tls,
            recipients=all_recipients,
        )
        return SendResult(status="sent")
    except Exception as exc:
        await logger.aerror("email.smtp_send_failed", error=str(exc))
        return SendResult(status="failed", error=str(exc))


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


async def send_loc_report(
    trigger_type: str,
    license_info: LicenseInfo | None = None,
    force: bool = False,
) -> None:
    """Render and send a LOC report email for the given trigger.

    Performs dedup check unless force=True.
    Logs to sent_email table regardless of delivery outcome.
    """
    from app.services.postgres import get_background_session

    async with get_background_session() as session:
        config = await _get_email_config(session)
        if not config or not config.enabled:
            await _log_sent_email(
                session,
                trigger_type=trigger_type,
                license_jti=license_info.jti if license_info else "",
                subject="",
                recipients=[],
                delivery_status="skipped_disabled",
            )
            return

        if not config.recipients:
            return

        jti = license_info.jti if license_info else ""

        # Dedup check (skip for scheduled — cadence handles its own frequency)
        if not force and trigger_type != "scheduled":
            if not await _should_send(session, jti, trigger_type):
                await _log_sent_email(
                    session,
                    trigger_type=trigger_type,
                    license_jti=jti,
                    subject="",
                    recipients=config.recipients,
                    delivery_status="skipped_dedup",
                )
                return

        loc_used = await cumulative_loc()
        context = _build_template_context(trigger_type, license_info, loc_used)
        subject = render_subject(trigger_type, context)
        html_body, text_body = _render_email(trigger_type, context)

        bcc: list[str] = []
        if config.flentas_bcc_enabled:
            bcc.append(LICENSE_FLENTAS_BCC_ADDRESS)

        result = await _smtp_send(
            config,
            to=config.recipients,
            bcc=bcc,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

        await _log_sent_email(
            session,
            trigger_type=trigger_type,
            license_jti=jti,
            subject=subject,
            recipients=config.recipients + bcc,
            delivery_status=result.status,
            error_message=result.error,
        )


async def test_send(to_address: str) -> SendResult:
    """Admin-triggered test email. Bypasses dedup. Does NOT write to sent_email."""
    from app.services.postgres import get_background_session

    async with get_background_session() as session:
        config = await _get_email_config(session)
        if not config:
            return SendResult(status="failed", error="Email not configured")

    license_info = get_current_license()
    loc_used = await cumulative_loc()
    context = _build_template_context("test", license_info, loc_used)
    subject = render_subject("test", context)
    html_body, text_body = _render_email("test", context)

    return await _smtp_send(
        config,
        to=[to_address],
        bcc=[],
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )


async def on_license_state_change(
    old_state: LicenseState,
    new_state: LicenseState,
    license_info: LicenseInfo | None,
) -> None:
    """Subscribed to license state transitions.

    Fires threshold alerts on forward transitions only:
    HEALTHY->WARN, WARN->GRACE, GRACE->BLOCKED.
    No-op on reverse transitions or when license_info is None.
    """
    trigger = _THRESHOLD_TRIGGERS.get((old_state, new_state))
    if trigger is None:
        return

    await logger.ainfo(
        "email.threshold_alert",
        trigger=trigger,
        old_state=old_state.value,
        new_state=new_state.value,
    )
    await send_loc_report(trigger, license_info)


# ---------------------------------------------------------------------------
# Scheduler job functions (used by CHAN-39)
# ---------------------------------------------------------------------------


async def scheduled_report_tick() -> None:
    """Hourly tick — check if now matches configured cadence, fire if so."""
    from app.services.postgres import get_background_session

    async with get_background_session() as session:
        config = await _get_email_config(session)

    if not config or not config.enabled or config.cadence == "off":
        return

    now = datetime.now(UTC)
    hour_matches = now.hour == config.cadence_hour_utc

    if config.cadence == "monthly":
        day_matches = now.day == config.cadence_day
    elif config.cadence == "weekly":
        day_matches = now.weekday() == config.cadence_day
    else:
        return

    if hour_matches and day_matches:
        license_info = get_current_license()
        await send_loc_report("scheduled", license_info)


async def expiry_reminder_tick() -> None:
    """Daily tick at 08:00 UTC — fire expiry reminders at 30/14/7/1 days."""
    license_info = get_current_license()
    if not license_info:
        return

    exp_dt = datetime.fromtimestamp(license_info.exp, tz=UTC)
    days_remaining = (exp_dt - datetime.now(UTC)).days

    if days_remaining in EXPIRY_REMINDER_DAYS:
        trigger_type = f"expiry_{days_remaining}d"
        await send_loc_report(trigger_type, license_info)
