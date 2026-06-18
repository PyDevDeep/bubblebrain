from fastapi import APIRouter, HTTPException, status
from openai import AsyncOpenAI
from pinecone import Pinecone  # type: ignore[reportMissingTypeStubs]

from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)
health_router = APIRouter()


@health_router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, str]:
    """Basic service health check (Liveness probe)."""
    return {"status": "healthy"}


@health_router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check() -> dict[str, str]:
    """Check availability of dependencies: Pinecone and OpenAI (Readiness probe)."""
    settings = get_settings()
    components_status = {"status": "ready", "pinecone": "ok", "openai": "ok"}
    errors: list[str] = []

    # Check OpenAI
    try:
        openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=5.0,
            max_retries=0,
        )
        # Call model listing as lightweight check
        await openai_client.models.list()
    except Exception as e:
        logger.warning("OpenAI readiness check failed", error=str(e))
        components_status["openai"] = "failed"
        errors.append(f"OpenAI: {e!s}")

    # Check Pinecone
    try:
        pinecone_client = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
        # Check service access (listing indices)
        pinecone_client.list_indexes()
    except Exception as e:
        logger.warning("Pinecone readiness check failed", error=str(e))
        components_status["pinecone"] = "failed"
        errors.append(f"Pinecone: {e!s}")

    if errors:
        components_status["status"] = "error"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=components_status,
        )

    return components_status
