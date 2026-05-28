import httpx

from app.core.config import Settings
from app.core.logging_config import get_logger

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
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.base_url,
                    json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                )
                if resp.status_code != 200:
                    logger.error("Failed to send TG alert", response=resp.text)
        except Exception as e:
            logger.error("Error sending TG alert", error=str(e))
