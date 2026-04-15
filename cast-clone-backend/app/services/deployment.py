"""Deployment singleton — manages the installation_id for license binding."""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.db import Deployment
from app.services.postgres import get_background_session

logger = structlog.get_logger(__name__)


async def init_deployment_id() -> str:
    """Return the deployment's installation_id, creating the row on first call.

    Idempotent: safe across concurrent callers and restarts. The ``singleton``
    column's UNIQUE constraint means at most one row ever exists.
    """
    async with get_background_session() as session:
        result = await session.execute(select(Deployment).limit(1))
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing.id

        # First boot — create the row. UNIQUE on ``singleton`` prevents duplicates
        # if two processes race here; the loser gets an IntegrityError and re-reads.
        deployment = Deployment()
        session.add(deployment)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            result = await session.execute(select(Deployment).limit(1))
            existing = result.scalar_one()
            return existing.id

        await logger.ainfo(
            "deployment.installation_id_created",
            installation_id=deployment.id,
        )
        return deployment.id
