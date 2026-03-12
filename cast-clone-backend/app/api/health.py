from typing import Any

import boto3
import redis.asyncio as redis
from fastapi import APIRouter
from neo4j import AsyncGraphDatabase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, Any]:
    settings = Settings()
    services: dict[str, str] = {}

    # PostgreSQL
    try:
        engine = create_async_engine(settings.database_url)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        services["postgres"] = "up"
    except Exception:
        services["postgres"] = "down"

    # Neo4j
    try:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        await driver.verify_connectivity()
        await driver.close()
        services["neo4j"] = "up"
    except Exception:
        services["neo4j"] = "down"

    # Redis
    try:
        r = redis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        services["redis"] = "up"
    except Exception:
        services["redis"] = "down"

    # MinIO
    try:
        scheme = "https" if settings.minio_secure else "http"
        endpoint_url = f"{scheme}://{settings.minio_endpoint}"
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )
        s3.list_buckets()
        services["minio"] = "up"
    except Exception:
        services["minio"] = "down"

    all_up = all(v == "up" for v in services.values())
    return {
        "status": "healthy" if all_up else "unhealthy",
        "services": services,
    }
