"""Authentication API endpoints — login, current user, and first-run setup."""

from __future__ import annotations

from datetime import UTC, datetime

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.config import Settings, get_settings
from app.models.db import User
from app.schemas.auth import (
    LoginResponse,
    SetupRequest,
    SetupStatusResponse,
    UserResponse,
)
from app.services.activity import log_activity
from app.services.auth import create_access_token, hash_password, verify_password
from app.services.postgres import get_session
from app.services.rate_limit import (
    RateLimitBackendUnavailable,
    RateLimitExceeded,
    check_rate_limit,
)
from app.services.redis import get_redis

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    redis: aioredis.Redis = Depends(get_redis),
) -> LoginResponse:
    client_ip = request.client.host if request.client else "unknown"
    try:
        await check_rate_limit(
            redis,
            f"rl:login:{client_ip}",
            window_seconds=60,
            max_requests=5,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except RateLimitBackendUnavailable as exc:
        # Fail-closed: refuse traffic when we cannot enforce the limit.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter backend unavailable",
        ) from exc

    result = await session.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form.password, user.password_hash):
        logger.warning("login_failed", username=form.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        logger.warning("login_inactive_user", username=form.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated",
        )

    user.last_login = datetime.now(UTC)
    await session.commit()

    token = create_access_token(user.id, settings.secret_key)
    logger.info("login_success", user_id=user.id, username=user.username)
    await log_activity(
        session,
        "user.login",
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
    )
    return LoginResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(user, from_attributes=True)


@router.get("/setup-status", response_model=SetupStatusResponse)
async def setup_status(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SetupStatusResponse:
    result = await session.execute(select(func.count()).select_from(User))
    count = result.scalar()
    return SetupStatusResponse(
        needs_setup=count == 0,
        auth_disabled=settings.auth_disabled,
    )


@router.post("/setup", response_model=UserResponse, status_code=201)
async def initial_setup(
    req: SetupRequest,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    result = await session.execute(select(func.count()).select_from(User))
    if result.scalar() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup already completed — users exist",
        )

    user = User(
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        role="admin",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    logger.info("initial_setup_complete", user_id=user.id, username=user.username)
    await log_activity(
        session,
        "user.created",
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
    )
    return UserResponse.model_validate(user, from_attributes=True)
