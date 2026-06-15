import asyncio
import html
import json
import re
import time
from collections.abc import AsyncGenerator
from typing import Any, cast

from app.core.config import Settings
from app.core.constants import (
    ALERT_MARGIN_ISSUE,
    ALERT_SCRAPER_FAILED,
    INSTR_ALERT_FAILED,
    INSTR_CHECKOUT_PRICE_ISSUE,
    INSTR_CHECKOUT_TELEGRAM,
    INSTR_DISCOUNT_AVAILABLE,
    INSTR_FALLBACK_CATEGORY,
    INSTR_NO_DUPLICATE_LINKS,
    INSTR_NOTHING_FOUND,
    INSTR_PRICE_CHECKING,
    INSTR_PRODUCT_FOUND,
    INTENT_CHECKOUT,
    INTENT_FAQ,
    INTENT_HYBRID,
    INTENT_PRODUCT,
    INTENT_SEARCH,
    LINK_CHECKOUT,
    LINK_TELEGRAM,
    LINK_VIBER,
    MSG_GUARDRAIL_FAILED,
    MSG_LEAD_FAILED,
    MSG_LEAD_SUCCESS,
    MSG_STREAM_FAILED,
    REGEX_CLEAN_QUERY,
    REGEX_PHONE,
    SEARCH_FOUND_HEADER,
    STATUS_INSTOCK,
    STATUS_OUT_OF_STOCK,
)
from app.core.logging_config import get_logger
from app.schemas.chat import LeadData, LinkItem, RAGResponse
from app.services.category_manager import CategoryManager
from app.services.chat_memory_service import ChatMemoryService
from app.services.guardrails_service import GuardrailsService
from app.services.openai_service import OpenAIService
from app.services.price_comparator import PriceComparator
from app.services.telegram_service import TelegramService
from app.services.vector_service import VectorService
from app.utils.prompts import INTENT_ANALYZER_PROMPT, NO_CONTEXT_RESPONSE, RAG_SYSTEM_PROMPT

logger = get_logger(__name__)


