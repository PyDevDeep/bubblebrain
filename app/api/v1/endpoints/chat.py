import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.config import Settings, get_settings
from app.core.logging_config import get_logger
from app.core.security import verify_api_key
from app.middleware.rate_limiter import limiter
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.cache_service import CacheService
from app.services.category_manager import CategoryManager
from app.services.guardrails_service import GuardrailsService
from app.services.openai_service import OpenAIService
from app.services.price_comparator import PriceComparator
from app.services.rag_engine import RAGEngine
from app.services.scraper_service import ScraperService
from app.services.telegram_service import TelegramService
from app.services.vector_service import VectorService
from app.services.woo_service import WooService

logger = get_logger(__name__)
chat_router = APIRouter()


def get_rag_engine(settings: Settings = Depends(get_settings)) -> RAGEngine:
    openai_service = OpenAIService(settings)
    vector_service = VectorService(settings)

    woo_service = WooService(settings)
    scraper_service = ScraperService(settings)
    cache_service = CacheService(settings)

    price_comparator = PriceComparator(woo_service, scraper_service, cache_service, settings)
    telegram_service = TelegramService(settings)
    category_manager = CategoryManager()
    guardrails_service = GuardrailsService()

    return RAGEngine(
        openai_service=openai_service,
        vector_service=vector_service,
        price_comparator=price_comparator,
        telegram_service=telegram_service,
        category_manager=category_manager,
        guardrails_service=guardrails_service,
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
    client_ip = request.client.host if request.client else None
    logger.info(
        "Sync chat request received", session_id=chat_request.session_id, client_ip=client_ip
    )
    session_id = chat_request.session_id or str(uuid.uuid4())

    try:
        rag_response = await rag_engine.process_query(
            chat_request.question, session_id=session_id, client_ip=client_ip
        )
        return ChatResponse(
            answer=rag_response.answer,
            sources=rag_response.sources,
            has_context=rag_response.has_context,
            session_id=session_id,
        )
    except Exception as e:
        logger.error("Critical error in sync chat pipeline", error=str(e), exc_info=True)
        # Fallback відповідь замість 500 помилки
        return ChatResponse(
            answer="Вибачте, виникла технічна затримка при обробці запиту. Спробуйте переформулювати питання або зверніться до нашого менеджера напряму.",
            sources=[],
            has_context=False,
            session_id=session_id,
        )


@chat_router.post("/stream")
@limiter.limit("20/minute")  # type: ignore[reportUntypedFunctionDecorator, reportUnknownMemberType]
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    api_key: str = Depends(verify_api_key),
    rag_engine: RAGEngine = Depends(get_rag_engine),
) -> StreamingResponse:
    """
    Streaming (SSE) ендпоінт чату. Повертає токени по мірі їх генерації моделлю.
    """
    client_ip = request.client.host if request.client else None
    session_id = chat_request.session_id or str(uuid.uuid4())
    logger.info("Stream chat request received", session_id=session_id, client_ip=client_ip)

    async def event_generator() -> AsyncGenerator[str]:
        try:
            async for token in rag_engine.process_query_stream(
                chat_request.question, session_id=session_id, client_ip=client_ip
            ):
                yield f"data: {token}\n\n"
        except Exception as e:
            logger.error("Critical error during streaming", error=str(e), exc_info=True)
            fallback_msg = "Технічна затримка на лінії. Оновіть сторінку або напишіть нам пізніше."
            yield f"data: {fallback_msg}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )
