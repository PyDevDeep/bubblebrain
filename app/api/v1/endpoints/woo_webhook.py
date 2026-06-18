import logging

from fastapi import APIRouter, BackgroundTasks, status
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.constants import ALERT_WOO_ORDER
from app.core.db import AsyncSessionLocal, commit_with_retry
from app.core.metrics import leads_created_total
from app.models.lead import Lead
from app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)

woo_webhook_router = APIRouter()


class WooOrderItem(BaseModel):
    name: str
    quantity: int
    total: str
    sku: str | None = None


class WooOrderPayload(BaseModel):
    order_id: int | str
    session_id: str
    total: str
    currency: str
    first_name: str
    last_name: str
    phone: str
    items: list[WooOrderItem]


async def process_woo_order_background(payload: WooOrderPayload) -> None:
    settings = get_settings()
    telegram_service = TelegramService(settings)

    # Створюємо або оновлюємо ліда в базі даних
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
                status="success",  # Відразу успіх, бо це факт продажу
                notification_status="pending",
            )
            session.add(db_lead)
            await commit_with_retry(session)
            leads_created_total.labels(type="conversion", status="success").inc()

            # Формуємо повідомлення
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

            alert_success = await telegram_service.send_alert(
                message, alert_type="conversion", session_id=payload.session_id
            )

            db_lead.notification_status = "sent" if alert_success else "failed"  # type: ignore
            await commit_with_retry(session)
        except Exception as e:
            logger.error(f"Error processing woo order webhook: {e}")


@woo_webhook_router.post("/woo-order", status_code=status.HTTP_200_OK)
async def woo_order_webhook(
    payload: WooOrderPayload, background_tasks: BackgroundTasks
) -> dict[str, str]:
    background_tasks.add_task(process_woo_order_background, payload)
    return {"status": "success", "message": "Webhook received"}
