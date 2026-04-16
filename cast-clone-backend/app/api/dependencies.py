"""Reusable FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.models.db import Project, Repository, User
from app.services.auth import decode_access_token
from app.services.license import LicenseState
from app.services.postgres import get_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _make_anonymous_admin() -> User:
    """Return a synthetic admin user when auth is disabled."""
    return User(
        id="00000000-0000-0000-0000-000000000000",
        username="anonymous",
        email="anonymous@localhost",
        password_hash="",
        role="admin",
        is_active=True,
    )


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    """Extract and validate the current user from a Bearer token.

    When AUTH_DISABLED=true, returns a synthetic admin user without
    requiring a token — useful for local development and testing.
    """
    if settings.auth_disabled:
        return _make_anonymous_admin()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_access_token(token, settings.secret_key)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    result = await session.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Require the current user to have the admin role.

    When auth is disabled, get_current_user already returns an admin,
    so this passes through.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def get_optional_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Return the current user if a valid token is provided, otherwise None.

    When AUTH_DISABLED=true, always returns the synthetic admin user.
    """
    if settings.auth_disabled:
        return _make_anonymous_admin()

    if not token:
        return None
    user_id = decode_access_token(token, settings.secret_key)
    if not user_id:
        return None
    result = await session.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def get_accessible_project(
    project_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Project:
    """Load a project and verify the caller can access it.

    Admins see all projects. Non-admins see projects whose parent repository
    has ``created_by == user.id``. Projects without a linked repository are
    currently accessible to any authenticated user — tracked as a schema
    gap (Project needs ``created_by`` column; see xfail in
    tests/integration/test_idor_protection.py).

    Raises 404 if the project doesn't exist.
    Raises 403 if the caller is not admin and not the repo creator.
    """
    stmt = (
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.repository))
    )
    result = await session.execute(stmt)
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    if user.role == "admin":
        return project
    repo = project.repository
    if repo is not None and repo.created_by == user.id:
        return project
    if repo is None:
        # Standalone projects have no ownership chain (Project lacks a
        # created_by column). Until the schema migration lands, only admins
        # may access them — non-admins get 403 to close the IDOR gap.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden",
    )


async def get_accessible_repository(
    repository_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Repository:
    """Load a repository and verify the caller can access it.

    Admins see all repositories. Non-admins see only repositories they
    created (``Repository.created_by == user.id``).

    Raises 404 if the repository doesn't exist.
    Raises 403 if the caller is not admin and not the repo creator.
    """
    result = await session.execute(
        select(Repository).where(Repository.id == repository_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found",
        )
    if user.role == "admin":
        return repo
    if repo.created_by == user.id:
        return repo
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden",
    )


# ---------------------------------------------------------------------------
# License gating (CHAN-17)
# ---------------------------------------------------------------------------
_BLOCKED_WRITE_STATES = frozenset({
    LicenseState.UNLICENSED,
    LicenseState.LICENSED_BLOCKED,
})


async def require_license_writable(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Gate write endpoints on license state.

    Returns quietly when license is HEALTHY / WARN / GRACE (or when
    LICENSE_DISABLED=true).  Raises 402 Payment Required when UNLICENSED
    or LICENSED_BLOCKED.
    """
    if settings.license_disabled:
        return  # dev escape hatch — mirrors auth_disabled pattern

    current_state: LicenseState = getattr(
        request.app.state, "license_state", LicenseState.UNLICENSED
    )
    if current_state in _BLOCKED_WRITE_STATES:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "license_required",
                "state": current_state.value,
                "message": (
                    "No valid license. Upload a license file at /settings/license."
                    if current_state == LicenseState.UNLICENSED
                    else "License limit exceeded or expired beyond grace period."
                ),
            },
        )
