import re
from typing import Any
from urllib.parse import urlparse, urlunparse

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
from app.core.constants import (
    ALERT_BOT_LEAD,
    ALERT_HOT_LEAD,
    BTN_DECLINE,
    BTN_IN_PROGRESS,
    BTN_PRODUCT_LINK,
    BTN_SUCCESS,
    MAX_PAYLOAD_SIZE,
)
from app.core.db import AsyncSessionLocal, commit_with_retry
from app.core.metrics import leads_created_total
from app.middleware.rate_limiter import limiter
from app.models.lead import Lead
from app.schemas.lead import ContactFormLead
from app.services.chat_memory_service import ChatMemoryService
from app.services.telegram_service import TelegramService

leads_router = APIRouter()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.RequestError),
)
async def send_telegram_notification(
    lead_id: int,
    message: str,
    alert_type: str,
    reply_markup: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> None:
    """Send notification to Telegram with retry mechanism."""
    settings = get_settings()
    telegram_service = TelegramService(settings)
    await telegram_service.send_alert(
        message, alert_type=alert_type, reply_markup=reply_markup, session_id=session_id
    )


async def process_lead_background(
    lead_id: int, message: str, alert_type: str = "lead", session_id: str | None = None
) -> None:
    """Process lead in background and send Telegram notification."""
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": BTN_SUCCESS, "callback_data": f"lead_status:{lead_id}:success"},
                {"text": BTN_DECLINE, "callback_data": f"lead_status:{lead_id}:decline"},
            ],
            [{"text": BTN_IN_PROGRESS, "callback_data": f"lead_status:{lead_id}:in_progress"}],
        ]
    }
    async with AsyncSessionLocal() as session:
        try:
            if session_id:
                chat_memory_service = ChatMemoryService()
                history = await chat_memory_service.get_history(session_id, limit=10)
                if history:
                    bot_msgs = [m["content"] for m in history if m["role"] == "bot"]
                    product_url = None
                    if bot_msgs:
                        for msg in reversed(bot_msgs):
                            match = re.search(r"<!-- link:\s*(.*?)\s*-->", msg)
                            if match:
                                raw_url = match.group(1)
                                parsed = urlparse(raw_url)
                                product_url = urlunparse(
                                    (
                                        parsed.scheme,
                                        parsed.netloc,
                                        parsed.path,
                                        parsed.params,
                                        "",
                                        parsed.fragment,
                                    )
                                )
                                break

                    if product_url:
                        reply_markup["inline_keyboard"].insert(
                            0, [{"text": BTN_PRODUCT_LINK, "url": product_url}]
                        )

            await send_telegram_notification(
                lead_id, message, alert_type, reply_markup=reply_markup, session_id=session_id
            )

            # Update status to sent
            lead = await session.get(Lead, lead_id)
            if lead:
                lead.notification_status = "sent"  # type: ignore
                await commit_with_retry(session)
        except RetryError:
            # If all attempts are exhausted
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
    """Create a new lead from contact form or checkout."""
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

    # Honeypot check
    if lead_data.honeypot:
        return {"status": "success", "message": "Lead received"}

    # Asynchronous write to DB
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
        message = ALERT_HOT_LEAD.format(
            lead_id=lead_id,
            now_str=now_str,
            name=lead_data.name,
            surname=lead_data.surname or "",
            phone=lead_data.phone_number,
            method=lead_data.contact_method,
            address=lead_data.delivery_address or "Не вказана",
            ip=client_ip,
        )
        leads_created_total.labels(type="checkout", status="success").inc()
        background_tasks.add_task(
            process_lead_background, lead_id, message, "hot_lead", lead_data.session_id
        )
    else:
        message = ALERT_BOT_LEAD.format(
            lead_id=lead_id,
            now_str=now_str,
            name=lead_data.name,
            phone=lead_data.phone_number,
            method=lead_data.contact_method,
            ip=client_ip,
        )
        leads_created_total.labels(type="contact", status="success").inc()
        background_tasks.add_task(
            process_lead_background, lead_id, message, "lead", lead_data.session_id
        )

    return {"status": "success", "message": "Lead received"}
