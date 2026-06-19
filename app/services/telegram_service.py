import asyncio
import html
from typing import Any

import httpx

from app.core.config import Settings
from app.core.constants import (
    CHAT_HISTORY_CAPTION,
    DEFAULT_LEAD_CONTEXT,
    DEFAULT_MISSING_VALUE,
    TELEGRAM_LEAD_TEMPLATE,
)
from app.core.logging_config import get_logger
from app.schemas.chat import LeadData

logger = get_logger(__name__)


class TelegramService:
    def __init__(self, settings: Settings) -> None:
        """Initialize TelegramService with settings."""
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.api_base = f"https://api.telegram.org/bot{self.token}" if self.token else None

        # Shared HTTP client for connection pooling
        self.client = httpx.AsyncClient(timeout=30.0)

        # Topic IDs
        self.fallback_topic = settings.telegram_topic_general
        self.topics = {
            "lead": settings.telegram_topic_leads,
            "hot_lead": settings.telegram_topic_hot_leads,
            "conversion": settings.telegram_topic_conversions,
            "stat": settings.telegram_topic_bot_stats,
            "price": settings.telegram_topic_prices,
            "error": settings.telegram_topic_errors,
        }

    async def close(self) -> None:
        """Close the shared HTTP client. Should be called on application shutdown."""
        await self.client.aclose()

    async def _make_request(
        self,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        retries: int = 3,
    ) -> httpx.Response | None:
        """
        Helper to make HTTP requests to Telegram API with retry logic.
        """
        if not self.api_base:
            return None

        url = f"{self.api_base}/{endpoint}"

        for attempt in range(retries):
            try:
                # If files are present, use data + files
                if files is not None:
                    # telegram file sending usually requires larger timeout
                    resp = await self.client.post(url, data=data, files=files, timeout=60.0)
                else:
                    resp = await self.client.post(url, json=payload)

                if resp.status_code == 200:
                    return resp
                else:
                    logger.error(
                        f"Failed TG request to {endpoint} (Attempt {attempt + 1}/{retries})",
                        response=resp.text,
                    )
            except Exception as e:
                logger.error(
                    f"Error in TG request to {endpoint} (Attempt {attempt + 1}/{retries})",
                    error=str(e),
                )

            if attempt < retries - 1:
                await asyncio.sleep(1)

        return None

    async def send_alert(
        self,
        message: str,
        alert_type: str = "general",
        retries: int = 3,
        reply_markup: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Send an alert message to a specific Telegram topic."""
        if not self.api_base or not self.chat_id:
            logger.warning("Telegram credentials missing, alert not sent.")
            return False

        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        topic_id = self.topics.get(alert_type) or self.fallback_topic
        if topic_id:
            payload["message_thread_id"] = topic_id

        resp = await self._make_request("sendMessage", payload=payload, retries=retries)
        alert_success = resp is not None

        if alert_success and history and session_id:
            history_lines = [
                f"{msg.get('role', '').upper()}: {msg.get('content', '')}" for msg in history
            ]
            history_text = "\n\n".join(history_lines)
            doc_name = f"chat_history_{session_id}.txt"
            caption = CHAT_HISTORY_CAPTION.format(session_id=session_id)
            await self.send_document(doc_name, history_text, caption, alert_type)

        return alert_success

    async def send_lead(
        self, lead: LeadData, context_info: str = DEFAULT_LEAD_CONTEXT, retries: int = 3
    ) -> bool:
        """Send a validated lead to the manager."""
        if not self.api_base or not self.chat_id:
            logger.warning("Telegram credentials missing, lead not sent.")
            return False

        safe_name = html.escape(str(lead.name)) if lead.name else DEFAULT_MISSING_VALUE
        safe_phone = html.escape(str(lead.phone)) if lead.phone else ""
        safe_context = html.escape(str(context_info)) if context_info else ""

        message = TELEGRAM_LEAD_TEMPLATE.format(
            name=safe_name, phone=safe_phone, context=safe_context
        )

        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
        topic_id = self.topics.get("lead") or self.fallback_topic
        if topic_id:
            payload["message_thread_id"] = topic_id

        resp = await self._make_request("sendMessage", payload=payload, retries=retries)
        if resp:
            logger.info("Lead successfully sent to Telegram", phone=lead.phone)
            return True
        return False

    async def update_message_reply_markup(
        self,
        message_id: int,
        reply_markup: dict[str, Any] | None = None,
        chat_id: int | str | None = None,
    ) -> bool:
        if not self.api_base:
            return False

        target_chat_id = chat_id or self.chat_id
        payload: dict[str, Any] = {"chat_id": target_chat_id, "message_id": message_id}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        resp = await self._make_request("editMessageReplyMarkup", payload=payload, retries=3)
        return resp is not None

    async def edit_message_text(
        self,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        chat_id: int | str | None = None,
    ) -> bool:
        """Edit the text of an existing message."""
        if not self.api_base:
            return False

        target_chat_id = chat_id or self.chat_id
        payload: dict[str, Any] = {
            "chat_id": target_chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        resp = await self._make_request("editMessageText", payload=payload, retries=3)
        return resp is not None

    async def send_document(
        self,
        document_name: str,
        document_content: str,
        caption: str = "",
        alert_type: str = "general",
    ) -> bool:
        """Send a document to a specific Telegram topic."""
        if not self.api_base or not self.chat_id:
            logger.warning("Telegram credentials missing, document not sent.")
            return False

        data: dict[str, Any] = {"chat_id": self.chat_id, "parse_mode": "HTML"}
        if caption:
            data["caption"] = caption

        topic_id = self.topics.get(alert_type) or self.fallback_topic
        if topic_id:
            data["message_thread_id"] = topic_id

        files = {"document": (document_name, document_content.encode("utf-8"), "text/plain")}

        resp = await self._make_request("sendDocument", data=data, files=files, retries=3)
        return resp is not None
