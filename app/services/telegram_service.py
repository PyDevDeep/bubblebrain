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
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.base_url = (
            f"https://api.telegram.org/bot{self.token}/sendMessage" if self.token else None
        )

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

    async def send_alert(
        self,
        message: str,
        alert_type: str = "general",
        retries: int = 3,
        reply_markup: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> bool:
        if not self.base_url or not self.chat_id:
            logger.warning("Telegram credentials missing, alert not sent.")
            return False

        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        topic_id = self.topics.get(alert_type) or self.fallback_topic
        if topic_id:
            payload["message_thread_id"] = topic_id

        alert_success = False
        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(retries):
                try:
                    resp = await client.post(
                        self.base_url,
                        json=payload,
                    )
                    if resp.status_code == 200:
                        alert_success = True
                        break
                    else:
                        logger.error(
                            f"Failed to send TG alert (Attempt {attempt + 1}/{retries})",
                            response=resp.text,
                        )
                except Exception as e:
                    logger.error(
                        f"Error sending TG alert (Attempt {attempt + 1}/{retries})", error=str(e)
                    )

                if attempt < retries - 1:
                    await asyncio.sleep(1)

        if alert_success and session_id:
            from app.services.chat_memory_service import ChatMemoryService

            chat_memory_service = ChatMemoryService()
            history = await chat_memory_service.get_history(session_id, limit=100)
            if history:
                history_lines = [f"{msg['role'].upper()}: {msg['content']}" for msg in history]
                history_text = "\n\n".join(history_lines)
                doc_name = f"chat_history_{session_id}.txt"
                caption = CHAT_HISTORY_CAPTION.format(session_id=session_id)
                await self.send_document(doc_name, history_text, caption, alert_type)

        return alert_success

    async def send_lead(
        self, lead: LeadData, context_info: str = DEFAULT_LEAD_CONTEXT, retries: int = 3
    ) -> bool:
        """Відправка валідованого ліда менеджеру."""
        if not self.base_url or not self.chat_id:
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

        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(retries):
                try:
                    resp = await client.post(
                        self.base_url,
                        json=payload,
                    )
                    if resp.status_code == 200:
                        logger.info("Lead successfully sent to Telegram", phone=lead.phone)
                        return True
                    else:
                        logger.error(
                            f"Failed to send TG lead (Attempt {attempt + 1}/{retries})",
                            response=resp.text,
                        )
                except Exception as e:
                    logger.error(
                        f"Error sending TG lead (Attempt {attempt + 1}/{retries})", error=str(e)
                    )
                if attempt < retries - 1:
                    await asyncio.sleep(1)

        return False

    async def update_message_reply_markup(
        self,
        message_id: int,
        reply_markup: dict[str, Any] | None = None,
        chat_id: int | str | None = None,
    ) -> bool:
        if not self.token:
            return False

        target_chat_id = chat_id or self.chat_id
        url = f"https://api.telegram.org/bot{self.token}/editMessageReplyMarkup"
        payload: dict[str, Any] = {"chat_id": target_chat_id, "message_id": message_id}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"Error updating TG message markup: {e}")
                return False

    async def edit_message_text(
        self,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        chat_id: int | str | None = None,
    ) -> bool:
        if not self.token:
            return False

        target_chat_id = chat_id or self.chat_id
        url = f"https://api.telegram.org/bot{self.token}/editMessageText"
        payload: dict[str, Any] = {
            "chat_id": target_chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"Error editing TG message: {e}")
                return False

    async def send_document(
        self,
        document_name: str,
        document_content: str,
        caption: str = "",
        alert_type: str = "general",
    ) -> bool:
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials missing, document not sent.")
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendDocument"

        data: dict[str, Any] = {"chat_id": self.chat_id, "parse_mode": "HTML"}
        if caption:
            data["caption"] = caption
        topic_id = self.topics.get(alert_type) or self.fallback_topic
        if topic_id:
            data["message_thread_id"] = topic_id

        files = {"document": (document_name, document_content.encode("utf-8"), "text/plain")}

        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(3):
                try:
                    resp = await client.post(url, data=data, files=files)
                    if resp.status_code == 200:
                        return True
                    else:
                        logger.error(
                            f"Failed to send TG document (Attempt {attempt + 1}/3)",
                            response=resp.text,
                        )
                except Exception as e:
                    logger.error(
                        f"Error sending TG document (Attempt {attempt + 1}/3)", error=str(e)
                    )
                if attempt < 2:
                    await asyncio.sleep(1)

        return False
