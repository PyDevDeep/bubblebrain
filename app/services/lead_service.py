import re
from datetime import datetime
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo

import sentry_sdk
from tenacity import RetryError

from app.core.constants import (
    ALERT_BOT_LEAD,
    ALERT_HOT_LEAD,
    ALERT_WOO_ORDER,
    BTN_DECLINE,
    BTN_IN_PROGRESS,
    BTN_PRODUCT_LINK,
    BTN_SUCCESS,
)
from app.core.db import AsyncSessionLocal, commit_with_retry
from app.core.logging_config import get_logger
from app.core.metrics import leads_created_total
from app.models.lead import Lead
from app.schemas.lead import ContactFormLead
from app.schemas.order import WooOrderPayload
from app.services.chat_memory_service import ChatMemoryService
from app.services.telegram_service import TelegramService

logger = get_logger(__name__)


class LeadService:
    def __init__(
        self, telegram_service: TelegramService, chat_memory_service: ChatMemoryService
    ) -> None:
        self.telegram_service = telegram_service
        self.chat_memory_service = chat_memory_service

    async def create_contact_lead(
        self, lead_data: ContactFormLead, client_ip: str
    ) -> tuple[int, str, str]:
        """Creates a lead in DB and returns lead_id, message, alert_type."""
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

        tz = ZoneInfo("Europe/Kyiv")
        now_str = datetime.now(tz).strftime("%d.%m.%Y %H:%M")

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
            return lead_id, message, "hot_lead"
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
            return lead_id, message, "lead"

    async def process_lead_background(
        self, lead_id: int, message: str, alert_type: str = "lead", session_id: str | None = None
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
                    history = await self.chat_memory_service.get_history(session_id, limit=10)
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

                await self.telegram_service.send_alert(
                    message, alert_type=alert_type, reply_markup=reply_markup, session_id=session_id
                )

                # Update status to sent
                lead = await session.get(Lead, lead_id)
                if lead:
                    lead.notification_status = "sent"  # type: ignore
                    await commit_with_retry(session)
            except RetryError as e:
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("lead_id", str(lead_id))
                    sentry_sdk.capture_exception(e)
                lead = await session.get(Lead, lead_id)
                if lead:
                    lead.notification_status = "failed"  # type: ignore
                    await commit_with_retry(session)
            except Exception as e:
                with sentry_sdk.isolation_scope() as scope:
                    scope.set_tag("lead_id", str(lead_id))
                    sentry_sdk.capture_exception(e)
                lead = await session.get(Lead, lead_id)
                if lead:
                    lead.notification_status = "failed"  # type: ignore
                    await commit_with_retry(session)

    async def process_woo_order_background(self, payload: WooOrderPayload) -> None:
        """Process WooCommerce order in background."""
        # Create or update lead in the database
        async with AsyncSessionLocal() as session:
            try:
                db_lead = Lead(
                    name=payload.first_name,
                    surname=payload.last_name,
                    phone_number=payload.phone,
                    contact_method="woo_checkout",
                    lead_type="checkout",
                    session_id=payload.session_id,
                    woo_order_id=str(payload.order_id),
                    status="success",  # Immediate success because it's a sale
                    notification_status="pending",
                )
                session.add(db_lead)
                await commit_with_retry(session)
                leads_created_total.labels(type="conversion", status="success").inc()

                # Form message
                items_lines: list[str] = []
                for item in payload.items:
                    sku_info = f" (Арт: {item.sku})" if item.sku else ""
                    items_lines.append(
                        f"- {item.name}{sku_info} (x{item.quantity}) - {item.total} {payload.currency}"
                    )
                items_str = "\n".join(items_lines)
                message = ALERT_WOO_ORDER.format(
                    order_id=payload.order_id,
                    first_name=payload.first_name,
                    last_name=payload.last_name,
                    phone=payload.phone,
                    total=payload.total,
                    currency=payload.currency,
                    items_str=items_str,
                    session_id=payload.session_id,
                )

                alert_success = await self.telegram_service.send_alert(
                    message, alert_type="conversion", session_id=payload.session_id
                )

                if db_lead:
                    db_lead.notification_status = "sent" if alert_success else "failed"  # type: ignore
                    await commit_with_retry(session)
            except Exception:
                logger.exception("Error processing woo order webhook")

    async def create_chat_lead(self, phone_number: str, lead_type: str, session_id: str) -> int:
        """Create a simple chat lead."""
        async with AsyncSessionLocal() as session:
            db_lead = Lead(
                name="Клієнт з чату",
                phone_number=phone_number,
                contact_method="chat",
                lead_type=lead_type,
                session_id=session_id,
                status="new",
                notification_status="pending",
            )
            session.add(db_lead)
            await commit_with_retry(session)
            await session.refresh(db_lead)
            return int(db_lead.id)  # type: ignore

    async def update_lead_notification_status(self, lead_id: int, status: str) -> None:
        """Update notification status."""
        async with AsyncSessionLocal() as session:
            lead = await session.get(Lead, lead_id)
            if lead:
                lead.notification_status = status  # type: ignore
                await commit_with_retry(session)
