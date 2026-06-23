import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_openai_service, get_vector_service
from app.core.logging_config import get_logger
from app.services.openai_service import OpenAIService
from app.services.vector_service import VectorService

logger = get_logger(__name__)
health_router = APIRouter()


@health_router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, str]:
    """Basic service health check (Liveness probe)."""
    return {"status": "healthy"}


@health_router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check(
    openai_service: OpenAIService = Depends(get_openai_service),
    vector_service: VectorService = Depends(get_vector_service),
) -> dict[str, str]:
    """Check availability of dependencies: Pinecone and OpenAI (Readiness probe)."""
    components_status = {"status": "ready", "pinecone": "ok", "openai": "ok"}
    errors: list[str] = []

    # Check OpenAI
    try:
        # Call model listing as lightweight check
        await openai_service.client.models.list()
    except Exception as e:
        logger.warning("OpenAI readiness check failed", error=str(e))
        components_status["openai"] = "failed"
        errors.append(f"OpenAI: {e!s}")

    # Check Pinecone
    try:
        # Check service access (listing indices)
        await asyncio.to_thread(vector_service.pc.list_indexes)
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
