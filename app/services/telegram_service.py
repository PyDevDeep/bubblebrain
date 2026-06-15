import html

import httpx

from app.core.config import Settings
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

    async def send_alert(self, message: str) -> None:
        if not self.base_url or not self.chat_id:
            logger.warning("Telegram credentials missing, alert not sent.")
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.base_url,
                    json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                )
                if resp.status_code != 200:
                    logger.error("Failed to send TG alert", response=resp.text)
        except Exception as e:
            logger.error("Error sending TG alert", error=str(e))

    async def send_lead(self, lead: LeadData, context_info: str = "Запит з чату") -> None:
        """Відправка валідованого ліда менеджеру."""
        if not self.base_url or not self.chat_id:
            logger.warning("Telegram credentials missing, lead not sent.")
            return

        safe_name = html.escape(str(lead.name)) if lead.name else "Не вказано"
        safe_phone = html.escape(str(lead.phone)) if lead.phone else ""
        safe_context = html.escape(str(context_info)) if context_info else ""

        message = (
            f"🚨 <b>Новий лід від бота!</b>\n\n"
            f"👤 <b>Ім'я:</b> {safe_name}\n"
            f"📞 <b>Телефон:</b> <code>{safe_phone}</code>\n"
            f"💬 <b>Контекст:</b> {safe_context}"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.base_url,
                    json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                )
                if resp.status_code != 200:
                    logger.error("Failed to send TG lead", response=resp.text)
                else:
                    logger.info("Lead successfully sent to Telegram", phone=lead.phone)
        except Exception as e:
            logger.error("Error sending TG lead", error=str(e))
