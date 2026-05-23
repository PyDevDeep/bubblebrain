import time
from collections.abc import AsyncGenerator

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.schemas.chat import RAGResponse
from app.services.openai_service import OpenAIService
from app.services.vector_service import VectorService
from app.utils.prompts import NO_CONTEXT_RESPONSE, RAG_SYSTEM_PROMPT

logger = get_logger(__name__)


class RAGEngine:
    def __init__(
        self,
        openai_service: OpenAIService,
        vector_service: VectorService,
        settings: Settings,
    ) -> None:
        """Dependency injection для інтеграції сервісів RAG пайплайну."""
        self.openai_service = openai_service
        self.vector_service = vector_service
        self.settings = settings
        self.top_k = settings.top_k_results
        self.threshold = settings.similarity_threshold

    async def _retrieve_context(
        self, question: str
    ) -> tuple[list[str], list[str], dict[str, float]]:
        """Внутрішній метод: генерація embedding та пошук релевантних чанків."""
        timings: dict[str, float] = {}

        # 1. Генерація query вектора
        start_embed = time.perf_counter()
        query_vector = await self.openai_service.generate_embedding(question)
        timings["embedding_ms"] = round((time.perf_counter() - start_embed) * 1000, 2)

        # 2. Пошук у Pinecone
        start_retrieve = time.perf_counter()
        results = self.vector_service.query_similar(
            query_vector=query_vector,
            top_k=self.top_k,
            score_threshold=self.threshold,
        )
        timings["retrieval_ms"] = round((time.perf_counter() - start_retrieve) * 1000, 2)

        context_chunks: list[str] = []
        sources: list[str] = []

        for match in results:
            metadata = match.get("metadata", {})
            if "text" in metadata:
                context_chunks.append(metadata["text"])
            if "source" in metadata and metadata["source"] not in sources:
                sources.append(metadata["source"])

        return context_chunks, sources, timings

    async def process_query(self, question: str) -> RAGResponse:
        """Повний цикл RAG: повертає фінальну відповідь та джерела."""
        start_total = time.perf_counter()

        context_chunks, sources, timings = await self._retrieve_context(question)

        # 3. Перевірка наявності релевантного контексту
        if not context_chunks:
            logger.info("RAG Engine fallback: no context", threshold=self.threshold)
            timings["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)
            return RAGResponse(
                answer=NO_CONTEXT_RESPONSE,
                sources=[],
                has_context=False,
            )

        # 4 & 5. Виклик LLM з контекстом
        start_gen = time.perf_counter()
        answer = await self.openai_service.get_chat_completion(
            system_prompt=RAG_SYSTEM_PROMPT,
            user_message=question,
            context_chunks=context_chunks,
        )
        timings["generation_ms"] = round((time.perf_counter() - start_gen) * 1000, 2)
        timings["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)

        logger.info("RAG sync query processed", timings=timings, sources_count=len(sources))

        return RAGResponse(
            answer=answer,
            sources=sources,
            has_context=True,
        )

    async def process_query_stream(self, question: str) -> AsyncGenerator[str]:
        """Streaming-версія RAG pipeline для SSE-відповідей."""
        context_chunks, sources, _ = await self._retrieve_context(question)

        if not context_chunks:
            logger.info("RAG Engine stream fallback: no context", threshold=self.threshold)
            yield NO_CONTEXT_RESPONSE
            return

        logger.info("RAG stream query started", sources_count=len(sources))

        stream = self.openai_service.stream_chat_completion(
            system_prompt=RAG_SYSTEM_PROMPT,
            user_message=question,
            context_chunks=context_chunks,
        )

        async for token in stream:
            yield token
