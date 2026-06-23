from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.api.dependencies import get_lead_service
from app.core.constants import MAX_PAYLOAD_SIZE
from app.middleware.rate_limiter import limiter
from app.schemas.lead import ContactFormLead
from app.services.lead_service import LeadService

leads_router = APIRouter()


@leads_router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")  # type: ignore
async def create_lead(
    request: Request,
    background_tasks: BackgroundTasks,
    lead_service: LeadService = Depends(get_lead_service),
) -> dict[str, str]:
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

    client_ip = request.client.host if request.client else "Unknown"

    lead_id, message, alert_type = await lead_service.create_contact_lead(lead_data, client_ip)

    background_tasks.add_task(
        lead_service.process_lead_background, lead_id, message, alert_type, lead_data.session_id
    )

    return {"status": "success", "message": "Lead received"}
