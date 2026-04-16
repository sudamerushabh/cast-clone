"""Git Connector CRUD + remote repo browsing API endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_admin
from app.config import Settings
from app.models.db import GitConnector, User
from app.schemas.connectors import (
    BranchListResponse,
    ConnectorCreate,
    ConnectorListResponse,
    ConnectorResponse,
    ConnectorTestResponse,
    ConnectorUpdate,
    RemoteRepoListResponse,
    RemoteRepoResponse,
)
from app.api.dependencies import get_current_user
from app.models.db import User
from app.services.activity import log_activity
from app.services.crypto import decrypt_token, encrypt_token
from app.services.git_providers import create_provider
from app.services.postgres import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


def _get_settings() -> Settings:
    return Settings()


def _connector_to_response(c: GitConnector) -> ConnectorResponse:
    return ConnectorResponse(
        id=c.id,
        name=c.name,
        provider=c.provider,
        base_url=c.base_url,
        auth_method=c.auth_method,
        status=c.status,
        remote_username=c.remote_username,
        created_by=c.created_by,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


async def _get_connector_or_404(
    connector_id: str, session: AsyncSession
) -> GitConnector:
    result = await session.execute(
        select(GitConnector).where(GitConnector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )
    return connector


@router.post("", response_model=ConnectorResponse, status_code=status.HTTP_201_CREATED)
async def create_connector(
    body: ConnectorCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(_get_settings),
    _user: User = Depends(get_current_user),
) -> ConnectorResponse:
    """Create a new git connector. Validates the token. Admin only."""
    # Validate token by calling the provider API
    provider = create_provider(body.provider, body.base_url, body.token)
    try:
        user = await provider.validate()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to validate token: {exc}",
        ) from exc

    encrypted = encrypt_token(body.token, settings.secret_key)

    connector = GitConnector(
        name=body.name,
        provider=body.provider,
        base_url=body.base_url,
        auth_method="pat",
        encrypted_token=encrypted,
        status="connected",
        remote_username=user.username,
        created_by=admin.id,
    )
    session.add(connector)
    await session.commit()
    await session.refresh(connector)

    await log_activity(
        session,
        "connector.created",
        user_id=_user.id,
        resource_type="connector",
        resource_id=connector.id,
        details={"name": body.name, "provider": body.provider},
    )

    return _connector_to_response(connector)


@router.get("", response_model=ConnectorListResponse)
async def list_connectors(
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConnectorListResponse:
    """List all git connectors."""
    count_result = await session.execute(select(func.count(GitConnector.id)))
    total = count_result.scalar_one()

    result = await session.execute(
        select(GitConnector)
        .order_by(GitConnector.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    connectors = result.scalars().all()

    return ConnectorListResponse(
        connectors=[_connector_to_response(c) for c in connectors],
        total=total,
    )


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(
    connector_id: str,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConnectorResponse:
    """Get a single connector by ID."""
    connector = await _get_connector_or_404(connector_id, session)
    return _connector_to_response(connector)


@router.put("/{connector_id}", response_model=ConnectorResponse)
async def update_connector(
    connector_id: str,
    body: ConnectorUpdate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(_get_settings),
) -> ConnectorResponse:
    """Update a connector's name or token. Admin only."""
    connector = await _get_connector_or_404(connector_id, session)

    if body.name is not None:
        connector.name = body.name

    if body.token is not None:
        # Re-validate token
        provider = create_provider(connector.provider, connector.base_url, body.token)
        try:
            user = await provider.validate()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to validate new token: {exc}",
            ) from exc
        connector.encrypted_token = encrypt_token(body.token, settings.secret_key)
        connector.remote_username = user.username
        connector.status = "connected"

    await session.commit()
    await session.refresh(connector)
    return _connector_to_response(connector)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: str,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> Response:
    """Delete a connector. Admin only."""
    connector = await _get_connector_or_404(connector_id, session)
    connector_name = connector.name
    connector_provider = connector.provider
    await session.delete(connector)
    await session.commit()

    await log_activity(
        session,
        "connector.deleted",
        user_id=_user.id,
        resource_type="connector",
        resource_id=connector_id,
        details={"name": connector_name, "provider": connector_provider},
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{connector_id}/test", response_model=ConnectorTestResponse)
async def test_connector(
    connector_id: str,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(_get_settings),
) -> ConnectorTestResponse:
    """Test a connector's token validity. Admin only."""
    connector = await _get_connector_or_404(connector_id, session)
    token = decrypt_token(connector.encrypted_token, settings.secret_key)
    provider = create_provider(connector.provider, connector.base_url, token)

    try:
        user = await provider.validate()
        connector.status = "connected"
        connector.remote_username = user.username
        await session.commit()
        return ConnectorTestResponse(status="connected", remote_username=user.username)
    except Exception as exc:
        connector.status = "error"
        await session.commit()
        return ConnectorTestResponse(status="error", error=str(exc))


@router.get("/{connector_id}/repos", response_model=RemoteRepoListResponse)
async def list_remote_repos(
    connector_id: str,
    page: int = Query(1, ge=1, le=100),
    per_page: int = Query(30, ge=1, le=100),
    search: str | None = None,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(_get_settings),
) -> RemoteRepoListResponse:
    """List repositories accessible via this connector."""
    connector = await _get_connector_or_404(connector_id, session)
    token = decrypt_token(connector.encrypted_token, settings.secret_key)
    provider = create_provider(connector.provider, connector.base_url, token)

    try:
        repos, has_more = await provider.list_repos(page, per_page, search)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list repos: {exc}",
        ) from exc

    return RemoteRepoListResponse(
        repos=[
            RemoteRepoResponse(
                full_name=r.full_name,
                clone_url=r.clone_url,
                default_branch=r.default_branch,
                description=r.description,
                language=r.language,
                is_private=r.is_private,
            )
            for r in repos
        ],
        has_more=has_more,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/{connector_id}/repos/{owner}/{repo}",
    response_model=RemoteRepoResponse,
)
async def get_remote_repo(
    connector_id: str,
    owner: str,
    repo: str,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(_get_settings),
) -> RemoteRepoResponse:
    """Get details for a specific remote repository."""
    connector = await _get_connector_or_404(connector_id, session)
    token = decrypt_token(connector.encrypted_token, settings.secret_key)
    provider = create_provider(connector.provider, connector.base_url, token)

    full_name = f"{owner}/{repo}"
    try:
        r = await provider.get_repo(full_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to get repo: {exc}",
        ) from exc

    return RemoteRepoResponse(
        full_name=r.full_name,
        clone_url=r.clone_url,
        default_branch=r.default_branch,
        description=r.description,
        language=r.language,
        is_private=r.is_private,
    )


@router.get(
    "/{connector_id}/repos/{owner}/{repo}/branches",
    response_model=BranchListResponse,
)
async def list_remote_branches(
    connector_id: str,
    owner: str,
    repo: str,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(_get_settings),
) -> BranchListResponse:
    """List branches for a remote repository."""
    connector = await _get_connector_or_404(connector_id, session)
    token = decrypt_token(connector.encrypted_token, settings.secret_key)
    provider = create_provider(connector.provider, connector.base_url, token)

    full_name = f"{owner}/{repo}"
    try:
        branches = await provider.list_branches(full_name)
        r = await provider.get_repo(full_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list branches: {exc}",
        ) from exc

    return BranchListResponse(
        branches=branches,
        default_branch=r.default_branch,
    )
