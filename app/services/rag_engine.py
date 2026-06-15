import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from typing import Any, cast

from app.core.config import Settings
from app.core.constants import (
    INTENT_CHECKOUT,
    INTENT_FAQ,
    INTENT_HYBRID,
    INTENT_PRODUCT,
    INTENT_SEARCH,
    LINK_TELEGRAM,
    LINK_VIBER,
    MSG_GUARDRAIL_FAILED,
    MSG_LEAD_FAILED,
    MSG_LEAD_SUCCESS,
    MSG_STREAM_FAILED,
    REGEX_CLEAN_QUERY,
    REGEX_PHONE,
    REGEX_PRODUCT_NAME_HISTORY,
)
from app.core.logging_config import get_logger
from app.schemas.chat import IntentContextResult, LeadData, LinkItem, PipelineContext, RAGResponse
from app.services.category_manager import CategoryManager
from app.services.chat_memory_service import ChatMemoryService
from app.services.guardrails_service import GuardrailsService
from app.services.intent_handlers import ProductCheckoutIntentHandler, SearchIntentHandler
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
        self.product_intent_handler = ProductCheckoutIntentHandler(
            price_comparator=price_comparator, telegram_service=telegram_service, settings=settings
        )
        self.search_intent_handler = SearchIntentHandler(price_comparator=price_comparator)

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
        results = await asyncio.to_thread(
            self.vector_service.query_similar,
            query_vector=query_vector,
            top_k=self.top_k,
            score_threshold=self.threshold,
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

    async def _get_intent_context(
        self, intent_data: dict[str, Any], history: list[dict[str, str]]
    ) -> IntentContextResult:
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
                    match = re.search(REGEX_PRODUCT_NAME_HISTORY, content)
                    if match:
                        product_name = match.group(1)
                        logger.info(
                            "Recovered product name from bot history",
                            extra={"product_name": product_name},
                        )
                        break

        category_term = str(intent_data.get("category_query") or "").strip()
        category_id = (
            self.category_manager.get_category_id(category_term) if category_term else None
        )

        if intent_type in [INTENT_PRODUCT, INTENT_HYBRID, INTENT_CHECKOUT] and product_name:
            res = await self.product_intent_handler.handle(
                intent_type=intent_type,
                product_name=str(product_name),
                category_id=category_id,
                system_instructions=system_instructions,
                product_facts=product_facts,
                extracted_links=extracted_links,
            )
            product_facts = res.product_facts
            system_instructions = res.system_instructions
            extracted_links = res.extracted_links
            requires_lead = res.requires_lead
            intent_type = res.new_intent_type or intent_type

            if intent_type == INTENT_SEARCH:
                intent_data["strict_query"] = str(product_name)
                intent_data["broad_query"] = str(product_name)

        if intent_type == INTENT_SEARCH:
            res = await self.search_intent_handler.handle(
                intent_data=intent_data,
                category_id=category_id,
                system_instructions=system_instructions,
                product_facts=product_facts,
                extracted_links=extracted_links,
            )
            product_facts = res.product_facts
            system_instructions = res.system_instructions
            extracted_links = res.extracted_links
            requires_lead = res.requires_lead

        return IntentContextResult(
            product_facts=product_facts,
            system_instructions=system_instructions,
            extracted_links=extracted_links,
            requires_lead=requires_lead,
        )

    async def _prepare_rag_pipeline(
        self, question: str, session_id: str, client_ip: str | None
    ) -> PipelineContext:
        """
        Executes the shared pipeline for both sync and stream methods.
        Returns:
            is_valid, fallback_response, final_context, sources, links, requires_lead, extended_message
        """
        if not self.guardrails_service.validate_input(question, client_ip=client_ip):
            return PipelineContext(
                is_valid=False,
                fallback_response=MSG_GUARDRAIL_FAILED,
                final_context=[],
                sources=[],
                extracted_links=[],
                requires_lead=False,
                extended_user_message="",
            )

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
                return PipelineContext(
                    is_valid=False,
                    fallback_response=msg,
                    final_context=[],
                    sources=[],
                    extracted_links=links,
                    requires_lead=False,
                    extended_user_message="",
                )
            except Exception:
                logger.exception("Lead capture validation failed")
                return PipelineContext(
                    is_valid=False,
                    fallback_response=MSG_LEAD_FAILED,
                    final_context=[],
                    sources=[],
                    extracted_links=[],
                    requires_lead=False,
                    extended_user_message="",
                )

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

        vector_tasks = []
        if valid_queries:
            vector_tasks = [self._retrieve_context(nq) for nq in valid_queries]

        async def fetch_vectors() -> list[
            tuple[list[str], set[str], dict[str, float]] | BaseException
        ]:
            if not vector_tasks:
                return []
            return await asyncio.gather(*vector_tasks, return_exceptions=True)

        vector_results, intent_results = await asyncio.gather(
            fetch_vectors(), self._get_intent_context(intent_data, history), return_exceptions=True
        )

        if not isinstance(vector_results, BaseException):
            for res in vector_results:
                if isinstance(res, BaseException):
                    logger.warning(f"Vector retrieval failed: {res}")
                    continue
                # res is now safely inferred as tuple[list[str], set[str], dict[str, float]]
                c_chunks = res[0]
                c_sources = res[1]
                context_chunks.extend(c_chunks)
                sources.update(c_sources)

        if isinstance(intent_results, BaseException):
            logger.error(f"Intent context retrieval failed: {intent_results}")
            product_facts, system_instructions, extracted_links, requires_lead = [], [], [], False
        else:
            product_facts = intent_results.product_facts
            system_instructions = intent_results.system_instructions
            extracted_links = intent_results.extracted_links
            requires_lead = intent_results.requires_lead

        prepended_context: list[str] = []
        if system_instructions:
            prepended_context.append("\n".join(system_instructions))
        if product_facts:
            prepended_context.append("\n".join(product_facts))

        final_context = prepended_context + context_chunks

        extended_user_message = f"[CHAT HISTORY]\n{history_context if history_context else 'This is the first message.'}\n\n[CURRENT CLIENT QUERY]\n{question}"

        return PipelineContext(
            is_valid=True,
            fallback_response=None,
            final_context=final_context,
            sources=list(sources),
            extracted_links=extracted_links,
            requires_lead=requires_lead,
            extended_user_message=extended_user_message,
        )

    async def process_query(
        self, question: str, session_id: str = "default", client_ip: str | None = None
    ) -> RAGResponse:
        """
        Processes a user query synchronously and returns a complete RAGResponse.
        """
        ctx = await self._prepare_rag_pipeline(question, session_id, client_ip)

        if not ctx.is_valid:
            if ctx.fallback_response == MSG_GUARDRAIL_FAILED:
                return RAGResponse(
                    answer=ctx.fallback_response,
                    sources=[],
                    has_context=False,
                    links=[],
                    requires_lead=False,
                )
            else:
                return RAGResponse(
                    answer=str(ctx.fallback_response),
                    sources=[],
                    has_context=False,
                    links=[LinkItem(**link) for link in ctx.extracted_links],
                    requires_lead=False,
                )

        if not ctx.final_context:
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
            user_message=ctx.extended_user_message.strip(),
            context_chunks=ctx.final_context,
        )

        await self.chat_memory_service.add_interaction(session_id, question, answer)

        logger.info("RAG sync query processed", sources_count=len(ctx.sources))
        return RAGResponse.model_validate(
            {
                "answer": answer,
                "sources": ctx.sources,
                "has_context": True,
                "links": ctx.extracted_links,
                "requires_lead": ctx.requires_lead,
            }
        )

    async def process_query_stream(
        self, question: str, session_id: str = "default", client_ip: str | None = None
    ) -> AsyncGenerator[str]:
        """
        Processes a user query asynchronously and yields a stream of tokens.
        """
        ctx = await self._prepare_rag_pipeline(question, session_id, client_ip)

        if not ctx.is_valid:
            meta_payload = json.dumps(
                {"links": ctx.extracted_links, "requires_lead": False}, ensure_ascii=False
            )
            yield f"[METADATA] {meta_payload}"
            yield json.dumps({"token": ctx.fallback_response}, ensure_ascii=False)
            return

        meta_payload = json.dumps(
            {"links": ctx.extracted_links, "requires_lead": ctx.requires_lead}, ensure_ascii=False
        )
        yield f"[METADATA] {meta_payload}"

        response_tokens: list[str] = []
        stream: AsyncGenerator[str] | None = None
        full_response = ""
        try:
            stream = self.openai_service.stream_chat_completion(
                system_prompt=RAG_SYSTEM_PROMPT,
                user_message=ctx.extended_user_message.strip(),
                context_chunks=ctx.final_context,
            )

            async for token in stream:
                response_tokens.append(token)
                yield json.dumps({"token": token}, ensure_ascii=False)

            full_response = "".join(response_tokens)
        except Exception:
            logger.exception("OpenAI Stream failed")
            yield json.dumps({"token": MSG_STREAM_FAILED}, ensure_ascii=False)
            full_response = "".join(response_tokens) + MSG_STREAM_FAILED
        finally:
            bg_tasks: set[asyncio.Task[Any]] = getattr(self, "_bg_tasks", set())
            if not hasattr(self, "_bg_tasks"):
                self._bg_tasks = bg_tasks

            if stream and hasattr(stream, "aclose"):
                t1 = asyncio.create_task(stream.aclose())
                bg_tasks.add(t1)
                t1.add_done_callback(bg_tasks.discard)

            t2 = asyncio.create_task(
                self.chat_memory_service.add_interaction(session_id, question, full_response)
            )
            bg_tasks.add(t2)
            t2.add_done_callback(bg_tasks.discard)