class RAGEngine:
    """
    RAGEngine is the core orchestrator for handling user queries.
    It manages intent detection, vector search, price comparison,
    lead capturing, and response generation (sync and streaming).
    """

    def __init__(
        self,
        openai_service: OpenAIService,
        vector_service: VectorService,
        price_comparator: PriceComparator,
        telegram_service: TelegramService,
        category_manager: CategoryManager,
        guardrails_service: GuardrailsService,
        chat_memory_service: ChatMemoryService,
        settings: Settings,
    ) -> None:
        self.openai_service = openai_service
        self.vector_service = vector_service
        self.price_comparator = price_comparator
        self.telegram_service = telegram_service
        self.category_manager = category_manager
        self.guardrails_service = guardrails_service
        self.chat_memory_service = chat_memory_service
        self.settings = settings
        self.top_k = settings.top_k_results
        self.threshold = settings.similarity_threshold

    async def detect_intent(self, question: str, history_context: str) -> dict[str, Any]:
        """
        Detects user intent using an LLM based on the conversation history and current question.

        Args:
            question: The user's query.
            history_context: String representation of the chat history.

        Returns:
            Dictionary containing 'intent', 'product_name', 'strict_query',
            'broad_query', 'category_query', and 'normalized_faq_queries'.
        """
        categories_str = self.category_manager.get_categories_string()

        prompt = INTENT_ANALYZER_PROMPT.format(
            history_context=history_context if history_context else "None",
            question=question,
            categories_str=categories_str,
            intent_product=INTENT_PRODUCT,
            intent_search=INTENT_SEARCH,
            intent_checkout=INTENT_CHECKOUT,
            intent_hybrid=INTENT_HYBRID,
        )

        try:
            response = await self.openai_service.get_chat_completion(
                system_prompt="You are a system JSON analyzer.",
                user_message=prompt,
                context_chunks=[],
            )
            cleaned = response.replace("```json", "").replace("```", "").strip()
            parsed_json = json.loads(cleaned)
            return cast(dict[str, Any], parsed_json)
        except json.JSONDecodeError:
            logger.exception("Intent detection JSON parsing failed")
            return {"intent": INTENT_FAQ, "normalized_faq_queries": [question]}
        except Exception:
            logger.exception("Intent detection generic error")
            return {"intent": INTENT_FAQ, "normalized_faq_queries": [question]}

    async def _retrieve_context(
        self, search_query: str
    ) -> tuple[list[str], set[str], dict[str, float]]:
        """
        Retrieves relevant document chunks from the vector database.
        """
        start_embed = time.perf_counter()
        query_vector = await self.openai_service.generate_embedding(search_query)
        emb_time = round((time.perf_counter() - start_embed) * 1000, 2)

        start_retrieve = time.perf_counter()
        results = self.vector_service.query_similar(
            query_vector=query_vector, top_k=self.top_k, score_threshold=self.threshold
        )
        ret_time = round((time.perf_counter() - start_retrieve) * 1000, 2)

        context_chunks: list[str] = []
        sources: set[str] = set()

        for match in results:
            metadata = match.get("metadata", {})
            if "text" in metadata:
                context_chunks.append(str(metadata["text"]))
            if "source" in metadata:
                sources.add(str(metadata["source"]))

        return context_chunks, sources, {"embedding_ms": emb_time, "retrieval_ms": ret_time}

    async def _handle_product_checkout_intent(
        self,
        intent_type: str,
        product_name: str,
        category_id: int | None,
        system_instructions: list[str],
        product_facts: list[str],
        extracted_links: list[dict[str, str]],
    ) -> tuple[bool, str]:
        """
        Handles explicit product inquiries and checkout flows by comparing prices
        and generating appropriate alert/system messages.
        Returns (requires_lead, fallback_intent_type).
        """
        is_checkout = intent_type == INTENT_CHECKOUT
        requires_lead = False
        new_intent_type = intent_type

        logger.info(
            "Product/Checkout intent detected",
            product=product_name,
            is_checkout=is_checkout,
        )

        result = await self.price_comparator.compare(
            product_name, is_checkout=is_checkout, category_id=category_id
        )

        if result.needs_alert:
            requires_lead = True
            safe_product_name = (
                html.escape(str(result.product_name)) if result.product_name else "Unknown Product"
            )

            if result.alert_reason in ["low_margin", "checkout_margin_issue"]:
                msg = ALERT_MARGIN_ISSUE.format(
                    safe_product_name=safe_product_name,
                    woo_price=result.woo_price,
                    datacomp_price=result.datacomp_price_uah,
                    diff_woo=result.diff_woo_uah,
                )
                alert_success = await self.telegram_service.send_alert(msg)

                if not alert_success:
                    system_instructions.append(INSTR_ALERT_FAILED)
                elif is_checkout:
                    system_instructions.append(INSTR_CHECKOUT_PRICE_ISSUE)
                else:
                    system_instructions.append(INSTR_DISCOUNT_AVAILABLE)
            else:
                msg = ALERT_SCRAPER_FAILED.format(safe_product_name=safe_product_name)
                alert_success = await self.telegram_service.send_alert(msg)

                if not alert_success:
                    system_instructions.append(INSTR_ALERT_FAILED)
                else:
                    system_instructions.append(
                        INSTR_PRICE_CHECKING.format(product_name=product_name)
                    )

        elif is_checkout:
            requires_lead = True
            if result.woo_url:
                extracted_links.append({"text": LINK_CHECKOUT, "url": result.woo_url})
            extracted_links.append(
                {"text": LINK_TELEGRAM, "url": self.settings.telegram_contact_url}
            )
            extracted_links.append({"text": LINK_VIBER, "url": self.settings.viber_contact_url})

            system_instructions.append(INSTR_CHECKOUT_TELEGRAM.format(product_name=product_name))

        else:
            if result.woo_price:
                if result.woo_url:
                    extracted_links.append(
                        {"text": f"View {result.product_name}", "url": result.woo_url}
                    )
                system_instructions.append(
                    INSTR_PRODUCT_FOUND.format(product_name=result.product_name)
                )

                status_text = (
                    STATUS_INSTOCK
                    if result.availability_status == "instock"
                    else STATUS_OUT_OF_STOCK
                )
                product_facts.append(
                    f"Data: Product '{result.product_name}', {result.woo_price} UAH. Conditions: {status_text}.\n"
                    f"CRITICAL: If 'In stock' - 1-3 days. 'Under order' - 14-20 days. DO NOT PUT LINKS IN TEXT!"
                )
                if result.attributes:
                    attr_str = "\n".join(f"- {k}: {v}" for k, v in result.attributes.items())
                    product_facts.append(f"Characteristics:\n{attr_str}")
                if result.short_description:
                    product_facts.append(f"Description:\n{result.short_description}")
            else:
                logger.info(
                    "Product not found by price_comparator, falling back to search cascade",
                    product=product_name,
                )
                new_intent_type = INTENT_SEARCH

        return requires_lead, new_intent_type

    async def _handle_search_intent(
        self,
        intent_data: dict[str, Any],
        category_id: int | None,
        system_instructions: list[str],
        product_facts: list[str],
        extracted_links: list[dict[str, str]],
    ) -> bool:
        """
        Executes a cascading search (strict -> broad -> category).
        Returns requires_lead boolean.
        """
        requires_lead = False
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
            search_facts.append(SEARCH_FOUND_HEADER)
            for product in woo_products:
                status = (
                    STATUS_INSTOCK if product.stock_status == "instock" else STATUS_OUT_OF_STOCK
                )
                search_facts.append(
                    f"- Name: {product.name}\n  Price: {product.price_uah} UAH\n  Status: {status}"
                )

                if product.attributes:
                    top_attrs = list(product.attributes.items())[:5]
                    attr_str = "\n".join(f"    * {k}: {v}" for k, v in top_attrs)
                    search_facts.append(f"  Characteristics:\n{attr_str}")

                if product.url:
                    extracted_links.append({"text": product.name, "url": product.url})

            search_facts.append(INSTR_NO_DUPLICATE_LINKS)
            product_facts.append("\n".join(search_facts))

            if is_fallback_category:
                system_instructions.append(INSTR_FALLBACK_CATEGORY)
            elif is_fallback_broad:
                system_instructions.append(
                    f"The backend performed an extended search for the query '{broad_term}'. "
                    f"Adapt the response: if the client looked for a SPECIFIC model ('{strict_term}'), politely say it is missing, but there are alternatives. If general, just present."
                )
        else:
            requires_lead = True
            system_instructions.append(INSTR_NOTHING_FOUND)

        return requires_lead

    async def _get_intent_context(
        self, intent_data: dict[str, Any], history: list[dict[str, str]]
    ) -> tuple[list[str], list[str], list[dict[str, str]], bool]:
        """
        Orchestrates intent handlers and builds the contextual facts and system instructions.
        """
        system_instructions: list[str] = []
        product_facts: list[str] = []
        extracted_links: list[dict[str, str]] = []
        requires_lead: bool = False

        intent_type = intent_data.get("intent", INTENT_FAQ)
        product_name = intent_data.get("product_name")

        # Context recovery from history
        if (not product_name or product_name == "FOUND_NAME_FROM_HISTORY") and intent_type in [
            INTENT_PRODUCT,
            INTENT_CHECKOUT,
        ]:
            for msg in reversed(history):
                content = msg.get("content", "")
                if msg.get("role") == "bot" and "Товар" in content:
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

        if intent_type in [INTENT_PRODUCT, INTENT_HYBRID, INTENT_CHECKOUT] and product_name:
            req_lead, new_intent = await self._handle_product_checkout_intent(
                intent_type,
                str(product_name),
                category_id,
                system_instructions,
                product_facts,
                extracted_links,
            )
            requires_lead = req_lead
            intent_type = new_intent
            if intent_type == INTENT_SEARCH:
                intent_data["strict_query"] = str(product_name)
                intent_data["broad_query"] = str(product_name)

        if intent_type == INTENT_SEARCH:
            requires_lead = await self._handle_search_intent(
                intent_data, category_id, system_instructions, product_facts, extracted_links
            )

        return product_facts, system_instructions, extracted_links, requires_lead

    async def _prepare_rag_pipeline(
        self, question: str, session_id: str, client_ip: str | None
    ) -> tuple[bool, Any, list[str], list[str], list[dict[str, str]], bool, str]:
        """
        Executes the shared pipeline for both sync and stream methods.
        Returns:
            is_valid, fallback_response, final_context, sources, links, requires_lead, extended_message
        """
        if not self.guardrails_service.validate_input(question, client_ip=client_ip):
            return False, MSG_GUARDRAIL_FAILED, [], [], [], False, ""

        cleaned_query = re.sub(REGEX_CLEAN_QUERY, "", question)
        phone_match = re.search(REGEX_PHONE, cleaned_query)
        if phone_match:
            phone_number = phone_match.group(0)
            logger.info("Direct lead captured", session_id=session_id)
            try:
                lead = LeadData(phone=phone_number)
                lead_success = await self.telegram_service.send_lead(
                    lead, context_info=f"User query: '{question}'. Session: {session_id}"
                )
                msg = MSG_LEAD_SUCCESS if lead_success else MSG_LEAD_FAILED
                await self.chat_memory_service.add_interaction(session_id, question, msg)

                links = [
                    {"text": LINK_TELEGRAM, "url": self.settings.telegram_contact_url},
                    {"text": LINK_VIBER, "url": self.settings.viber_contact_url},
                ]
                return False, msg, [], [], links, False, ""
            except Exception:
                logger.exception("Lead capture validation failed")

        history = await self.chat_memory_service.get_history(session_id, limit=6)
        history_context = "\n".join(
            [
                f"{'Client' if m.get('role') == 'user' else 'You'}: {m.get('content', '')}"
                for m in history
            ]
        )

        intent_data = await self.detect_intent(question, history_context)
        intent_type = intent_data.get("intent", INTENT_FAQ)

        if intent_type in [INTENT_PRODUCT, INTENT_SEARCH, INTENT_CHECKOUT]:
            intent_data["normalized_faq_queries"] = []

        if intent_type == INTENT_SEARCH:
            await self.chat_memory_service.clear_history(session_id)
            history_context = ""
            history = []

        raw_queries = intent_data.get("normalized_faq_queries", [])
        valid_queries: list[str] = []
        if isinstance(raw_queries, str):
            valid_queries = [raw_queries]
        elif isinstance(raw_queries, list):
            for q in cast(list[Any], raw_queries):
                if isinstance(q, str) and q.strip():
                    valid_queries.append(q.strip())

        context_chunks: list[str] = []
        sources: set[str] = set()

        if valid_queries:
            tasks = [self._retrieve_context(nq) for nq in valid_queries]
            if tasks:
                results = await asyncio.gather(*tasks)
                for c_chunks, c_sources, _ in results:
                    context_chunks.extend(c_chunks)
                    sources.update(c_sources)

        (
            product_facts,
            system_instructions,
            extracted_links,
            requires_lead,
        ) = await self._get_intent_context(intent_data, history)

        prepended_context: list[str] = []
        if system_instructions:
            prepended_context.append("\n".join(system_instructions))
        if product_facts:
            prepended_context.append("\n".join(product_facts))

        final_context = prepended_context + context_chunks

        extended_user_message = f"[CHAT HISTORY]\n{history_context if history_context else 'This is the first message.'}\n\n[CURRENT CLIENT QUERY]\n{question}"

        return (
            True,
            None,
            final_context,
            list(sources),
            extracted_links,
            requires_lead,
            extended_user_message,
        )

    async def process_query(
        self, question: str, session_id: str = "default", client_ip: str | None = None
    ) -> RAGResponse:
        """
        Processes a user query synchronously and returns a complete RAGResponse.
        """
        (
            is_valid,
            fallback_msg,
            final_context,
            sources,
            extracted_links,
            requires_lead,
            extended_user_message,
        ) = await self._prepare_rag_pipeline(question, session_id, client_ip)

        if not is_valid:
            if fallback_msg == MSG_GUARDRAIL_FAILED:
                return RAGResponse(
                    answer=fallback_msg,
                    sources=[],
                    has_context=False,
                    links=[],
                    requires_lead=False,
                )
            else:
                return RAGResponse(
                    answer=str(fallback_msg),
                    sources=[],
                    has_context=False,
                    links=[LinkItem(**link) for link in extracted_links],
                    requires_lead=False,
                )

        if not final_context:
            logger.info("RAG Engine fallback: no context", threshold=self.threshold)
            return RAGResponse(
                answer=NO_CONTEXT_RESPONSE,
                sources=[],
                has_context=False,
                links=[],
                requires_lead=True,
            )

        answer = await self.openai_service.get_chat_completion(
            system_prompt=RAG_SYSTEM_PROMPT,
            user_message=extended_user_message.strip(),
            context_chunks=final_context,
        )

        await self.chat_memory_service.add_interaction(session_id, question, answer)

        logger.info("RAG sync query processed", sources_count=len(sources))
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
        """
        Processes a user query asynchronously and yields a stream of tokens.
        """
        (
            is_valid,
            fallback_msg,
            final_context,
            _,
            extracted_links,
            requires_lead,
            extended_user_message,
        ) = await self._prepare_rag_pipeline(question, session_id, client_ip)

        if not is_valid:
            meta_payload = json.dumps(
                {"links": extracted_links, "requires_lead": False}, ensure_ascii=False
            )
            yield f"[METADATA] {meta_payload}"
            yield json.dumps({"token": fallback_msg}, ensure_ascii=False)
            return

        meta_payload = json.dumps(
            {"links": extracted_links, "requires_lead": requires_lead}, ensure_ascii=False
        )
        yield f"[METADATA] {meta_payload}"

        response_tokens: list[str] = []
        stream: AsyncGenerator[str] | None = None
        full_response = ""
        try:
            stream = self.openai_service.stream_chat_completion(
                system_prompt=RAG_SYSTEM_PROMPT,
                user_message=extended_user_message.strip(),
                context_chunks=final_context,
            )

            async for token in stream:
                response_tokens.append(token)
                yield json.dumps({"token": token}, ensure_ascii=False)

            full_response = "".join(response_tokens)
        except Exception:
            logger.exception("OpenAI Stream failed")
            yield json.dumps({"token": MSG_STREAM_FAILED}, ensure_ascii=False)
            full_response = "".join(response_tokens) + MSG_STREAM_FAILED

            # Since we hit an error, we should close the async generator if it supports it
            if stream and hasattr(stream, "aclose"):
                await stream.aclose()
        finally:
            await self.chat_memory_service.add_interaction(session_id, question, full_response)
