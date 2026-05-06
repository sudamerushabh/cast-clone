"""Idempotent database initialization for container startup.

Runs before uvicorn so the FastAPI app starts against a ready schema.

Two paths:
  * Fresh DB (no alembic_version table) → create schema via Base.metadata.create_all,
    then `alembic stamp head` to mark current state as latest without replaying any
    migrations against the just-created schema (which would error: "relation already
    exists" / "column already exists").
  * Existing DB → run `alembic upgrade head` to apply any pending migrations.

Run as: `python -m app.db_init`
"""

from __future__ import annotations

import asyncio
import logging
import sys

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models.db import Base

logger = logging.getLogger(__name__)


async def _is_alembic_initialized(database_url: str) -> bool:
    engine = create_async_engine(database_url, echo=False)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(sa.text("SELECT to_regclass('alembic_version')"))
            return result.scalar() is not None
    finally:
        await engine.dispose()


async def _bootstrap_schema(database_url: str) -> None:
    engine = create_async_engine(database_url, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    cfg = Config("alembic.ini")
    return cfg


async def main() -> None:
    settings = get_settings()
    database_url = settings.database_url

    if await _is_alembic_initialized(database_url):
        logger.info("alembic_version table present — applying any pending migrations")
        command.upgrade(_alembic_config(), "head")
        logger.info("alembic upgrade head: complete")
        return

    logger.info("alembic_version table missing — bootstrapping schema from Base.metadata")
    await _bootstrap_schema(database_url)
    logger.info("schema created from Base.metadata; stamping alembic to head")
    command.stamp(_alembic_config(), "head")
    logger.info("alembic stamp head: complete")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(main())
