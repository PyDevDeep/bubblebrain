from functools import lru_cache

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.services.cache_service import CacheService
from app.services.category_manager import CategoryManager
from app.services.chat_memory_service import ChatMemoryService
from app.services.guardrails_service import GuardrailsService
from app.services.lead_service import LeadService
from app.services.openai_service import OpenAIService
from app.services.price_comparator import PriceComparator
from app.services.rag_engine import RAGEngine
from app.services.scraper_service import ScraperService
from app.services.telegram_service import TelegramService
from app.services.vector_service import VectorService
from app.services.woo_service import WooService


@lru_cache(maxsize=1)
def get_openai_service() -> OpenAIService:
    """Provide a singleton instance of OpenAIService."""
    return OpenAIService(get_settings())


@lru_cache(maxsize=1)
def get_vector_service() -> VectorService:
    """Provide a singleton instance of VectorService."""
    return VectorService(get_settings())


@lru_cache(maxsize=1)
def get_woo_service() -> WooService:
    """Provide a singleton instance of WooService."""
    return WooService(get_settings())


@lru_cache(maxsize=1)
def get_scraper_service() -> ScraperService:
    """Provide a singleton instance of ScraperService."""
    return ScraperService(get_settings())


@lru_cache(maxsize=1)
def get_cache_service() -> CacheService:
    """Provide a singleton instance of CacheService."""
    return CacheService(get_settings())


@lru_cache(maxsize=1)
def get_telegram_service() -> TelegramService:
    """Provide a singleton instance of TelegramService."""
    return TelegramService(get_settings())


@lru_cache(maxsize=1)
def get_category_manager() -> CategoryManager:
    """Provide a singleton instance of CategoryManager."""
    return CategoryManager()


@lru_cache(maxsize=1)
def get_guardrails_service() -> GuardrailsService:
    """Provide a singleton instance of GuardrailsService."""
    return GuardrailsService()


@lru_cache(maxsize=1)
def get_chat_memory_service() -> ChatMemoryService:
    """Provide a singleton instance of ChatMemoryService."""
    return ChatMemoryService()


def get_lead_service(
    telegram_service: TelegramService = Depends(get_telegram_service),
    chat_memory_service: ChatMemoryService = Depends(get_chat_memory_service),
) -> LeadService:
    """Provide a LeadService instance."""
    return LeadService(telegram_service, chat_memory_service)


def get_price_comparator(
    woo_service: WooService = Depends(get_woo_service),
    scraper_service: ScraperService = Depends(get_scraper_service),
    cache_service: CacheService = Depends(get_cache_service),
    settings: Settings = Depends(get_settings),
) -> PriceComparator:
    """Provide a PriceComparator instance constructed from its dependencies."""
    return PriceComparator(woo_service, scraper_service, cache_service, settings)


def get_rag_engine(
    openai_service: OpenAIService = Depends(get_openai_service),
    vector_service: VectorService = Depends(get_vector_service),
    price_comparator: PriceComparator = Depends(get_price_comparator),
    telegram_service: TelegramService = Depends(get_telegram_service),
    category_manager: CategoryManager = Depends(get_category_manager),
    guardrails_service: GuardrailsService = Depends(get_guardrails_service),
    chat_memory_service: ChatMemoryService = Depends(get_chat_memory_service),
    settings: Settings = Depends(get_settings),
) -> RAGEngine:
    """Dependency injection for RAGEngine."""
    return RAGEngine(
        openai_service=openai_service,
        vector_service=vector_service,
        price_comparator=price_comparator,
        telegram_service=telegram_service,
        category_manager=category_manager,
        guardrails_service=guardrails_service,
        chat_memory_service=chat_memory_service,
        settings=settings,
    )
