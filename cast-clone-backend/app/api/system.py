"""System information endpoint — health, config, and instance metadata."""

import os
import platform
from typing import Any

import boto3
import redis.asyncio as redis
from fastapi import APIRouter
from neo4j import AsyncGraphDatabase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.services.deployment import init_deployment_id

router = APIRouter(prefix="/api/v1/system", tags=["system"])


async def _check_services(settings: Settings) -> dict[str, str]:
    """Probe each infrastructure service and return status."""
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

    return services


@router.get("/info")
async def system_info() -> dict[str, Any]:
    """Return system health, instance metadata, and analysis configuration."""
    settings = Settings()
    services = await _check_services(settings)
    all_up = all(v == "up" for v in services.values())

    deployment_id = await init_deployment_id()

    return {
        "health": {
            "status": "healthy" if all_up else "degraded",
            "services": services,
        },
        "instance": {
            "installation_id": str(deployment_id) if deployment_id else None,
            "auth_disabled": settings.auth_disabled,
            "license_disabled": settings.license_disabled,
            "python_version": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}",
            "cpu_count": os.cpu_count(),
        },
        "analysis": {
            "total_timeout_seconds": settings.total_analysis_timeout,
            "scip_timeout_seconds": settings.scip_timeout,
            "git_clone_timeout_seconds": settings.git_clone_timeout,
            "max_traversal_depth": settings.max_traversal_depth,
            "treesitter_workers": settings.treesitter_workers or os.cpu_count(),
            "repo_storage_path": settings.repo_storage_path,
        },
        "ai": {
            "pr_analysis_model": settings.pr_analysis_model,
            "chat_model": settings.chat_model,
            "chat_timeout_seconds": settings.chat_timeout_seconds,
            "chat_max_response_tokens": settings.chat_max_response_tokens,
            "mcp_port": settings.mcp_port,
        },
        "connections": {
            "neo4j_uri": settings.neo4j_uri,
            "redis_url": _mask_url(settings.redis_url),
            "minio_endpoint": settings.minio_endpoint,
            "database_host": _extract_host(settings.database_url),
        },
    }


def _mask_url(url: str) -> str:
    """Mask password in a connection URL."""
    # redis://user:pass@host:port -> redis://***@host:port
    if "@" in url:
        scheme_rest = url.split("://", 1)
        if len(scheme_rest) == 2:
            after_scheme = scheme_rest[1]
            at_idx = after_scheme.index("@")
            return f"{scheme_rest[0]}://***@{after_scheme[at_idx + 1:]}"
    return url


def _extract_host(db_url: str) -> str:
    """Extract host:port from a database URL, hiding credentials."""
    try:
        after_scheme = db_url.split("://", 1)[1]
        at_idx = after_scheme.index("@")
        host_part = after_scheme[at_idx + 1:]
        # Remove database name
        return host_part.split("/")[0]
    except (IndexError, ValueError):
        return "unknown"
