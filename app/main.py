import contextlib
import os
from collections.abc import AsyncGenerator
from pathlib import Path

import sentry_sdk
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[reportMissingTypeStubs]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[reportMissingTypeStubs]
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sentry_sdk.integrations.fastapi import FastApiIntegration
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.logging_config import get_logger, setup_logging
from app.middleware.rate_limiter import limiter
from app.middleware.request_logging import RequestLoggingMiddleware
from scripts.export_categories import export_categories_to_csv

logger = get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Lifespan events for FastAPI application."""
    # on_startup
    from app.core.db import init_db

    await init_db()

    settings = get_settings()
    setup_logging(settings.log_level)

    # --- ADDED FOR CACHE FIX ---
    from app.api.dependencies import get_cache_service

    cache_service = get_cache_service()
    await cache_service.initialize()

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
            integrations=[FastApiIntegration()],
        )
        logger.info("Sentry initialized")

    logger.info("Application started", env=settings.pinecone_environment)

    from app.api.dependencies import get_vector_service

    vector_service = get_vector_service()
    await vector_service.initialize()

    # TECHNICAL DEBT:
    # Current implementation of cron jobs runs in memory (APScheduler) and is LIMITED to 1 worker (--workers 1).
    # With increased traffic and number of workers (e.g., --workers 4), the scheduler will run 4 times.
    # To move past MVP we need to:
    # Path A: Move APScheduler to an isolated Docker container (separate process).
    # Path B: Use distributed locking (Redis Lock or APScheduler RedisJobStore).
    from apscheduler.jobstores.sqlalchemy import (  # type: ignore[reportMissingTypeStubs]
        SQLAlchemyJobStore,
    )

    from app.services.statistics_service import gather_and_send_daily_report_job

    jobstores = {"default": SQLAlchemyJobStore(url="sqlite:///digitaldreams.db")}
    scheduler = AsyncIOScheduler(jobstores=jobstores)  # type: ignore
    scheduler.add_job(  # type: ignore[reportUnknownMemberType]
        export_categories_to_csv,
        trigger=CronTrigger(hour=3, minute=0, timezone="Europe/Kyiv"),
        id="export_woo_categories",
        name="Export WooCommerce categories to CSV",
        replace_existing=True,
    )

    # Add job for daily statistics at 09:00 (Kyiv time)
    scheduler.add_job(  # type: ignore[reportUnknownMemberType]
        gather_and_send_daily_report_job,
        trigger=CronTrigger(hour=9, minute=0, timezone="Europe/Kyiv"),
        id="daily_bot_statistics",
        name="Send Daily Bot Statistics to TG",
        replace_existing=True,
    )

    if os.getenv("RUN_CRON", "false").lower() == "true":
        scheduler.start()  # type: ignore
        logger.info("APScheduler started: jobs scheduled")
    else:
        logger.info("APScheduler not started: RUN_CRON is not 'true'")

    yield

    # on_shutdown
    logger.info("Application shutting down")
    scheduler.shutdown(wait=False)  # type: ignore

    # Close HTTP clients
    from app.api.dependencies import get_scraper_service

    scraper_service = get_scraper_service()
    await scraper_service.close()

    from app.api.dependencies import get_woo_service

    woo_service = get_woo_service()
    await woo_service.close()

    if settings.sentry_dsn:
        sentry_sdk.flush()


def create_application() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title="Chatbot AI Backend",
        version="0.1.0",
        description="""
Backend for Chat Embed with RAG.

## Authentication
All API requests to `/api/v1/*` endpoints require a Bearer token in the `Authorization` header.
Example: `Authorization: Bearer YOUR_API_KEY`

## Rate Limiting
Endpoints are protected by rate limiting.
For chat endpoints, the limit is **20 requests per minute** per IP.
""",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(api_v1_router, prefix="/api/v1")

    # Rate Limiter configuration
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore

    # ABSOLUTE PATH FOR STATIC FILES
    base_dir = Path(__file__).resolve().parent.parent
    frontend_dir = base_dir / "frontend"

    # DIAGNOSTIC ENDPOINT: Allows checking if files are actually mounted in the container
    @app.get("/debug-fs")
    def debug_fs() -> dict[str, str | bool | list[str]]:
        """Diagnostic endpoint to check if static files are mounted."""
        import os

        files_list: list[str] = os.listdir(str(frontend_dir)) if frontend_dir.exists() else []
        return {
            "path": str(frontend_dir),
            "exists": frontend_dir.exists(),
            "files": files_list,
        }

    _ = debug_fs  # Masking for Pylance (prevents unused code error)

    app.mount("/widget", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    # Prometheus metrics
    from prometheus_client import make_asgi_app  # type: ignore[import-untyped]

    metrics_app = make_asgi_app()  # type: ignore
    app.mount("/metrics", metrics_app)  # type: ignore

    return app


app = create_application()
