import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, status

from app.core.config import get_settings
from app.core.constants import BTN_DECLINE, BTN_IN_PROGRESS, BTN_STATUS, BTN_SUCCESS
from app.core.db import AsyncSessionLocal, commit_with_retry
from app.models.lead import Lead
from app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)

telegram_router = APIRouter()


async def process_telegram_update(update: dict[str, Any]) -> None:
    """Process incoming Telegram update."""
    try:
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
            await telegram_service.answer_callback_query(callback_id)

        if data.startswith("lead_status:"):
            parts = data.split(":")
            if len(parts) == 3:
                _, lead_id_str, new_status = parts
                try:
                    lead_id = int(lead_id_str)
                except ValueError:
                    return

                status_map = {
                    "success": BTN_SUCCESS,
                    "decline": BTN_DECLINE,
                    "in_progress": BTN_IN_PROGRESS,
                }
                status_text = status_map.get(new_status, new_status)

                # Update DB
                async with AsyncSessionLocal() as session:
                    lead = await session.get(Lead, lead_id)
                    if lead:
                        lead.status = new_status  # type: ignore
                        await commit_with_retry(session)

                # Update message (remove buttons, add status to end of text)
                if original_text and message_id and chat_id:
                    # Since Telegram returns text without HTML tags, it's better to just append the string to the end.
                    # But if we lose formatting, it could be a problem.
                    # Simplest way: leave the message, but update ReplyMarkup to a single "Status: ..." button or remove buttons.

                    # Leave unclickable button or update text
                    new_markup = {
                        "inline_keyboard": [
                            [
                                {
                                    "text": BTN_STATUS.format(status_text=status_text),
                                    "callback_data": "ignore",
                                }
                            ]
                        ]
                    }
                    await telegram_service.update_message_reply_markup(
                        message_id=message_id, reply_markup=new_markup, chat_id=chat_id
                    )
    except Exception:
        logger.exception("Error processing telegram update")


@telegram_router.post("/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Handle Telegram webhook."""
    try:
        update = await request.json()
        background_tasks.add_task(process_telegram_update, update)
    except Exception:
        logger.exception("Error parsing telegram update")

    return {"status": "ok"}
