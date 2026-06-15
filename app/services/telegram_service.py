import asyncio
import html

import httpx

from app.core.config import Settings
from app.core.constants import DEFAULT_LEAD_CONTEXT, DEFAULT_MISSING_VALUE, TELEGRAM_LEAD_TEMPLATE
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

    async def send_alert(self, message: str, retries: int = 3) -> bool:
        if not self.base_url or not self.chat_id:
            logger.warning("Telegram credentials missing, alert not sent.")
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(retries):
                try:
                    resp = await client.post(
                        self.base_url,
                        json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                    )
                    if resp.status_code == 200:
                        return True
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

        return False

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

        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(retries):
                try:
                    resp = await client.post(
                        self.base_url,
                        json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
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
