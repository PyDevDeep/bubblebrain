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
                resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error sending TG alert", error=str(e))
            raise
        except httpx.RequestError as e:
            logger.error("Network error sending TG alert", error=str(e))
            raise

    async def send_lead(self, lead: LeadData, context_info: str = "Запит з чату") -> None:
        """Відправка валідованого ліда менеджеру."""
        if not self.base_url or not self.chat_id:
            logger.warning("Telegram credentials missing, lead not sent.")
            return

        message = (
            f"🚨 <b>Новий лід від бота!</b>\n\n"
            f"👤 <b>Ім'я:</b> {lead.name or 'Не вказано'}\n"
            f"📞 <b>Телефон:</b> <code>{lead.phone}</code>\n"
            f"💬 <b>Контекст:</b> {context_info}"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.base_url,
                    json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                )
                resp.raise_for_status()
                logger.info("Lead successfully sent to Telegram", phone=lead.phone)
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error sending TG lead", error=str(e))
            raise
        except httpx.RequestError as e:
            logger.error("Network error sending TG lead", error=str(e))
            raise
