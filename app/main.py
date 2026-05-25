import contextlib
from collections.abc import AsyncGenerator
from pathlib import Path

import sentry_sdk
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

logger = get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # on_startup
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

    yield

    # on_shutdown
    logger.info("Application shutting down")
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
