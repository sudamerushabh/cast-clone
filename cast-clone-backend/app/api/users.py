"""User management API endpoints — admin only."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.models.db import User
from app.schemas.auth import UserCreateRequest, UserResponse, UserUpdateRequest
from app.services.activity import log_activity
from app.services.auth import hash_password
from app.services.postgres import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> list[UserResponse]:
    """List all users. Admin only."""
    result = await session.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [UserResponse.model_validate(u, from_attributes=True) for u in users]


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    req: UserCreateRequest,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> UserResponse:
    """Create a new user. Admin only."""
    existing = await session.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists",
        )

    user = User(
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        role=req.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await log_activity(
        session, "user.admin_created", user_id=_admin.id,
        resource_type="user", resource_id=user.id,
        details={"username": user.username, "role": user.role},
    )
    return UserResponse.model_validate(user, from_attributes=True)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> UserResponse:
    """Get a user by ID. Admin only."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user, from_attributes=True)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> UserResponse:
    """Update a user. Admin only."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.username is not None:
        dup = await session.execute(
            select(User).where(User.username == req.username, User.id != user_id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username already taken")
        user.username = req.username
    if req.email is not None:
        dup = await session.execute(
            select(User).where(User.email == req.email, User.id != user_id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already taken")
        user.email = req.email
    if req.password is not None:
        user.password_hash = hash_password(req.password)
    if req.role is not None:
        user.role = req.role
    if req.is_active is not None:
        user.is_active = req.is_active

    await session.commit()
    await session.refresh(user)
    await log_activity(
        session, "user.updated", user_id=_admin.id,
        resource_type="user", resource_id=user.id,
        details={"username": user.username},
    )
    return UserResponse.model_validate(user, from_attributes=True)


@router.delete("/{user_id}", status_code=204)
async def deactivate_user(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> None:
    """Deactivate a user (soft delete). Admin only."""
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate yourself",
        )
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    await session.commit()

    await log_activity(
        session, "user.deactivated", user_id=admin.id,
        resource_type="user", resource_id=user.id,
        details={"username": user.username},
    )
