import json
import time
from collections.abc import AsyncGenerator

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.schemas.chat import RAGResponse
from app.services.openai_service import OpenAIService
from app.services.price_comparator import PriceComparator
from app.services.telegram_service import TelegramService
from app.services.vector_service import VectorService
from app.utils.prompts import NO_CONTEXT_RESPONSE, RAG_SYSTEM_PROMPT

logger = get_logger(__name__)

_chat_memory: dict[str, list[dict[str, str]]] = {}


class RAGEngine:
    def __init__(
        self,
        openai_service: OpenAIService,
        vector_service: VectorService,
        price_comparator: PriceComparator,
        telegram_service: TelegramService,
        settings: Settings,
    ) -> None:
        self.openai_service = openai_service
        self.vector_service = vector_service
        self.price_comparator = price_comparator
        self.telegram_service = telegram_service
        self.settings = settings
        self.top_k = settings.top_k_results
        self.threshold = settings.similarity_threshold

    async def detect_intent(self, question: str, history_context: str) -> dict[str, str]:
        """Визначає, чи потрібен скрапер для запиту, враховуючи історію."""
        prompt = f"""Ти — аналізатор намірів клієнта магазину техніки.
        Історія останніх повідомлень:
        {history_context if history_context else "Немає"}

        Поточний запит: "{question}"
        Зважаючи на історію, якщо користувач запитує про конкретний товар (ціна, наявність, характеристики) АБО продовжує про нього говорити (наприклад, "а коли він буде?", "яка його ціна?"), поверни JSON: {{"intent": "product", "product_name": "Точна назва товару для пошуку"}}.
        Інакше поверни: {{"intent": "faq"}}.
        Відповідай ЛИШЕ валідним JSON, без жодного іншого тексту."""

        try:
            response = await self.openai_service.get_chat_completion(
                system_prompt="Ти - системний аналізатор JSON.",
                user_message=prompt,
                context_chunks=[],
            )
            cleaned = response.replace("```json", "").replace("```", "").strip()
            return dict(json.loads(cleaned))
        except Exception as e:
            logger.error("Intent detection failed", error=str(e))
            return {"intent": "faq"}

    async def _retrieve_context(
        self, search_query: str
    ) -> tuple[list[str], list[str], dict[str, float]]:
        # Генерація query вектора
        start_embed = time.perf_counter()
        query_vector = await self.openai_service.generate_embedding(search_query)
        emb_time = round((time.perf_counter() - start_embed) * 1000, 2)

        start_retrieve = time.perf_counter()
        results = self.vector_service.query_similar(
            query_vector=query_vector, top_k=self.top_k, score_threshold=self.threshold
        )
        ret_time = round((time.perf_counter() - start_retrieve) * 1000, 2)

        context_chunks: list[str] = []
        sources: list[str] = []
        for match in results:
            metadata = match.get("metadata", {})
            if "text" in metadata:
                context_chunks.append(metadata["text"])
            if "source" in metadata and metadata["source"] not in sources:
                sources.append(metadata["source"])

        return context_chunks, sources, {"embedding_ms": emb_time, "retrieval_ms": ret_time}

    async def process_query(self, question: str, session_id: str = "default") -> RAGResponse:
        """Повний цикл RAG (з підтримкою пам'яті та агентів): повертає фінальну відповідь та джерела."""
        start_total = time.perf_counter()

        if session_id not in _chat_memory:
            _chat_memory[session_id] = []

        history = _chat_memory[session_id][-4:]
        history_context = "\n".join(
            [
                f"{'Клієнт' if m.get('role') == 'user' else 'Ти'}: {m.get('content', '')}"
                for m in history
            ]
        )

        search_query = f"{history_context}\nКлієнт: {question}" if history_context else question
        context_chunks, sources, timings = await self._retrieve_context(search_query)

        intent_data = await self.detect_intent(question, history_context)

        system_instructions: list[str] = []
        product_facts: list[str] = []

        if intent_data.get("intent") == "product":
            product_name = str(intent_data.get("product_name", ""))
            if product_name:
                logger.info("Product intent detected", product=product_name)
                result = await self.price_comparator.compare(product_name)

                if result.needs_alert:
                    if result.alert_reason == "low_margin":
                        msg = f"🚨 <b>Аномалія ціни / Низька маржа!</b>\n📦 Товар: {result.product_name}\n🌐 Наша ціна: {result.woo_price} грн\n🇸🇰 Закупка: {result.datacomp_price_uah} грн\n📉 Маржа: {result.diff_woo_uah} грн"
                    else:
                        msg = f"⚠️ <b>Помилка Скрапера!</b>\n📦 Товар: {result.product_name}\nНе вдалося отримати ціну постачальника."

                    await self.telegram_service.send_alert(msg)

                    system_instructions.append(
                        f"СИСТЕМНА ІНСТРУКЦІЯ: Ціна та наявність для товару '{product_name}' потребують уточнення на складі. Перепроси у клієнта і скажи, що запит вже передано менеджеру, який незабаром зв'яжеться з ним. НЕ НАЗИВАЙ ЖОДНИХ ЦІН."
                    )
                elif result.woo_price:
                    product_facts.append(
                        f"ФАКТИ ПРО ТОВАР '{result.product_name}': Наша актуальна ціна {result.woo_price} грн. Статус наявності: {result.availability_status}."
                    )
                else:
                    system_instructions.append(
                        f"СИСТЕМНА ІНСТРУКЦІЯ: Скажи клієнту, що товар '{product_name}' не знайдено на нашому сайті."
                    )

        final_context = list(context_chunks)
        if product_facts:
            final_context.insert(0, "\n".join(product_facts))
        if system_instructions:
            final_context.insert(0, "\n".join(system_instructions))

        if not final_context:
            logger.info("RAG Engine fallback: no context", threshold=self.threshold)
            timings["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)
            return RAGResponse(
                answer=NO_CONTEXT_RESPONSE,
                sources=[],
                has_context=False,
            )

        extended_user_message = f"[ІСТОРІЯ ЧАТУ]\n{history_context if history_context else 'Це перше повідомлення.'}\n\n[ПОТОЧНИЙ ЗАПИТ КЛІЄНТА]\n{question}"

        start_gen = time.perf_counter()
        answer = await self.openai_service.get_chat_completion(
            system_prompt=RAG_SYSTEM_PROMPT,
            user_message=extended_user_message.strip(),
            context_chunks=final_context,
        )
        timings["generation_ms"] = round((time.perf_counter() - start_gen) * 1000, 2)
        timings["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)

        _chat_memory[session_id].append({"role": "user", "content": question})
        _chat_memory[session_id].append({"role": "bot", "content": answer})

        logger.info("RAG sync query processed", timings=timings, sources_count=len(sources))

        return RAGResponse(
            answer=answer,
            sources=sources,
            has_context=True,
        )

    async def process_query_stream(
        self, question: str, session_id: str = "default"
    ) -> AsyncGenerator[str]:
        # Управління пам'яттю
        if session_id not in _chat_memory:
            _chat_memory[session_id] = []
        history = _chat_memory[session_id][-4:]  # Останні 4 повідомлення
        history_context = "\n".join(
            [f"{'Клієнт' if m['role'] == 'user' else 'Ти'}: {m['content']}" for m in history]
        )

        # 1. Pinecone FAQ Search (шукаємо з урахуванням історії!)
        search_query = f"{history_context}\nКлієнт: {question}" if history_context else question
        context_chunks, _, _ = await self._retrieve_context(search_query)

        # 2. Agentic Intent Detection
        intent_data = await self.detect_intent(question, history_context)

        system_instructions: list[str] = []
        product_facts: list[str] = []

        if intent_data.get("intent") == "product":
            product_name = intent_data.get("product_name", "")
            logger.info("Product intent detected", product=product_name)

            # 3. Trigger Scraper & Cache
            result = await self.price_comparator.compare(product_name)

            if result.needs_alert:
                if result.alert_reason == "low_margin":
                    msg = f"🚨 <b>Аномалія ціни / Низька маржа!</b>\n📦 Товар: {result.product_name}\n🌐 Наша ціна: {result.woo_price} грн\n🇸🇰 Закупка: {result.datacomp_price_uah} грн\n📉 Маржа: {result.diff_woo_uah} грн"
                else:
                    msg = f"⚠️ <b>Помилка Скрапера!</b>\n📦 Товар: {result.product_name}\nНе вдалося отримати ціну постачальника."

                await self.telegram_service.send_alert(msg)

                system_instructions.append(
                    f"СИСТЕМНА ІНСТРУКЦІЯ: Ціна та наявність для товару '{product_name}' потребують уточнення на складі. Перепроси у клієнта і скажи, що запит вже передано менеджеру, який незабаром зв'яжеться з ним. НЕ НАЗИВАЙ ЖОДНИХ ЦІН."
                )

            elif result.woo_price:
                product_facts.append(
                    f"ФАКТИ ПРО ТОВАР '{result.product_name}': Наша актуальна ціна {result.woo_price} грн. Статус наявності: {result.availability_status}."
                )
            else:
                system_instructions.append(
                    f"СИСТЕМНА ІНСТРУКЦІЯ: Скажи клієнту, що товар '{product_name}' не знайдено на нашому сайті."
                )

        # Формуємо фінальний контекст
        final_context = list(context_chunks)
        if product_facts:
            final_context.insert(0, "\n".join(product_facts))
        if system_instructions:
            final_context.insert(0, "\n".join(system_instructions))

        # ПРОКИДАЄМО ІСТОРІЮ В LLM
        extended_user_message = f"""
[ІСТОРІЯ ЧАТУ]
{history_context if history_context else "Це перше повідомлення."}

[ПОТОЧНИЙ ЗАПИТ КЛІЄНТА]
{question}
"""
        # Запускаємо LLM
        stream = self.openai_service.stream_chat_completion(
            system_prompt=RAG_SYSTEM_PROMPT,
            user_message=extended_user_message.strip(),
            context_chunks=final_context,
        )

        full_response = ""
        async for token in stream:
            full_response += token
            yield token

        # Зберігаємо відповідь в пам'ять
        _chat_memory[session_id].append({"role": "user", "content": question})
        _chat_memory[session_id].append({"role": "bot", "content": full_response})
