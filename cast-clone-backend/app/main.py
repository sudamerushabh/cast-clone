from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.config import Settings
from app.services.neo4j import close_neo4j, init_neo4j
from app.services.postgres import close_postgres, init_postgres
from app.services.redis import close_redis, init_redis

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
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

    application.include_router(health_router)

    return application


app = create_app()
