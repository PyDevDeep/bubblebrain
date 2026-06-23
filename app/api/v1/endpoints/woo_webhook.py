import logging

from fastapi import APIRouter, BackgroundTasks, Depends, status

from app.api.dependencies import get_lead_service
from app.schemas.order import WooOrderPayload
from app.services.lead_service import LeadService

logger = logging.getLogger(__name__)

woo_webhook_router = APIRouter()


@woo_webhook_router.post("/woo-order", status_code=status.HTTP_200_OK)
async def woo_order_webhook(
    payload: WooOrderPayload,
    background_tasks: BackgroundTasks,
    lead_service: LeadService = Depends(get_lead_service),
) -> dict[str, str]:
    """Handle WooCommerce order webhook."""
    background_tasks.add_task(lead_service.process_woo_order_background, payload)
    return {"status": "success", "message": "Webhook received"}
