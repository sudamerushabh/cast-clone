"""Git configuration CRUD endpoints for repositories."""

from __future__ import annotations

import secrets

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.config import Settings, get_settings
from app.models.db import RepositoryGitConfig, User
from app.schemas.git_config import (
    GitConfigCreate,
    GitConfigResponse,
    GitConfigUpdate,
    WebhookUrlResponse,
)
from app.services.crypto import decrypt_token, encrypt_token
from app.services.git_providers import create_provider
from app.services.postgres import get_session

logger = structlog.get_logger()

router = APIRouter(
    prefix="/api/v1/repositories/{repo_id}/git-config",
    tags=["git-config"],
)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_git_config(
    repo_id: str,
    body: GitConfigCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Create a new git configuration for a repository."""
    result = await session.execute(
        select(RepositoryGitConfig).where(
            RepositoryGitConfig.repository_id == repo_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Git config already exists for this repository",
        )

    webhook_secret = secrets.token_urlsafe(32)
    encrypted_token = encrypt_token(body.api_token, settings.secret_key)

    config = RepositoryGitConfig(
        repository_id=repo_id,
        platform=body.platform,
        repo_url=body.repo_url,
        api_token_encrypted=encrypted_token,
        webhook_secret=webhook_secret,
        monitored_branches=body.monitored_branches,
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)

    base_url = str(request.base_url).rstrip("/")
    webhook_url = f"{base_url}/api/v1/webhooks/{body.platform}/{repo_id}"

    await logger.ainfo(
        "git_config_created", repo_id=repo_id, platform=body.platform
    )

    return {
        "id": config.id,
        "repository_id": config.repository_id,
        "platform": config.platform,
        "repo_url": config.repo_url,
        "monitored_branches": config.monitored_branches,
        "is_active": config.is_active,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        "webhook_url": webhook_url,
        "webhook_secret": webhook_secret,
    }


@router.get("", response_model=GitConfigResponse)
async def get_git_config(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> GitConfigResponse:
    """Get the git configuration for a repository."""
    result = await session.execute(
        select(RepositoryGitConfig).where(
            RepositoryGitConfig.repository_id == repo_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Git config not found for this repository",
        )
    return GitConfigResponse.model_validate(config)


@router.put("", response_model=GitConfigResponse)
async def update_git_config(
    repo_id: str,
    body: GitConfigUpdate,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> GitConfigResponse:
    """Update the git configuration for a repository."""
    result = await session.execute(
        select(RepositoryGitConfig).where(
            RepositoryGitConfig.repository_id == repo_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Git config not found for this repository",
        )

    update_data = body.model_dump(exclude_unset=True)
    if "api_token" in update_data:
        update_data["api_token_encrypted"] = encrypt_token(
            update_data.pop("api_token"), settings.secret_key
        )
    for key, value in update_data.items():
        setattr(config, key, value)

    await session.commit()
    await session.refresh(config)

    await logger.ainfo("git_config_updated", repo_id=repo_id)
    return GitConfigResponse.model_validate(config)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_git_config(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> None:
    """Delete the git configuration for a repository."""
    result = await session.execute(
        select(RepositoryGitConfig).where(
            RepositoryGitConfig.repository_id == repo_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Git config not found for this repository",
        )
    await session.delete(config)
    await session.commit()
    await logger.ainfo("git_config_deleted", repo_id=repo_id)


@router.get("/webhook-url", response_model=WebhookUrlResponse)
async def get_webhook_url(
    repo_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> WebhookUrlResponse:
    """Get the webhook URL and secret for a repository's git config."""
    result = await session.execute(
        select(RepositoryGitConfig).where(
            RepositoryGitConfig.repository_id == repo_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Git config not found for this repository",
        )

    base_url = str(request.base_url).rstrip("/")
    webhook_url = f"{base_url}/api/v1/webhooks/{config.platform}/{repo_id}"

    return WebhookUrlResponse(
        webhook_url=webhook_url,
        webhook_secret=config.webhook_secret,
    )


@router.post("/test")
async def test_git_connectivity(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Test connectivity to the git platform using stored credentials."""
    result = await session.execute(
        select(RepositoryGitConfig).where(
            RepositoryGitConfig.repository_id == repo_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Git config not found for this repository",
        )

    try:
        token = decrypt_token(config.api_token_encrypted, settings.secret_key)
        provider = create_provider(
            provider=config.platform,
            base_url=config.repo_url,
            token=token,
        )
        user = await provider.validate()
        return {
            "status": "connected",
            "remote_username": user.username,
        }
    except Exception as exc:
        await logger.awarn(
            "git_config_test_failed", repo_id=repo_id, error=str(exc)
        )
        return {
            "status": "error",
            "message": str(exc),
        }
