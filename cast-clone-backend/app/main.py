import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analysis_router,
    connectors_router,
    graph_router,
    graph_views_router,
    health_router,
    projects_router,
    repositories_router,
    websocket_router,
)
from app.config import Settings
from app.services.neo4j import close_neo4j, init_neo4j
from app.services.postgres import close_postgres, init_postgres
from app.services.redis import close_redis, init_redis


def _configure_logging(log_level: str) -> None:
    """Configure structlog with JSON output for production."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
    )


logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    _configure_logging(settings.log_level)
    # Startup
    await init_postgres(settings)
    await init_neo4j(settings)
    await init_redis(settings)
    await logger.ainfo("All services initialized")
    yield
    # Shutdown
    await close_redis()
    await close_neo4j()
    await close_postgres()
    await logger.ainfo("All services shut down")


def create_app() -> FastAPI:
    settings = Settings()

    application = FastAPI(
        title="CodeLens Backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    application.include_router(health_router)
    application.include_router(projects_router)
    application.include_router(analysis_router)
    application.include_router(graph_router)
    application.include_router(connectors_router)
    application.include_router(repositories_router)
    application.include_router(graph_views_router)
    application.include_router(websocket_router)

    return application


app = create_app()
