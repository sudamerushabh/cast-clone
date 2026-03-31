"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.models.db import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_postgres(settings: Settings) -> None:
    """Create engine and ensure tables exist. Called during app lifespan startup."""
    global _engine, _session_factory
    _engine = create_async_engine(settings.database_url, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_postgres() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    """Return the current async engine. Must be called after init_postgres."""
    assert _engine is not None, "PostgreSQL not initialized"
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an async session."""
    assert _session_factory is not None, "PostgreSQL not initialized"
    async with _session_factory() as session:
        yield session


@contextlib.asynccontextmanager
async def get_background_session() -> AsyncIterator[AsyncSession]:
    """Get a session outside of FastAPI's Depends (for background tasks)."""
    assert _session_factory is not None, "PostgreSQL not initialized"
    async with _session_factory() as session:
        yield session
