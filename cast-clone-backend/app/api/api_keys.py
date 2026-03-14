"""API key management endpoints.

Allows creating, listing, and revoking API keys for MCP server access.
Keys are hashed with SHA-256 before storage; the raw key is returned only
on creation and never stored.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.mcp.auth import generate_api_key, hash_api_key
from app.models.db import ApiKey, User
from app.schemas.api_keys import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
)
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=ApiKeyCreateResponse
)
async def create_api_key(
    body: ApiKeyCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyCreateResponse:
    """Create a new API key. Returns the raw key once — it cannot be retrieved later."""
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)

    api_key = ApiKey(
        key_hash=key_hash,
        name=body.name,
        user_id=user.id,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)

    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        raw_key=raw_key,
        created_at=api_key.created_at or "",
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKeyResponse]:
    """List all API keys for the current user (no raw key exposed)."""
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user.id)
        .order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        ApiKeyResponse(
            id=k.id,
            name=k.name,
            is_active=k.is_active,
            created_at=k.created_at or "",
            last_used_at=k.last_used_at,
        )
        for k in keys
    ]


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Revoke an API key (set is_active=false). Does not delete the record."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    api_key.is_active = False
    await session.commit()
    return {"message": "Key revoked"}
