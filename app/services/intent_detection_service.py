import json
import logging
import re
from typing import Any

from app.core.constants import (
    INTENT_CHECKOUT,
    INTENT_CONTACT,
    INTENT_FAQ,
    INTENT_GENERAL,
    INTENT_HYBRID,
    INTENT_ORDER_STATUS,
    INTENT_PRODUCT,
    INTENT_SEARCH,
)
from app.schemas.chat import IntentDetectionResult
from app.services.category_manager import CategoryManager
from app.services.openai_service import OpenAIService
from app.utils.prompts import INTENT_ANALYZER_PROMPT

logger = logging.getLogger(__name__)


class IntentDetectionService:
    """Service responsible for parsing user queries and detecting intent."""

    def __init__(self, openai_service: OpenAIService, category_manager: CategoryManager) -> None:
        self.openai_service = openai_service
        self.category_manager = category_manager

    async def detect_intent(
        self, question: str, history_context: str, session_state_json: str
    ) -> dict[str, Any]:
        """Detects user intent using regex and LLM."""
        stripped_q = question.strip()

        # Regex checks for product codes
        sku_match = re.search(r"\b\d{6}\b", stripped_q)
        pn_match = re.search(
            r"\b(?=[a-zA-Z0-9\-\.]*[a-zA-Z])(?=[a-zA-Z0-9\-\.]*\d)[a-zA-Z0-9\-\.]{5,25}\b",
            stripped_q,
        )

        extracted_code = None
        if sku_match:
            extracted_code = sku_match.group(0)
        elif pn_match:
            extracted_code = pn_match.group(0)

        faq_triggers = [
            "доставка",
            "оплата",
            "гаранті",
            "купити",
            "замовити",
            "наявн",
            "скільки",
            "як ",
        ]
        needs_llm = any(trigger in stripped_q.lower() for trigger in faq_triggers)

        # Fast-path for pure part numbers/SKUs
        if extracted_code and not needs_llm and len(stripped_q) < 100:
            return {
                "intent": INTENT_SEARCH,
                "product_name": None,
                "strict_query": extracted_code,
                "broad_query": stripped_q,
                "category_query": None,
                "normalized_faq_queries": [],
            }

        # Fast-path for pure checkout intents
        checkout_triggers = [
            "хочу замовити",
            "замовити",
            "оформити замовлення",
            "беру",
            "купую",
            "оформити",
            "хочу купити",
        ]
        if stripped_q.lower() in checkout_triggers:
            return {
                "intent": INTENT_CHECKOUT,
                "product_name": None,  # Will be filled by rag_engine session_state fallback
                "strict_query": None,
                "broad_query": None,
                "category_query": None,
                "normalized_faq_queries": [],
            }

        categories_str = await self.category_manager.get_categories_string()

        prompt = INTENT_ANALYZER_PROMPT.format(
            history_context=history_context if history_context else "None",
            session_state_json=session_state_json,
            question=question,
            categories_str=categories_str,
            intent_product=INTENT_PRODUCT,
            intent_search=INTENT_SEARCH,
            intent_checkout=INTENT_CHECKOUT,
            intent_hybrid=INTENT_HYBRID,
            intent_general=INTENT_GENERAL,
            intent_contact=INTENT_CONTACT,
            intent_order_status=INTENT_ORDER_STATUS,
        )

        try:
            response = await self.openai_service.get_chat_completion(
                system_prompt="You are a system JSON analyzer. Ensure you respond with valid JSON.",
                user_message=prompt,
                context_chunks=[],
                response_format={"type": "json_object"},
            )
            cleaned = response.replace("```json", "").replace("```", "").strip()
            parsed_json = IntentDetectionResult.model_validate_json(cleaned).model_dump()

            # Fallback override
            if extracted_code and parsed_json.get("intent") in (INTENT_GENERAL, INTENT_FAQ):
                parsed_json["intent"] = INTENT_SEARCH
                parsed_json["strict_query"] = extracted_code
                parsed_json["broad_query"] = stripped_q

            return parsed_json
        except json.JSONDecodeError:
            logger.exception("Intent detection JSON parsing failed")
            return {"intent": INTENT_FAQ, "normalized_faq_queries": [question]}
        except Exception:
            logger.exception("Intent detection generic error")
            return {"intent": INTENT_FAQ, "normalized_faq_queries": [question]}
