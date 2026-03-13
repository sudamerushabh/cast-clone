"""Branch project management — ensures branch projects exist and are ready for analysis."""
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Project, Repository
from app.services.clone import (
    clone_branch_local,
    get_branch_clone_path,
    get_current_commit,
    pull_latest,
)

logger = structlog.get_logger(__name__)


class BranchManager:
    """Ensures branch projects exist with their own clone directories."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_branch_project(
        self, repo: Repository, branch: str
    ) -> Project:
        """Ensure a Project record and clone directory exist for a branch.

        If the project already exists, pulls latest code.
        If it doesn't exist, creates the project and clones the branch.

        Returns the Project record.
        """
        # Check for existing project
        result = await self._session.execute(
            select(Project).where(
                Project.repository_id == repo.id,
                Project.branch == branch,
            )
        )
        project = result.scalar_one_or_none()

        branch_dir = get_branch_clone_path(repo.local_path, branch)

        if project is not None:
            # Project exists — pull latest
            try:
                await pull_latest(branch_dir)
                logger.info("branch_pulled", branch=branch, path=branch_dir)
            except Exception as exc:
                logger.warning(
                    "branch_pull_failed", branch=branch, error=str(exc)
                )
            return project

        # Create new project + clone
        await clone_branch_local(repo.local_path, branch, branch_dir)

        project = Project(
            name=f"{repo.repo_full_name}:{branch}",
            source_path=branch_dir,
            status="created",
            repository_id=repo.id,
            branch=branch,
        )
        self._session.add(project)
        await self._session.flush()
        await self._session.refresh(project)

        logger.info(
            "branch_project_created",
            project_id=project.id,
            branch=branch,
            path=branch_dir,
        )
        return project

    async def needs_analysis(self, project: Project) -> bool:
        """Check if a project needs (re-)analysis.

        Returns True if:
        - Never analyzed (status != "analyzed")
        - Branch has new commits since last analysis
        """
        if project.status != "analyzed" or project.last_analyzed_commit is None:
            return True

        current_commit = await get_current_commit(project.source_path)
        if current_commit != project.last_analyzed_commit:
            return True

        return False
