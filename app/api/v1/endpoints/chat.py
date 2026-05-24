import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.config import Settings, get_settings
from app.core.logging_config import get_logger
from app.core.security import verify_api_key
from app.middleware.rate_limiter import limiter
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.openai_service import OpenAIService
from app.services.rag_engine import RAGEngine
from app.services.vector_service import VectorService

logger = get_logger(__name__)
chat_router = APIRouter()


def get_rag_engine(settings: Settings = Depends(get_settings)) -> RAGEngine:
    openai_service = OpenAIService(settings)
    vector_service = VectorService(settings)
    return RAGEngine(
        openai_service=openai_service,
        vector_service=vector_service,
        settings=settings,
    )


@chat_router.post("", response_model=ChatResponse)
@limiter.limit("20/minute")  # type: ignore
async def chat_completion(
    request: Request,
    chat_request: ChatRequest,
    api_key: str = Depends(verify_api_key),
    rag_engine: RAGEngine = Depends(get_rag_engine),
) -> ChatResponse:
    """
    Синхронний ендпоінт чату. Запускає RAG pipeline та повертає повну відповідь.
    """
    logger.info("Sync chat request received", session_id=chat_request.session_id)

    rag_response = await rag_engine.process_query(chat_request.question)
    session_id = chat_request.session_id or str(uuid.uuid4())

    return ChatResponse(
        answer=rag_response.answer,
        sources=rag_response.sources,
        has_context=rag_response.has_context,
        session_id=session_id,
    )


@chat_router.post("/stream")
@limiter.limit("20/minute")  # type: ignore
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    api_key: str = Depends(verify_api_key),
    rag_engine: RAGEngine = Depends(get_rag_engine),
) -> StreamingResponse:
    """
    Streaming (SSE) ендпоінт чату. Повертає токени по мірі їх генерації моделлю.
    """
    logger.info("Stream chat request received", session_id=chat_request.session_id)

    async def event_generator() -> AsyncGenerator[str]:
        try:
            async for token in rag_engine.process_query_stream(chat_request.question):
                # Формат SSE згідно з вимогами Flowise/Roadmap
                yield f"data: {token}\n\n"
        except Exception as e:
            logger.error("Error during streaming", error=str(e))
            yield f"data: [ERROR] {e!s}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
