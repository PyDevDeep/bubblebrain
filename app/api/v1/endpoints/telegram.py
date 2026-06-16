import logging
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, status

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, commit_with_retry
from app.models.lead import Lead
from app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)

telegram_router = APIRouter()


async def answer_callback_query(callback_query_id: str, token: str, text: str = "") -> None:
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "text": text}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload)
        except Exception as e:
            logger.error(f"Failed to answer callback query: {e}")


async def process_telegram_update(update: dict[str, Any]) -> None:
    if "callback_query" not in update:
        return

    callback_query = update["callback_query"]
    callback_id = callback_query.get("id")
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    message_id = message.get("message_id")
    chat_id = message.get("chat", {}).get("id")
    original_text = message.get("text", "") or message.get("caption", "")

    settings = get_settings()
    telegram_service = TelegramService(settings)

    if callback_id and settings.telegram_bot_token:
        await answer_callback_query(callback_id, settings.telegram_bot_token)

    if data.startswith("lead_status:"):
        parts = data.split(":")
        if len(parts) == 3:
            _, lead_id_str, new_status = parts
            try:
                lead_id = int(lead_id_str)
            except ValueError:
                return

            status_map = {
                "success": "✅ Успіх (Продано)",
                "decline": "❌ Відмова",
                "in_progress": "⏳ В процесі",
            }
            status_text = status_map.get(new_status, new_status)

            # Оновлюємо БД
            async with AsyncSessionLocal() as session:
                lead = await session.get(Lead, lead_id)
                if lead:
                    lead.status = new_status  # type: ignore
                    await commit_with_retry(session)

            # Змінюємо повідомлення (прибираємо кнопки, додаємо статус в кінець тексту)
            if original_text and message_id and chat_id:
                # Оскільки Telegram повертає text без HTML тегів, краще просто додати рядок в кінець.
                # Але якщо ми втратимо форматування, це може бути проблемою.
                # Найпростіший спосіб: залишити повідомлення, але оновити ReplyMarkup на одну кнопку "Статус: ..." або прибрати кнопки.

                # Залишимо кнопку яка не клікається або оновимо текст
                new_markup = {
                    "inline_keyboard": [
                        [{"text": f"Статус: {status_text}", "callback_data": "ignore"}]
                    ]
                }
                await telegram_service.update_message_reply_markup(
                    message_id=message_id, reply_markup=new_markup, chat_id=chat_id
                )


@telegram_router.post("/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    try:
        update = await request.json()
        background_tasks.add_task(process_telegram_update, update)
    except Exception as e:
        logger.error(f"Error parsing telegram update: {e}")

    return {"status": "ok"}
