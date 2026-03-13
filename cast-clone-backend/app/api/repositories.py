"""Repository CRUD, clone management, and branch operations."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from uuid import uuid4

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models.db import AnalysisRun, GitConnector, Project, Repository
from app.schemas.repositories import (
    BranchAddRequest,
    BranchCompareResponse,
    CloneStatusResponse,
    EvolutionTimelineResponse,
    ProjectBranchResponse,
    RepositoryCreate,
    RepositoryListResponse,
    RepositoryResponse,
    SnapshotPoint,
)
from app.services.clone import clone_repo, pull_latest
from app.services.crypto import decrypt_token
from app.services.git_providers import create_provider
from app.services.postgres import _session_factory, get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/repositories", tags=["repositories"])


def _get_settings() -> Settings:
    return Settings()


def _repo_to_response(repo: Repository) -> RepositoryResponse:
    projects = []
    for p in repo.projects:
        # Find latest completed run for this project
        last_analyzed_at = None
        node_count = None
        edge_count = None
        projects.append(
            ProjectBranchResponse(
                id=p.id,
                branch=p.branch,
                status=p.status,
                last_analyzed_at=last_analyzed_at,
                node_count=node_count,
                edge_count=edge_count,
            )
        )
    return RepositoryResponse(
        id=repo.id,
        connector_id=repo.connector_id,
        repo_full_name=repo.repo_full_name,
        default_branch=repo.default_branch,
        description=repo.description,
        language=repo.language,
        is_private=repo.is_private,
        clone_status=repo.clone_status,
        clone_error=repo.clone_error,
        local_path=repo.local_path,
        last_synced_at=repo.last_synced_at,
        created_at=repo.created_at,
        projects=projects,
    )


async def _background_clone(
    repo_id: str, clone_url: str, token: str, target_dir: str
) -> None:
    """Background task: clone the repository and update status in DB."""
    assert _session_factory is not None, "PostgreSQL not initialized"
    async with _session_factory() as session:
        result = await session.execute(
            select(Repository).where(Repository.id == repo_id)
        )
        repo = result.scalar_one_or_none()
        if repo is None:
            return

        repo.clone_status = "cloning"
        await session.commit()

        try:
            await clone_repo(clone_url, token, target_dir)
            repo.clone_status = "cloned"
            repo.local_path = target_dir
            repo.clone_error = None
        except Exception as exc:
            repo.clone_status = "failed"
            repo.clone_error = str(exc)
            await logger.awarning(
                "clone_failed", repo_id=repo_id, error=str(exc)
            )

        await session.commit()


@router.post(
    "", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED
)
async def create_repository(
    body: RepositoryCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(_get_settings),
) -> RepositoryResponse:
    """Onboard a repository: fetch info, create repo + projects, clone."""
    # Fetch connector
    result = await session.execute(
        select(GitConnector).where(GitConnector.id == body.connector_id)
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {body.connector_id} not found",
        )

    token = decrypt_token(connector.encrypted_token, settings.secret_key)
    provider = create_provider(connector.provider, connector.base_url, token)

    # Fetch repo metadata from provider
    try:
        remote_repo = await provider.get_repo(body.repo_full_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch repo info: {exc}",
        ) from exc

    # Create Repository record
    repo_id = str(uuid4())
    repo = Repository(
        id=repo_id,
        connector_id=connector.id,
        repo_full_name=remote_repo.full_name,
        repo_clone_url=remote_repo.clone_url,
        default_branch=remote_repo.default_branch,
        description=remote_repo.description,
        language=remote_repo.language,
        is_private=remote_repo.is_private,
        clone_status="pending",
    )
    session.add(repo)
    await session.flush()

    # Create a Project for each requested branch
    target_dir = str(Path(settings.repo_storage_path) / repo_id)
    for branch in body.branches:
        project = Project(
            name=f"{remote_repo.full_name}:{branch}",
            source_path=target_dir,
            status="created",
            repository_id=repo.id,
            branch=branch,
        )
        session.add(project)

    await session.commit()
    await session.refresh(repo, attribute_names=["projects"])

    # Start background clone
    background_tasks.add_task(
        _background_clone,
        repo.id,
        remote_repo.clone_url,
        token,
        target_dir,
    )

    await logger.ainfo(
        "repository_created",
        repo_id=repo.id,
        full_name=remote_repo.full_name,
        branches=body.branches,
    )
    return _repo_to_response(repo)


@router.get("", response_model=RepositoryListResponse)
async def list_repositories(
    session: AsyncSession = Depends(get_session),
) -> RepositoryListResponse:
    """List all onboarded repositories."""
    result = await session.execute(
        select(Repository)
        .options(selectinload(Repository.projects))
        .order_by(Repository.created_at.desc())
    )
    repos = result.scalars().all()
    return RepositoryListResponse(
        repositories=[_repo_to_response(r) for r in repos],
        total=len(repos),
    )


@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> RepositoryResponse:
    """Get a single repository by ID."""
    result = await session.execute(
        select(Repository)
        .options(selectinload(Repository.projects))
        .where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found",
        )
    return _repo_to_response(repo)


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a repository and all its projects."""
    result = await session.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found",
        )
    await session.delete(repo)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{repo_id}/clone-status", response_model=CloneStatusResponse)
