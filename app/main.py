import contextlib
from collections.abc import AsyncGenerator

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.logging_config import get_logger, setup_logging
from app.middleware.request_logging import RequestLoggingMiddleware
from app.services.vector_service import VectorService

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
    VectorService(settings)
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
        root_path=settings.root_path,  # ДОДАНО
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

    return app


app = create_application()
