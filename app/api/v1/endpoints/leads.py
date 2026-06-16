from typing import Any

import httpx
import sentry_sdk
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, commit_with_retry
from app.middleware.rate_limiter import limiter
from app.models.lead import Lead
from app.schemas.lead import ContactFormLead
from app.services.telegram_service import TelegramService

leads_router = APIRouter()

MAX_PAYLOAD_SIZE = 2048


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.RequestError),
)
async def send_telegram_notification(
    lead_id: int, message: str, alert_type: str, reply_markup: dict[str, Any] | None = None
) -> None:
    settings = get_settings()
    telegram_service = TelegramService(settings)
    await telegram_service.send_alert(message, alert_type=alert_type, reply_markup=reply_markup)


async def process_lead_background(lead_id: int, message: str, alert_type: str = "lead") -> None:
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Успіх (Продано)", "callback_data": f"lead_status:{lead_id}:success"},
                {"text": "❌ Відмова", "callback_data": f"lead_status:{lead_id}:decline"},
            ],
            [{"text": "⏳ В процесі", "callback_data": f"lead_status:{lead_id}:in_progress"}],
        ]
    }
    async with AsyncSessionLocal() as session:
        try:
            await send_telegram_notification(
                lead_id, message, alert_type, reply_markup=reply_markup
            )
            # Оновлюємо статус на sent
            lead = await session.get(Lead, lead_id)
            if lead:
                lead.notification_status = "sent"  # type: ignore
                await commit_with_retry(session)
        except RetryError:
            # Якщо всі спроби вичерпано
            sentry_sdk.capture_message(f"Telegram API failed for lead_id={lead_id}", level="error")
            lead = await session.get(Lead, lead_id)
            if lead:
                lead.notification_status = "failed"  # type: ignore
                await commit_with_retry(session)
        except Exception as e:
            sentry_sdk.capture_message(
                f"Unexpected error for lead_id={lead_id}: {e}", level="error"
            )
            lead = await session.get(Lead, lead_id)
            if lead:
                lead.notification_status = "failed"  # type: ignore
                await commit_with_retry(session)


@leads_router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")  # type: ignore
async def create_lead(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_PAYLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload Too Large"
        )

    body_bytes = b""
    async for chunk in request.stream():
        body_bytes += chunk
        if len(body_bytes) > MAX_PAYLOAD_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload Too Large"
            )

    try:
        lead_data = ContactFormLead.model_validate_json(body_bytes)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid JSON format or validation error",
        ) from None

    # Honeypot перевірка
    if lead_data.honeypot:
        return {"status": "success", "message": "Lead received"}

    # Асинхронний запис у БД
    async with AsyncSessionLocal() as session:
        db_lead = Lead(
            name=lead_data.name,
            surname=lead_data.surname,
            phone_number=lead_data.phone_number,
            contact_method=lead_data.contact_method,
            lead_type=lead_data.lead_type,
            delivery_address=lead_data.delivery_address,
            notification_status="pending",
            session_id=lead_data.session_id,
        )
        session.add(db_lead)
        await commit_with_retry(session)
        await session.refresh(db_lead)
        lead_id = int(db_lead.id)  # type: ignore

    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Kyiv")
    now_str = datetime.now(tz).strftime("%d.%m.%Y %H:%M")
    client_ip = request.client.host if request.client else "Unknown"

    if lead_data.lead_type == "checkout":
        message = (
            f"🛒 <b>Нове ЗАМОВЛЕННЯ з Бота (Hot Lead) {lead_id}</b>\n"
            f"📅 <b>Дата:</b> {now_str}\n\n"
            f"👨 <b>Ім'я:</b> {lead_data.name} {lead_data.surname or ''}\n"
            f"📞 <b>Телефон:</b> <code>{lead_data.phone_number}</code>\n"
            f"📱 <b>Спосіб зв'язку:</b> {lead_data.contact_method}\n"
            f"🚛 <b>Адреса доставки:</b> {lead_data.delivery_address or 'Не вказана'}\n\n"
            f"🥷 <b>IP:</b> {client_ip}\n\n"
            f"#HOT_LEAD #ID{lead_id}"
        )
        background_tasks.add_task(process_lead_background, lead_id, message, "hot_lead")
    else:
        message = (
            f"🔥 <b>НОВИЙ ЛІД З БОТА {lead_id}</b>\n"
            f"📅 <b>Дата:</b> {now_str}\n\n"
            f"👨 <b>Ім'я:</b> {lead_data.name}\n"
            f"📞 <b>Телефон:</b> <code>{lead_data.phone_number}</code>\n"
            f"📱 <b>Спосіб зв'язку:</b> {lead_data.contact_method}\n\n"
            f"🥷 <b>IP:</b> {client_ip}\n\n"
            f"#БОТ_ЛІД #ID{lead_id}"
        )
        background_tasks.add_task(process_lead_background, lead_id, message, "lead")

    return {"status": "success", "message": "Lead received"}
