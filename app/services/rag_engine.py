import html
import json
import re
import time
from collections.abc import AsyncGenerator
from typing import cast

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.schemas.chat import LeadData, LinkItem, RAGResponse
from app.services.category_manager import CategoryManager
from app.services.guardrails_service import GuardrailsService
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
        category_manager: CategoryManager,
        guardrails_service: GuardrailsService,
        settings: Settings,
    ) -> None:
        self.openai_service = openai_service
        self.vector_service = vector_service
        self.price_comparator = price_comparator
        self.telegram_service = telegram_service
        self.category_manager = category_manager
        self.guardrails_service = guardrails_service
        self.settings = settings
        self.top_k = settings.top_k_results
        self.threshold = settings.similarity_threshold

    async def detect_intent(
        self, question: str, history_context: str
    ) -> dict[str, str | None | list[str]]:
        categories_str = self.category_manager.get_categories_string()
        prompt = f"""Ти — суворий аналізатор намірів клієнта магазину техніки.
Історія розмови:
{history_context if history_context else "Немає"}

Поточний запит: "{question}"

Твоє завдання — повернути JSON з полями: "intent", "product_name", "strict_query", "broad_query", "category_query", "normalized_faq_queries" (це має бути масив рядків).

ПРАВИЛА:
1. Якщо клієнт вказує КОНКРЕТНУ назву моделі (наприклад "Acer CZ342CUR"):
   -> {{"intent": "product", "product_name": "Точна назва", "strict_query": null, "broad_query": null, "category_query": "Обери ТОЧНУ назву категорії зі списку нижче. Якщо не впевнений - null", "normalized_faq_queries": []}}
2. Якщо клієнт задає цінові рамки ("15000-20000"), просить кілька товарів або вказує загальну категорію з характеристиками ("бездротова ігрова мишка Logitech G Pro"):
   -> {{"intent": "search", "product_name": null, "strict_query": "повний комерційний запит з прикметниками (наприклад 'бездротова ігрова мишка Logitech G Pro')", "broad_query": "МАКСИМУМ 1-3 найважливіших слова: тільки бренд і базова модель, або тільки категорія (наприклад 'Logitech G Pro' або 'мишка'). Чим коротше, тим краще!", "category_query": "Обери ТОЧНУ назву категорії зі списку нижче. Якщо не впевнений - null", "normalized_faq_queries": []}}
3. Якщо клієнт використовує займенники ("цей", "він") або задає уточнююче питання ВИКЛЮЧНО про характеристики (без вказівки бренду):
   -> Знайди останню модель в Історії. Intent має бути "product".
4. Якщо клієнт явно висловлює бажання КУПИТИ або ОФОРМИТИ ЗАМОВЛЕННЯ:
   -> {{"intent": "checkout", "product_name": "ЗНАЙДЕНА_НАЗВА_З_ІСТОРІЇ", "strict_query": null, "broad_query": null, "category_query": null, "normalized_faq_queries": []}}
5. КРИТИЧНО (Гібрид): НАЯВНІСТЬ будь-якого питання про доставку, оплату, гарантію або розстрочку (навіть якщо вони комбіновані або стосуються конкретного товару) ПРИМУСОВО змінює інтент на "hybrid". Тільки так ти можеш повернути FAQ-запити.
   -> {{"intent": "hybrid", "product_name": "назва моделі (якщо є)", "strict_query": "комерційний запит (якщо є)", "broad_query": "короткий запит (якщо є)", "category_query": "ТОЧНА назва категорії", "normalized_faq_queries": ["оплата частинами", "доставка"]}}
6. КРИТИЧНО: Для "category_query" обери ТОЧНУ назву з цього списку: [{categories_str}]. Якщо нічого не підходить — null.

Відповідай ЛИШЕ валідним JSON."""

        try:
            response = await self.openai_service.get_chat_completion(
                system_prompt="Ти - системний аналізатор JSON.",
                user_message=prompt,
                context_chunks=[],
            )
            cleaned = response.replace("```json", "").replace("```", "").strip()
            parsed_json = json.loads(cleaned)
            return cast(dict[str, str | None | list[str]], parsed_json)
        except Exception as e:
            logger.error("Intent detection failed", error=str(e))
            return {"intent": "faq", "normalized_faq_queries": [question]}

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
        self, intent_data: dict[str, str | None | list[str]], history: list[dict[str, str]]
    ) -> tuple[list[str], list[str], list[dict[str, str]], bool]:
        system_instructions: list[str] = []
        product_facts: list[str] = []
        extracted_links: list[dict[str, str]] = []
        requires_lead: bool = False

        intent_type = intent_data.get("intent", "faq")
        product_name = intent_data.get("product_name")
        # РЕАЛІЗАЦІЯ ВІДНОВЛЕННЯ КОНТЕКСТУ З ІСТОРІЇ (Блокування плейсхолдерів)
        if (not product_name or product_name == "ЗНАЙДЕНА_НАЗВА_З_ІСТОРІЇ") and intent_type in [
            "product",
            "checkout",
        ]:
            for msg in reversed(history):
                content = msg.get("content", "")
                # Жорстка прив'язка до маркера "Товар", який генерує бекенд
                if msg.get("role") == "bot" and "Товар" in content:
                    # Шукаємо назву товару в одинарних або подвійних лапках
                    match = re.search(r"['\"«»]([^'\"«»]+)['\"«»]", content)
                    if match:
                        product_name = match.group(1)
                        logger.info(
                            "Recovered product name from bot history", product_name=product_name
                        )
                        break

        category_term = str(intent_data.get("category_query") or "").strip()
        category_id = (
            self.category_manager.get_category_id(category_term) if category_term else None
        )

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
            result = await self.price_comparator.compare(
                product_name_str, is_checkout=is_checkout, category_id=category_id
            )

            if result.needs_alert:
                requires_lead = True
                safe_product_name = (
                    html.escape(str(result.product_name))
                    if result.product_name
                    else "Невідомий товар"
                )
                if result.alert_reason in ["low_margin", "checkout_margin_issue"]:
                    msg = f"🚨 <b>Аномалія ціни / Зміна маржі!</b>\n📦 Товар: {safe_product_name}\n🌐 Наша ціна: {result.woo_price} грн\n🇸🇰 Закупка: {result.datacomp_price_uah} грн\n📉 Маржа: {result.diff_woo_uah} грн"
                    alert_success = await self.telegram_service.send_alert(msg)

                    if not alert_success:
                        system_instructions.append(
                            "УВАГА: Виникла технічна помилка зв'язку з менеджером (система сповіщень не працює). Вибачся перед клієнтом за тимчасові незручності і попроси його залишити свій номер телефону або Telegram/Viber прямо в чаті, щоб ми могли зв'язатися з ним як тільки систему буде відновлено."
                        )
                    elif is_checkout:
                        # Твоя логіка збереження клієнта без зміни ціни
                        system_instructions.append(
                            "Інструкція: Ти щойно актуалізував дані на складі для фіналізації замовлення і виникла необхідність додаткового узгодження деталей постачання. Ввічливо скажи клієнту, що для завершення оформлення потрібне уточнення менеджера, і попроси залишити номер телефону (Telegram/Viber)."
                        )
                    else:
                        system_instructions.append(
                            "Інструкція: Для цього товару доступна індивідуальна знижка. Запропонуй клієнту передати номер телефону (Viber/Telegram), щоб менеджер узгодив з ним фінальну ціну."
                        )
                else:
                    msg = f"⚠️ <b>Помилка Скрапера!</b>\n📦 Товар: {safe_product_name}\nНе вдалося отримати ціну."
                    alert_success = await self.telegram_service.send_alert(msg)
                    if not alert_success:
                        system_instructions.append(
                            "УВАГА: Виникла технічна помилка зв'язку з менеджером (система сповіщень не працює). Вибачся перед клієнтом за тимчасові незручності і попроси його залишити свій номер телефону або Telegram/Viber прямо в чаті, щоб ми могли зв'язатися з ним як тільки систему буде відновлено."
                        )
                    else:
                        system_instructions.append(
                            f"Інформація для тебе: ціна на '{product_name_str}' зараз перевіряється. Скажи клієнту, що запит передано менеджеру і попроси контакти."
                        )

            # Якщо все добре і це оформлення замовлення
            elif is_checkout:
                requires_lead = True
                if result.woo_url:
                    extracted_links.append({"text": "Оформити замовлення", "url": result.woo_url})
                extracted_links.append(
                    {"text": "✈️ Написати в Telegram", "url": self.settings.telegram_contact_url}
                )
                extracted_links.append(
                    {"text": "📞 Написати у Viber", "url": self.settings.viber_contact_url}
                )
                system_instructions.append(
                    f"Клієнт хоче купити '{product_name_str}'. ТВОЯ ЗАДАЧА:\n"
                    f"Скажи, що він може оформити замовлення самостійно (кнопка вже згенерована) АБО просто залишити номер телефону тут, і менеджер все оформить сам. Також запропонуй написати нам в Інстаграм."
                )

            # Якщо все добре і це просто консультація
            else:
                if result.woo_price:
                    if result.woo_url:
                        extracted_links.append(
                            {"text": f"Переглянути {result.product_name}", "url": result.woo_url}
                        )
                    system_instructions.append(
                        f"Бекенд знайшов товар '{result.product_name}', який є відповіддю на поточний запит клієнта. "
                        f"Обов'язково розкажи про нього і не кажи, що інформації не знайдено."
                    )
                    product_facts.append(
                        f"Дані: Товар '{result.product_name}', {result.woo_price} грн. Умови: {result.availability_status}.\n"
                        f"КРИТИЧНО: Якщо товар 'В наявності' - 1-3 дні. 'Під замовлення' - 14-20 днів. ПОСИЛАННЯ В ТЕКСТ НЕ ПИСАТИ!"
                    )
                    if result.attributes:
                        attr_str = "\n".join([f"- {k}: {v}" for k, v in result.attributes.items()])
                        product_facts.append(f"Характеристики:\n{attr_str}")
                    if result.short_description:
                        product_facts.append(f"Опис:\n{result.short_description}")
                else:
                    # ДИНАМІЧНИЙ FALLBACK: Товар не знайдено скрапером, провалюємося в search
                    logger.info(
                        "Product not found by price_comparator, falling back to search cascade",
                        product=product_name_str,
                    )
                    intent_type = "search"
                    intent_data["strict_query"] = product_name_str
                    intent_data["broad_query"] = product_name_str
                    # category_query залишається таким, як його міг заповнити LLM, або порожнім

        if intent_type == "search":
            strict_term = str(
                intent_data.get("strict_query")
                or intent_data.get("search_term")
                or intent_data.get("search_query")
                or ""
            ).strip()
            broad_term = str(intent_data.get("broad_query") or "").strip()

            woo_products = []
            if strict_term:
                logger.info(
                    "Search intent detected (strict)", query=strict_term, category_id=category_id
                )
                woo_products = await self.price_comparator.woo_service.search_products_async(
                    strict_term, category_id=category_id, limit=3
                )

            is_fallback_broad = False
            is_fallback_category = False

            if not woo_products and broad_term and broad_term != strict_term:
                logger.info(
                    "Strict search failed, trying fallback broad search",
                    query=broad_term,
                    category_id=category_id,
                )
                woo_products = await self.price_comparator.woo_service.search_products_async(
                    broad_term, category_id=category_id, limit=3
                )
                if woo_products:
                    is_fallback_broad = True

            if not woo_products:
                if category_id is not None:
                    logger.info(
                        "Text search failed or empty, trying fallback category search",
                        category_id=category_id,
                    )
                    woo_products = (
                        await self.price_comparator.woo_service.search_products_by_category_async(
                            category_id, limit=3
                        )
                    )
                    if woo_products:
                        is_fallback_category = True
                else:
                    logger.info("Search cascade aborted: category_id is None")

            search_facts: list[str] = []
            if woo_products:
                search_facts.append("Знайдено у нашому магазині:")
                for p in woo_products:
                    status = "В наявності" if p.stock_status == "instock" else "Під замовлення"
                    search_facts.append(
                        f"- Назва: {p.name}\n  Ціна: {p.price_uah} грн\n  Статус: {status}"
                    )

                    if p.attributes:
                        top_attrs = list(p.attributes.items())[:5]
                        attr_str = "\n".join([f"    * {k}: {v}" for k, v in top_attrs])
                        search_facts.append(f"  Характеристики:\n{attr_str}")

                    if p.url:
                        extracted_links.append({"text": p.name, "url": p.url})
                search_facts.append(
                    "ВКАЗІВКА: Посилання вже згенеровані системою. Не дублюй їх у тексті."
                )
                product_facts.append("\n".join(search_facts))

                if is_fallback_category:
                    system_instructions.append(
                        "Ти шукав конкретику, але бекенд знайшов товари лише за категорією. "
                        "Адаптуй відповідь: якщо клієнт шукав КОНКРЕТНУ модель, ввічливо скажи, що її немає, але є альтернативи. Якщо запит клієнта був загальним (наприклад 'які є SSD'), просто радо презентуй знайдені товари без жодних вибачень."
                    )
                elif is_fallback_broad:
                    system_instructions.append(
                        f"Бекенд виконав розширений пошук за запитом '{broad_term}'. "
                        f"Адаптуй відповідь: якщо клієнт шукав КОНКРЕТНУ модель ('{strict_term}'), ввічливо скажи, що її немає, але є альтернативи. Якщо запит клієнта був загальним, просто радо презентуй знайдені товари без вибачень."
                    )
            else:
                requires_lead = True
                system_instructions.append(
                    "Інформація: за запитом нічого не знайдено. Запропонуй клієнту залишити номер телефону, щоб менеджер підібрав аналог."
                )

        return product_facts, system_instructions, extracted_links, requires_lead

    async def process_query(
        self, question: str, session_id: str = "default", client_ip: str | None = None
    ) -> RAGResponse:
        start_total = time.perf_counter()

        if not self.guardrails_service.validate_input(question, client_ip=client_ip):
            return RAGResponse(
                answer="Вибачте, виникла технічна затримка при обробці запиту. Будь ласка, переформулюйте питання стосовно товарів.",
                sources=[],
                has_context=False,
                links=[],
                requires_lead=False,
            )

        if session_id not in _chat_memory:
            _chat_memory[session_id] = []

        cleaned_q = re.sub(r"[\s\-\(\)]", "", question)
        phone_match = re.search(r"(?:\+380|380|0)\d{9}", cleaned_q)
        if phone_match:
            phone_number = phone_match.group(0)
            logger.info("Direct lead captured from chat", session_id=session_id)
            try:
                lead = LeadData(phone=phone_number)
                lead_success = await self.telegram_service.send_lead(
                    lead, context_info=f"Повідомлення клієнта: '{question}'. Сесія: {session_id}"
                )
                if lead_success:
                    msg = "Ваш запит отримано. Менеджер з вами зв'яжеться. Також можете написати нам в Інстаграм..."
                else:
                    msg = "На жаль, виникла технічна помилка при передачі вашого запиту менеджеру. Будь ласка, напишіть нам напряму в Telegram або Viber, щоб ми могли вам допомогти."
                _chat_memory[session_id].append({"role": "user", "content": question})
                _chat_memory[session_id].append({"role": "bot", "content": msg})
                return RAGResponse(
                    answer=msg,
                    sources=[],
                    has_context=False,
                    links=[
                        LinkItem(
                            text="✈️ Написати в Telegram", url=self.settings.telegram_contact_url
                        ),
                        LinkItem(text="📞 Написати у Viber", url=self.settings.viber_contact_url),
                    ],
                    requires_lead=False,
                )
            except Exception as e:
                logger.warning("Lead capture validation failed", error=str(e))

        history = _chat_memory[session_id][-6:]
        history_context = "\n".join(
            [
                f"{'Клієнт' if m.get('role') == 'user' else 'Ти'}: {m.get('content', '')}"
                for m in history
            ]
        )

        intent_data = await self.detect_intent(question, history_context)

        intent_type = intent_data.get("intent", "faq")

        # Програмне обнулення FAQ для точних товарів та пошуку
        if intent_type in ["product", "search", "checkout"]:
            intent_data["normalized_faq_queries"] = []

        if intent_type == "search":
            _chat_memory[session_id] = []
            history_context = ""
            history = []

        normalized_queries = intent_data.get("normalized_faq_queries", [])
        if isinstance(normalized_queries, str):
            normalized_queries = [normalized_queries]
        elif not isinstance(normalized_queries, list):
            normalized_queries = []

        context_chunks: list[str] = []
        sources: list[str] = []
        timings: dict[str, float] = {}

        if normalized_queries:
            for nq in normalized_queries:
                if str(nq).strip():
                    c_chunks, c_sources, pinecone_timings = await self._retrieve_context(nq)
                    context_chunks.extend(c_chunks)
                    for src in c_sources:
                        if src not in sources:
                            sources.append(src)
                    for k, v in pinecone_timings.items():
                        timings[k] = timings.get(k, 0.0) + v

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
                requires_lead=True,
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
        self, question: str, session_id: str = "default", client_ip: str | None = None
    ) -> AsyncGenerator[str]:
        """Повний цикл RAG для стрімінгових запитів (SSE)."""
        if not self.guardrails_service.validate_input(question, client_ip=client_ip):
            fallback_msg = "Вибачте, виникла технічна затримка при обробці запиту. Будь ласка, переформулюйте питання стосовно товарів."
            meta_payload = json.dumps({"links": [], "requires_lead": False}, ensure_ascii=False)
            yield f"[METADATA] {meta_payload}"
            yield json.dumps({"token": fallback_msg}, ensure_ascii=False)
            return

        if session_id not in _chat_memory:
            _chat_memory[session_id] = []

        # ЖОРСТКЕ ПЕРЕХОПЛЕННЯ ЛІДІВ (Байпас LLM для Stream)
        cleaned_q = re.sub(r"[\s\-\(\)]", "", question)
        phone_match = re.search(r"(?:\+380|380|0)\d{9}", cleaned_q)
        if phone_match:
            phone_number = phone_match.group(0)
            logger.info("Direct lead captured from stream", session_id=session_id)
            try:
                lead = LeadData(phone=phone_number)
                lead_success = await self.telegram_service.send_lead(
                    lead, context_info=f"Повідомлення клієнта: '{question}'. Сесія: {session_id}"
                )
                if lead_success:
                    msg = "Ваш запит отримано. Менеджер з вами зв'яжеться. Також можете написати нам в Інстаграм..."
                else:
                    msg = "На жаль, виникла технічна помилка при передачі вашого запиту менеджеру. Будь ласка, напишіть нам напряму в Telegram або Viber, щоб ми могли вам допомогти."

                meta_payload = json.dumps(
                    {
                        "links": [
                            {
                                "text": "✈️ Написати в Telegram",
                                "url": self.settings.telegram_contact_url,
                            },
                            {"text": "📞 Написати у Viber", "url": self.settings.viber_contact_url},
                        ],
                        "requires_lead": False,
                    },
                    ensure_ascii=False,
                )
                yield f"[METADATA] {meta_payload}"
                yield json.dumps({"token": msg}, ensure_ascii=False)

                _chat_memory[session_id].append({"role": "user", "content": question})
                _chat_memory[session_id].append({"role": "bot", "content": msg})
                return
            except Exception as e:
                logger.warning("Lead capture validation failed in stream", error=str(e))

        history = _chat_memory[session_id][-6:]
        history_context = "\n".join(
            [f"{'Клієнт' if m['role'] == 'user' else 'Ти'}: {m['content']}" for m in history]
        )

        intent_data = await self.detect_intent(question, history_context)

        # САНІТИЗАЦІЯ ПАМ'ЯТІ ПРИ ЗМІНІ ТЕМИ ПОШУКУ
        if intent_data.get("intent") == "search":
            _chat_memory[session_id] = []
            history_context = ""
            history = []
        normalized_queries = intent_data.get("normalized_faq_queries", [])
        if isinstance(normalized_queries, str):
            normalized_queries = [normalized_queries]
        elif not isinstance(normalized_queries, list):
            normalized_queries = []

        context_chunks: list[str] = []

        if normalized_queries:
            for nq in normalized_queries:
                if str(nq).strip():
                    c_chunks, _, _ = await self._retrieve_context(nq)
                    context_chunks.extend(c_chunks)

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
        meta_payload = json.dumps(
            {"links": extracted_links, "requires_lead": requires_lead}, ensure_ascii=False
        )
        yield f"[METADATA] {meta_payload}"

        full_response = ""
        try:
            stream = self.openai_service.stream_chat_completion(
                system_prompt=RAG_SYSTEM_PROMPT,
                user_message=extended_user_message.strip(),
                context_chunks=final_context,
            )

            async for token in stream:
                full_response += token
                yield json.dumps({"token": token}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"OpenAI Stream failed: {e}")
            fallback_msg = (
                "\n\nСервіс тимчасово недоступний. Спробуйте пізніше або зв'яжіться з менеджером."
            )
            yield json.dumps({"token": fallback_msg}, ensure_ascii=False)
            full_response += fallback_msg
        finally:
            _chat_memory[session_id].append({"role": "bot", "content": full_response})
