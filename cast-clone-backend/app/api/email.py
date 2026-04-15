"""Email configuration and test-send endpoints (CHAN-40)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.models.db import EmailConfig, User
from app.services.email import SendResult, encrypt_password, test_send
from app.services.postgres import get_session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/email", tags=["email"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class EmailConfigResponse(BaseModel):
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool
    from_address: str
    from_name: str
    recipients: list[str]
    flentas_bcc_enabled: bool
    cadence: str
    cadence_day: int
    cadence_hour_utc: int


class EmailConfigUpdateRequest(BaseModel):
    enabled: bool
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    from_address: str = ""
    from_name: str = "ChangeSafe"
    recipients: list[str] = []
    flentas_bcc_enabled: bool = False
    cadence: str = "off"
    cadence_day: int = 1
    cadence_hour_utc: int = 9


class TestSendRequest(BaseModel):
    to: str


class TestSendResponse(BaseModel):
    status: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_to_response(config: EmailConfig) -> EmailConfigResponse:
    return EmailConfigResponse(
        enabled=config.enabled,
        smtp_host=config.smtp_host,
        smtp_port=config.smtp_port,
        smtp_username=config.smtp_username,
        smtp_password="***" if config.smtp_password_encrypted else "",
        smtp_use_tls=config.smtp_use_tls,
        from_address=config.from_address,
        from_name=config.from_name,
        recipients=config.recipients or [],
        flentas_bcc_enabled=config.flentas_bcc_enabled,
        cadence=config.cadence,
        cadence_day=config.cadence_day,
        cadence_hour_utc=config.cadence_hour_utc,
    )


_DEFAULT_RESPONSE = EmailConfigResponse(
    enabled=False,
    smtp_host="",
    smtp_port=587,
    smtp_username="",
    smtp_password="",
    smtp_use_tls=True,
    from_address="",
    from_name="ChangeSafe",
    recipients=[],
    flentas_bcc_enabled=False,
    cadence="off",
    cadence_day=1,
    cadence_hour_utc=9,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/config", response_model=EmailConfigResponse)
async def get_email_config(
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> EmailConfigResponse:
    result = await session.execute(select(EmailConfig).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        return _DEFAULT_RESPONSE
    return _config_to_response(config)


@router.put("/config", response_model=EmailConfigResponse)
async def update_email_config(
    body: EmailConfigUpdateRequest,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> EmailConfigResponse:
    result = await session.execute(select(EmailConfig).limit(1))
    config = result.scalar_one_or_none()

    if config is None:
        config = EmailConfig()
        session.add(config)

    # Update fields
    config.enabled = body.enabled
    config.smtp_host = body.smtp_host
    config.smtp_port = body.smtp_port
    config.smtp_username = body.smtp_username
    config.smtp_use_tls = body.smtp_use_tls
    config.from_address = body.from_address
    config.from_name = body.from_name
    config.recipients = body.recipients
    config.flentas_bcc_enabled = body.flentas_bcc_enabled
    config.cadence = body.cadence
    config.cadence_day = body.cadence_day
    config.cadence_hour_utc = body.cadence_hour_utc

    # Password: "***" means preserve existing, anything else means encrypt new
    if body.smtp_password != "***":
        if body.smtp_password:
            config.smtp_password_encrypted = encrypt_password(body.smtp_password)
        else:
            config.smtp_password_encrypted = None

    await session.commit()
    await session.refresh(config)

    await logger.ainfo("email.config_updated", admin=_admin.username)
    return _config_to_response(config)


@router.post("/test-send", response_model=TestSendResponse)
async def send_test_email(
    body: TestSendRequest,
    _admin: User = Depends(require_admin),
) -> TestSendResponse:
    result: SendResult = await test_send(body.to)
    await logger.ainfo(
        "email.test_send",
        admin=_admin.username,
        to=body.to,
        status=result.status,
    )
    return TestSendResponse(status=result.status, error=result.error)