async def get_clone_status(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> CloneStatusResponse:
    """Get the clone status for a repository."""
    result = await session.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found",
        )
    return CloneStatusResponse(
        clone_status=repo.clone_status,
        clone_error=repo.clone_error,
    )


@router.post("/{repo_id}/sync", response_model=CloneStatusResponse)
async def sync_repository(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> CloneStatusResponse:
    """Pull latest changes for a cloned repository."""
    result = await session.execute(
        select(Repository).where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found",
        )
    if repo.clone_status != "cloned" or not repo.local_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository is not in cloned state",
        )

    try:
        await pull_latest(repo.local_path)
        from datetime import datetime

        repo.last_synced_at = datetime.now(UTC)
        repo.clone_error = None
        await session.commit()
    except Exception as exc:
        repo.clone_error = str(exc)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Sync failed: {exc}",
        ) from exc

    return CloneStatusResponse(
        clone_status=repo.clone_status,
        clone_error=repo.clone_error,
    )


@router.post(
    "/{repo_id}/branches",
    response_model=ProjectBranchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_branch(
    repo_id: str,
    body: BranchAddRequest,
    session: AsyncSession = Depends(get_session),
) -> ProjectBranchResponse:
    """Add a new branch project to an existing repository."""
    result = await session.execute(
        select(Repository)
        .options(selectinload(Repository.projects))
        .where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found",
        )

    # Check if branch already exists
    for p in repo.projects:
        if p.branch == body.branch:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Branch {body.branch} already exists for this repository",
            )

    project = Project(
        name=f"{repo.repo_full_name}:{body.branch}",
        source_path=repo.local_path or "",
        status="created",
        repository_id=repo.id,
        branch=body.branch,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    return ProjectBranchResponse(
        id=project.id,
        branch=project.branch,
        status=project.status,
    )


@router.get("/{repo_id}/projects", response_model=list[ProjectBranchResponse])
async def list_branch_projects(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[ProjectBranchResponse]:
    """List all branch projects for a repository."""
    result = await session.execute(
        select(Repository)
        .options(selectinload(Repository.projects))
        .where(Repository.id == repo_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found",
        )
    return [
        ProjectBranchResponse(
            id=p.id,
            branch=p.branch,
            status=p.status,
        )
        for p in repo.projects
    ]


@router.get("/{repo_id}/evolution", response_model=EvolutionTimelineResponse)
async def get_evolution_timeline(
    repo_id: str,
    branch: str = "main",
    session: AsyncSession = Depends(get_session),
) -> EvolutionTimelineResponse:
    """Get the evolution timeline for a repository branch."""
    # Find project for this repo + branch
    result = await session.execute(
        select(Project).where(
            Project.repository_id == repo_id,
            Project.branch == branch,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No project found for repo {repo_id} branch {branch}",
        )

    # Get completed analysis runs ordered by time
    runs_result = await session.execute(
        select(AnalysisRun)
        .where(
            AnalysisRun.project_id == project.id,
            AnalysisRun.status == "completed",
        )
        .order_by(AnalysisRun.completed_at.asc())
    )
    runs = runs_result.scalars().all()

    snapshots = [
        SnapshotPoint(
            run_id=r.id,
            analyzed_at=r.completed_at or r.started_at,  # type: ignore[arg-type]
            commit_sha=r.commit_sha,
            summary=r.snapshot or {},
        )
        for r in runs
    ]

    return EvolutionTimelineResponse(
        repo_id=repo_id,
        branch=branch,
        snapshots=snapshots,
    )


@router.get("/{repo_id}/compare", response_model=BranchCompareResponse)
async def compare_branches(
    repo_id: str,
    branch_a: str = "main",
    branch_b: str = "develop",
    session: AsyncSession = Depends(get_session),
) -> BranchCompareResponse:
    """Compare two branches of a repository (placeholder for full diff logic)."""
    # Verify both branches exist
    for branch_name in [branch_a, branch_b]:
        result = await session.execute(
            select(Project).where(
                Project.repository_id == repo_id,
                Project.branch == branch_name,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No project found for repo {repo_id} branch {branch_name}",
            )

    # Placeholder: real comparison logic will query Neo4j for graph diffs
    return BranchCompareResponse(
        branch_a=branch_a,
        branch_b=branch_b,
        diff={},
    )
