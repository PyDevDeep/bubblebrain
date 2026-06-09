import json
import time
from collections.abc import AsyncGenerator
from typing import cast

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

    async def detect_intent(self, question: str, history_context: str) -> dict[str, str | None]:
        prompt = f"""Ти — суворий аналізатор намірів клієнта магазину техніки.
Історія розмови:
{history_context if history_context else "Немає"}

Поточний запит: "{question}"

Твоє завдання — повернути JSON з полями: "intent", "product_name", "search_term", "normalized_faq_query".

ПРАВИЛА:
1. Якщо клієнт вказує КОНКРЕТНУ назву моделі (наприклад "Acer CZ342CUR"):
   -> {{"intent": "product", "product_name": "Точна назва", "search_term": null, "normalized_faq_query": null}}
2. Якщо клієнт задає цінові рамки ("15000-20000"), просить кілька товарів ("3-4 монітори") або вказує НОВУ загальну категорію ("а є мишки?"):
   -> {{"intent": "search", "product_name": null, "search_term": "чистий запит без цифр кількості (наприклад 'монітор')", "normalized_faq_query": null}}
3. КРИТИЧНО ДЛЯ ІСТОРІЇ: Якщо клієнт використовує займенники ("цей", "він") АБО задає уточнююче питання без вказівки бренду ("яка ціна?", "а характеристики?"):
   -> Обов'язково знайди останню обговорювану модель в Історії (без кирилиці) і поверни її в "product_name". Intent має бути "product".
4. Якщо клієнт явно висловлює бажання КУПИТИ або ОФОРМИТИ ЗАМОВЛЕННЯ:
   -> {{"intent": "checkout", "product_name": "ЗНАЙДЕНА_НАЗВА_З_ІСТОРІЇ", "search_term": null, "normalized_faq_query": null}}
5. Запити про доставку, оплату або питання до конкретного товару:
   -> {{"intent": "hybrid" або "faq", "product_name": "назва з історії", "search_term": null, "normalized_faq_query": "перекладений запит"}}

Відповідай ЛИШЕ валідним JSON."""

        try:
            response = await self.openai_service.get_chat_completion(
                system_prompt="Ти - системний аналізатор JSON.",
                user_message=prompt,
                context_chunks=[],
            )
            cleaned = response.replace("```json", "").replace("```", "").strip()
            parsed_json = json.loads(cleaned)
            return cast(dict[str, str | None], parsed_json)
        except Exception as e:
            logger.error("Intent detection failed", error=str(e))
            return {"intent": "faq", "normalized_faq_query": question}

    async def _retrieve_context(
        self, search_query: str
    ) -> tuple[list[str], list[str], dict[str, float]]:
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
                context_chunks.append(str(metadata["text"]))
            if "source" in metadata and str(metadata["source"]) not in sources:
                sources.append(str(metadata["source"]))

        return context_chunks, sources, {"embedding_ms": emb_time, "retrieval_ms": ret_time}

    async def _get_intent_context(
        self, intent_data: dict[str, str | None], history: list[dict[str, str]]
    ) -> tuple[list[str], list[str], list[dict[str, str]], bool]:
        system_instructions: list[str] = []
        product_facts: list[str] = []
        extracted_links: list[dict[str, str]] = []
        requires_lead: bool = False

        intent_type = intent_data.get("intent", "faq")
        product_name = intent_data.get("product_name")
        if not product_name and intent_type in ["product", "checkout"]:
            for msg in reversed(history):
                if msg["role"] == "bot" and "Товар" in msg["content"]:
                    pass  # Логіка витягнення назви, якщо потрібно

        # 1. ОБРОБКА КОНКРЕТНОГО ТОВАРУ (Consultation & Checkout)
        if intent_type in ["product", "hybrid", "checkout"] and product_name:
            is_checkout = intent_type == "checkout"
            product_name_str = str(product_name)
            logger.info(
                "Product/Checkout intent detected",
                product=product_name_str,
                is_checkout=is_checkout,
            )

            # Виклик з ігноруванням кешу, якщо це чекаут
            result = await self.price_comparator.compare(product_name_str, is_checkout=is_checkout)

            if result.needs_alert:
                requires_lead = True
                if result.alert_reason in ["low_margin", "checkout_margin_issue"]:
                    msg = f"🚨 <b>Аномалія ціни / Зміна маржі!</b>\n📦 Товар: {result.product_name}\n🌐 Наша ціна: {result.woo_price} грн\n🇸🇰 Закупка: {result.datacomp_price_uah} грн\n📉 Маржа: {result.diff_woo_uah} грн"
                    await self.telegram_service.send_alert(msg)

                    if is_checkout:
                        # Твоя логіка збереження клієнта без зміни ціни
                        system_instructions.append(
                            "Інструкція: Ти щойно актуалізував дані на складі для фіналізації замовлення і виникла необхідність додаткового узгодження деталей постачання. Ввічливо скажи клієнту, що для завершення оформлення потрібне уточнення менеджера, і попроси залишити номер телефону (Telegram/Viber)."
                        )
                    else:
                        system_instructions.append(
                            "Інструкція: Для цього товару доступна індивідуальна знижка. Запропонуй клієнту передати номер телефону (Viber/Telegram), щоб менеджер узгодив з ним фінальну ціну."
                        )
                else:
                    msg = f"⚠️ <b>Помилка Скрапера!</b>\n📦 Товар: {result.product_name}\nНе вдалося отримати ціну."
                    await self.telegram_service.send_alert(msg)
                    system_instructions.append(
                        f"Інформація для тебе: ціна на '{product_name_str}' зараз перевіряється. Скажи клієнту, що запит передано менеджеру і попроси контакти."
                    )

            # Якщо все добре і це оформлення замовлення
            elif is_checkout:
                requires_lead = True
                if result.woo_url:
                    extracted_links.append({"text": "Оформити замовлення", "url": result.woo_url})
                system_instructions.append(
                    f"Клієнт хоче купити '{product_name_str}'. ТВОЯ ЗАДАЧА:\n"
                    f"Скажи, що він може оформити замовлення самостійно (кнопка вже згенерована) АБО просто залишити номер телефону тут, і менеджер все оформить сам."
                )

            # Якщо все добре і це просто консультація
            else:
                if result.woo_price:
                    if result.woo_url:
                        extracted_links.append(
                            {"text": f"Переглянути {result.product_name}", "url": result.woo_url}
                        )
                    product_facts.append(
                        f"Дані: Товар '{result.product_name}', {result.woo_price} грн. Умови: {result.availability_status}.\n"
                        f"КРИТИЧНО: Якщо товар 'В наявності' - 1-3 дні. 'Під замовлення' - 14-20 днів. ПОСИЛАННЯ В ТЕКСТ НЕ ПИСАТИ!"
                    )
                else:
                    system_instructions.append(f"Інформація: товар '{product_name_str}' відсутній.")

        # 2. КАТЕГОРІЙНИЙ ПОШУК
        elif intent_type == "search":
            search_term = str(
                intent_data.get("search_term") or intent_data.get("search_query") or ""
            )
            if search_term:
                logger.info("Search intent detected", query=search_term)
                woo_products = await self.price_comparator.woo_service.search_products_async(
                    search_term, limit=3
                )

                search_facts: list[str] = []
                if woo_products:
                    search_facts.append("Знайдено у нашому магазині:")
                    for p in woo_products:
                        status = "В наявності" if p.stock_status == "instock" else "Під замовлення"
                        search_facts.append(f"- {p.name}: {p.price_uah} грн, статус: {status}")
                        if p.url:
                            extracted_links.append({"text": p.name, "url": p.url})
                    search_facts.append(
                        "ВКАЗІВКА: Посилання вже згенеровані системою. Не дублюй їх у тексті."
                    )
                    product_facts.append("\n".join(search_facts))
                else:
                    requires_lead = True
                    system_instructions.append(
                        f"Інформація: за запитом '{search_term}' нічого не знайдено. Запропонуй клієнту залишити номер телефону, щоб менеджер підібрав аналог."
                    )

        return product_facts, system_instructions, extracted_links, requires_lead

    async def process_query(self, question: str, session_id: str = "default") -> RAGResponse:
        """Повний цикл RAG для синхронних запитів."""
        start_total = time.perf_counter()

        if session_id not in _chat_memory:
            _chat_memory[session_id] = []

        history = _chat_memory[session_id][-6:]
        history_context = "\n".join(
            [
                f"{'Клієнт' if m.get('role') == 'user' else 'Ти'}: {m.get('content', '')}"
                for m in history
            ]
        )

        intent_data = await self.detect_intent(question, history_context)
        normalized_query = intent_data.get("normalized_faq_query")

        context_chunks: list[str] = []
        sources: list[str] = []
        timings: dict[str, float] = {}

        if intent_data.get("intent") in ["faq", "hybrid"] and normalized_query:
            context_chunks, sources, pinecone_timings = await self._retrieve_context(
                str(normalized_query)
            )
            timings.update(pinecone_timings)

        (
            product_facts,
            system_instructions,
            extracted_links,
            requires_lead,
        ) = await self._get_intent_context(intent_data, history)

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
                links=[],
                requires_lead=True,  # Якщо нічого не знайдено, пропонуємо залишити контакти
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
        return RAGResponse.model_validate(
            {
                "answer": answer,
                "sources": sources,
                "has_context": True,
                "links": extracted_links,
                "requires_lead": requires_lead,
            }
        )

    async def process_query_stream(
        self, question: str, session_id: str = "default"
    ) -> AsyncGenerator[str]:
        """Повний цикл RAG для стрімінгових запитів (SSE)."""
        if session_id not in _chat_memory:
            _chat_memory[session_id] = []

        history = _chat_memory[session_id][-6:]
        history_context = "\n".join(
            [f"{'Клієнт' if m['role'] == 'user' else 'Ти'}: {m['content']}" for m in history]
        )

        intent_data = await self.detect_intent(question, history_context)
        normalized_query = intent_data.get("normalized_faq_query")

        context_chunks: list[str] = []

        if intent_data.get("intent") in ["faq", "hybrid"] and normalized_query:
            context_chunks, _, _ = await self._retrieve_context(str(normalized_query))

        (
            product_facts,
            system_instructions,
            extracted_links,
            requires_lead,
        ) = await self._get_intent_context(intent_data, history)

        # УВАГА: Для SSE стрімінгу передача метаданих (links, requires_lead)
        # вимагає оновлення формату генератора в chat.py на кастомні event-типи.
        # Наразі фронтенд отримуватиме лише потік тексту відповіді.

        final_context = list(context_chunks)
        if product_facts:
            final_context.insert(0, "\n".join(product_facts))
        if system_instructions:
            final_context.insert(0, "\n".join(system_instructions))

        extended_user_message = f"""
[ІСТОРІЯ ЧАТУ]
{history_context if history_context else "Це перше повідомлення."}

[ПОТОЧНИЙ ЗАПИТ КЛІЄНТА]
{question}
"""
        _chat_memory[session_id].append({"role": "user", "content": question})

        # Спочатку віддаємо фронтенду метадані (посилання та прапорці)
        meta_payload = json.dumps({"links": extracted_links, "requires_lead": requires_lead})
        yield f"[METADATA] {meta_payload}"

        stream = self.openai_service.stream_chat_completion(
            system_prompt=RAG_SYSTEM_PROMPT,
            user_message=extended_user_message.strip(),
            context_chunks=final_context,
        )

        full_response = ""
        try:
            async for token in stream:
                full_response += token
                yield token
        finally:
            _chat_memory[session_id].append({"role": "bot", "content": full_response})
