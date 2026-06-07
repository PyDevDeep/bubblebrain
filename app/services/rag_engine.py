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
        prompt = f"""Ти — суворий аналізатор намірів клієнта магазину техніки.
        Історія розмови:
        {history_context if history_context else "Немає"}

        Поточний запит: "{question}"

        ПРАВИЛА:
        1. Якщо клієнт явно вказує КОНКРЕТНУ назву або модель товару (наприклад "Sony Playstation", "Acer CZ342CUR"), поверни JSON: {{"intent": "product", "product_name": "Точна назва моделі"}}.
        2. КРИТИЧНО: При витягуванні "product_name" відкидай ВСЕ кириличне сміття (наприклад "об'ємом 4 ТБ", "чорний", "купити"). Залишай ТІЛЬКИ базову англійську назву бренду та моделі (наприклад "Crucial T705 4TB" або просто "Crucial T705").
        3. Якщо клієнт шукає або цікавиться наявністю групи товарів, категорії, бренду чи характеристик (наприклад "ссд на 4 тб", "ігрові монітори", "мишка razer", "ssd 4tb", "що порадите з відеокарт"), поверни JSON: {{"intent": "search", "search_query": "Очищений пошуковий запит англійською або транслітом, наприклад 'ssd 4tb' чи 'razer mouse'"}}.
        4. Якщо клієнт запитує про загальну категорію без вказівки характеристик/брендів ("монітор", "товар", "каталог") - поверни {{"intent": "faq"}}.
        5. Якщо клієнт використовує займенники ("цей", "він", "яка ціна") - знайди конкретну модель в Історії (очищену від кирилиці) і поверни її в "product_name". Якщо моделі немає - {{"intent": "faq"}}.
        6. Запити про доставку, оплату, гарантію -> {{"intent": "faq"}}.

        Відповідай ЛИШЕ валідним JSON, без жодного іншого тексту чи маркдауну."""

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

    async def _get_intent_context(self, intent_data: dict[str, str]) -> tuple[list[str], list[str]]:
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
                        f"Інформація для тебе: ціна та наявність на '{product_name}' зараз перевіряється. М'яко скажи клієнту, що запит передано менеджеру для уточнення. Не називай жодних цін."
                    )
                elif result.woo_price:
                    product_facts.append(
                        f"Дані для відповіді: Товар '{result.product_name}' коштує {result.woo_price} грн. Умови: {result.availability_status}. Якщо клієнт питає про характеристики, ввічливо повідом, що всі детальні характеристики можна переглянути на сторінці товару на нашому сайті."
                    )
                elif result.datacomp_price_uah:
                    product_facts.append(
                        f"Дані для відповіді: Товар '{result.product_name}' відсутній на нашому складі, але ми можемо замовити його для вас у постачальника з Європи. Орієнтовна ціна: {result.datacomp_price_uah} грн. Умови доставки: {result.availability_status}. Посилання для ознайомлення: {result.datacomp_url}"
                    )
                else:
                    system_instructions.append(
                        f"Інформація для тебе: товар '{product_name}' відсутній на нашому сайті та у постачальників."
                    )

        elif intent_data.get("intent") == "search":
            search_query = str(intent_data.get("search_query", ""))
            if search_query:
                logger.info("Search intent detected", query=search_query)
                woo_products = await self.price_comparator.woo_service.search_products_async(
                    search_query, limit=3
                )
                dc_products = await self.price_comparator.scraper_service.scrape_datacomp_multi(
                    search_query, limit=3
                )

                search_facts: list[str] = []
                if woo_products:
                    search_facts.append("Знайдено у нашому магазині (Digital Dreams):")
                    for p in woo_products:
                        status = (
                            "В наявності" if p.stock_status == "instock" else "Немає в наявності"
                        )
                        search_facts.append(
                            f"- {p.name}: ціна {p.price_uah} грн, статус: {status}, посилання: {p.url}"
                        )

                if dc_products:
                    search_facts.append("Знайдено у постачальника (можна замовити під клієнта):")
                    for p in dc_products:
                        availability = self.price_comparator.map_availability(p.availability_status)
                        price_desc = f"{p.price_uah} грн" if p.price_uah else "ціна уточнюється"
                        search_facts.append(
                            f"- {p.name}: орієнтовна ціна {price_desc}, умови доставки: {availability}, посилання: {p.url}"
                        )

                if search_facts:
                    product_facts.append("\n".join(search_facts))
                else:
                    system_instructions.append(
                        f"Інформація для тебе: за запитом '{search_query}' товарів не знайдено ні в нашому магазині, ні у постачальників. Запропонуй менеджеру зв'язатися для підбору."
                    )

        return product_facts, system_instructions

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

        search_query = question
        context_chunks, sources, timings = await self._retrieve_context(search_query)

        intent_data = await self.detect_intent(question, history_context)

        product_facts, system_instructions = await self._get_intent_context(intent_data)

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
        """Повний цикл RAG для стрімінгових запитів (SSE)."""
        if session_id not in _chat_memory:
            _chat_memory[session_id] = []

        history = _chat_memory[session_id][-6:]
        history_context = "\n".join(
            [f"{'Клієнт' if m['role'] == 'user' else 'Ти'}: {m['content']}" for m in history]
        )

        search_query = question
        context_chunks, _, _ = await self._retrieve_context(search_query)

        intent_data = await self.detect_intent(question, history_context)

        product_facts, system_instructions = await self._get_intent_context(intent_data)

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
