"""Authentication API endpoints — login, current user, and first-run setup."""
from __future__ import annotations

import structlog
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.config import get_settings, Settings
from app.models.db import User
from app.schemas.auth import (
    LoginResponse,
    SetupRequest,
    SetupStatusResponse,
    UserResponse,
)
from app.services.auth import create_access_token, hash_password, verify_password
from app.services.postgres import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    result = await session.execute(
        select(User).where(User.username == form.username)
    )
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

    user.last_login = datetime.now(timezone.utc)
    await session.commit()

    token = create_access_token(user.id, settings.secret_key)
    logger.info("login_success", user_id=user.id, username=user.username)
    return LoginResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(user, from_attributes=True)


@router.get("/setup-status", response_model=SetupStatusResponse)
async def setup_status(
    session: AsyncSession = Depends(get_session),
) -> SetupStatusResponse:
    result = await session.execute(select(func.count()).select_from(User))
    count = result.scalar()
    return SetupStatusResponse(needs_setup=count == 0)


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
    return UserResponse.model_validate(user, from_attributes=True)
