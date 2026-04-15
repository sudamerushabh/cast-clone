import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    activity_router,
    ai_usage_router,
    analysis_router,
    analysis_views_router,
    annotations_project_router,
    annotations_router,
    api_keys_router,
    auth_router,
    chat_router,
    connectors_router,
    email_router,
    export_router,
    git_config_router,
    graph_router,
    graph_views_router,
    health_router,
    license_router,
    projects_router,
    pull_requests_router,
    repositories_router,
    summary_router,
    tags_project_router,
    tags_router,
    users_router,
    views_project_router,
    views_router,
    webhooks_router,
    websocket_router,
)
from app.config import Settings
from app.services.deployment import init_deployment_id
from app.services.license import LicenseState, get_license_state, load_license
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


async def _cleanup_stale_analyses() -> None:
    """Mark any analyses stuck in running/pending state as failed.

    This handles the case where the server was restarted (or crashed) while
    an analysis was in progress.  Without this, the project stays in
    'analyzing' state forever and can never be re-triggered.
    """
    from sqlalchemy import text

    from app.services.postgres import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE analysis_runs SET status='failed', "
                "error_message='Server restarted during analysis', "
                "completed_at=NOW() "
                "WHERE status IN ('running', 'pending') "
                "RETURNING id"
            )
        )
        stale_runs = result.fetchall()

        result2 = await conn.execute(
            text(
                "UPDATE projects SET status='failed' "
                "WHERE status='analyzing' "
                "RETURNING id"
            )
        )
        stale_projects = result2.fetchall()

    if stale_runs or stale_projects:
        await logger.awarning(
            "startup.cleanup_stale_analyses",
            stale_runs=len(stale_runs),
            stale_projects=len(stale_projects),
        )


async def _license_state_refresher(app: FastAPI) -> None:
    """Every 5 minutes, re-evaluate license state (picks up expiry transitions)."""
    while True:
        try:
            await asyncio.sleep(300)
            new_state = await get_license_state()
            old_state = app.state.license_state
            if new_state != old_state:
                app.state.license_state = new_state
                await logger.ainfo(
                    "license.state_changed",
                    from_state=old_state.value,
                    to_state=new_state.value,
                )
                from app.services.license import (
                    _notify_state_change,
                    get_current_license,
                )
                lic = get_current_license()
                await _notify_state_change(old_state, new_state, lic)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            await logger.aerror("license.state_refresher_failed", error=str(exc))


async def _run_scheduled_report_tick() -> None:
    """Wrapper for email scheduled report tick with error handling."""
    try:
        from app.services.email import scheduled_report_tick

        await scheduled_report_tick()
    except Exception:
        await logger.aexception("scheduler.scheduled_report_tick_failed")


async def _run_expiry_reminder_tick() -> None:
    """Wrapper for email expiry reminder tick with error handling."""
    try:
        from app.services.email import expiry_reminder_tick

        await expiry_reminder_tick()
    except Exception:
        await logger.aexception("scheduler.expiry_reminder_tick_failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    _configure_logging(settings.log_level)
    # Startup
    await init_postgres(settings)
    installation_id = await init_deployment_id()
    app.state.installation_id = installation_id

    # License loading — after installation_id is known
    refresher_task: asyncio.Task[None] | None = None
    if settings.license_disabled:
        app.state.license_info = None
        app.state.license_state = LicenseState.LICENSED_HEALTHY
        await logger.awarning(
            "license.disabled_via_settings",
            note="LICENSE_DISABLED=true — license checks are bypassed",
        )
    else:
        license_info, license_state = await load_license(settings, installation_id)
        app.state.license_info = license_info
        app.state.license_state = license_state
        refresher_task = asyncio.create_task(_license_state_refresher(app))

        # Register email service as listener for license state transitions
        from app.services.email import on_license_state_change
        from app.services.license import register_state_change_listener
        register_state_change_listener(on_license_state_change)

    await init_neo4j(settings)
    await init_redis(settings)

    # Clean up any analyses left in "running" state from a previous crash/restart
    await _cleanup_stale_analyses()

    # APScheduler — email report + expiry reminder jobs
    scheduler = AsyncIOScheduler()

    # Hourly tick: check if now matches configured cadence for scheduled reports
    scheduler.add_job(
        _run_scheduled_report_tick,
        "cron",
        minute=0,  # top of every hour
        id="email_scheduled_report",
        replace_existing=True,
    )

    # Daily tick at 08:00 UTC: check for expiry reminders
    scheduler.add_job(
        _run_expiry_reminder_tick,
        "cron",
        hour=8,
        minute=0,
        id="email_expiry_reminder",
        replace_existing=True,
    )

    scheduler.start()
    await logger.ainfo(
        "scheduler.started",
        jobs=["email_scheduled_report", "email_expiry_reminder"],
    )

    await logger.ainfo("All services initialized")
    yield
    # Shutdown
    scheduler.shutdown(wait=False)
    await logger.ainfo("scheduler.stopped")
    if refresher_task is not None:
        refresher_task.cancel()
        try:
            await refresher_task
        except asyncio.CancelledError:
            pass
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
    application.include_router(activity_router)
    application.include_router(annotations_project_router)
    application.include_router(annotations_router)
    application.include_router(auth_router)
    application.include_router(health_router)
    application.include_router(license_router)
    application.include_router(projects_router)
    application.include_router(analysis_router)
    application.include_router(graph_router)
    application.include_router(connectors_router)
    application.include_router(export_router)
    application.include_router(repositories_router)
    application.include_router(graph_views_router)
    application.include_router(analysis_views_router)
    application.include_router(tags_project_router)
    application.include_router(tags_router)
    application.include_router(users_router)
    application.include_router(views_project_router)
    application.include_router(views_router)
    application.include_router(pull_requests_router)
    application.include_router(webhooks_router)
    application.include_router(git_config_router)
    application.include_router(websocket_router)
    application.include_router(chat_router)
    application.include_router(summary_router)
    application.include_router(api_keys_router)
    application.include_router(ai_usage_router)
    application.include_router(email_router)

    return application


app = create_app()
