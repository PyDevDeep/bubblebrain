import contextlib
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
    # on_startup
    from app.core.db import init_db

    await init_db()

    settings = get_settings()
    setup_logging(settings.log_level)

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
            integrations=[FastApiIntegration()],
        )
        logger.info("Sentry initialized")

    logger.info("Application started", env=settings.pinecone_environment)

    # ТЕХНІЧНИЙ БОРГ (TECH DEBT):
    # Поточна реалізація крон-задач працює в пам'яті (APScheduler) і ОБМЕЖЕНА 1 воркером (--workers 1).
    # При збільшенні трафіку і кількості воркерів (наприклад, --workers 4), scheduler запуститься 4 рази.
    # Для виходу з MVP необхідно:
    # Шлях А: Винести APScheduler в ізольований Docker-контейнер (окремий процес).
    # Шлях Б: Використати розподілене блокування (Redis Lock або APScheduler RedisJobStore).
    scheduler = AsyncIOScheduler()  # type: ignore
    scheduler.add_job(  # type: ignore[reportUnknownMemberType]
        export_categories_to_csv,
        trigger=CronTrigger(hour=3, minute=0),
        id="export_woo_categories",
        name="Export WooCommerce categories to CSV",
        replace_existing=True,
    )
    scheduler.start()  # type: ignore
    logger.info("APScheduler started: category export scheduled at 03:00")

    yield

    # on_shutdown
    logger.info("Application shutting down")
    scheduler.shutdown(wait=False)  # type: ignore
    if settings.sentry_dsn:
        sentry_sdk.flush()


def create_application() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Chatbot AI Backend",
        version="0.1.0",
        description="Backend for Flowise Chat Embed with RAG",
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

    # Конфігурація Rate Limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore

    # АБСОЛЮТНИЙ ШЛЯХ ДЛЯ СТАТИКИ
    base_dir = Path(__file__).resolve().parent.parent
    frontend_dir = base_dir / "frontend"

    # ДІАГНОСТИЧНИЙ ЕНДПОІНТ: Дозволяє побачити, чи дійсно файли змонтовані в контейнер
    @app.get("/debug-fs")
    def debug_fs() -> dict[str, str | bool | list[str]]:
        import os

        files_list: list[str] = os.listdir(str(frontend_dir)) if frontend_dir.exists() else []
        return {
            "path": str(frontend_dir),
            "exists": frontend_dir.exists(),
            "files": files_list,
        }

    _ = debug_fs  # Маскування для Pylance (запобігає помилці неактивного коду)

    app.mount("/widget", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_application()
