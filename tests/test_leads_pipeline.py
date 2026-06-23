from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.middleware.rate_limiter import limiter
from app.schemas.lead import ContactFormLead
from app.services.telegram_service import TelegramService


@pytest.fixture(autouse=True)
def reset_rate_limit() -> None:
    """Fixture to reset the rate limiter storage before each test."""
    limiter._storage.reset()  # type: ignore[reportPrivateUsage]


# 1. Pydantic schema tests
def test_clean_and_validate_phone_success() -> None:
    """Test cleaning and validation of a properly formatted phone number."""
    lead = ContactFormLead(
        name="Test", phone_number="+38 (093) 123-45-67", contact_method="telegram"
    )
    assert lead.phone_number == "+380931234567"


def test_clean_and_validate_phone_no_country_code() -> None:
    """Test cleaning and validation of a phone number missing the country code."""
    lead = ContactFormLead(name="Test", phone_number="093 123 45 67", contact_method="telegram")
    assert lead.phone_number == "0931234567"


def test_clean_and_validate_phone_too_short() -> None:
    """Test that a phone number which is too short raises a ValidationError."""
    with pytest.raises(ValidationError) as exc:
        ContactFormLead(name="Test", phone_number="093 123", contact_method="telegram")
    assert "Некоректний формат телефону" in str(exc.value)


def test_clean_and_validate_phone_integer() -> None:
    """Test that an integer phone number is properly converted to string and validated."""
    lead = ContactFormLead(
        name="Test",
        phone_number=380931234567,  # type: ignore
        contact_method="telegram",
    )
    assert lead.phone_number == "380931234567"


# 2. TelegramService tests
@pytest.mark.asyncio
async def test_telegram_service_success() -> None:
    """Test successful sending of an alert via TelegramService."""
    service = TelegramService(
        MagicMock(telegram_bot_token="test", telegram_chat_id="test", tg_leads_chat_id="test")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = await service.send_alert("Test message")
        assert result is True
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_telegram_service_http_error() -> None:
    """Test handling of an HTTP error while sending an alert via TelegramService."""
    service = TelegramService(
        MagicMock(telegram_bot_token="test", telegram_chat_id="test", tg_leads_chat_id="test")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        result = await service.send_alert("Test message")
        assert result is False
        assert mock_post.call_count == 3


@pytest.mark.asyncio
async def test_telegram_service_network_error() -> None:
    """Test handling of a network error while sending an alert via TelegramService."""
    service = TelegramService(
        MagicMock(telegram_bot_token="test", telegram_chat_id="test", tg_leads_chat_id="test")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Network Error")

        result = await service.send_alert("Test message")
        assert result is False
        assert mock_post.call_count == 3


# 4. API Endpoint tests
client = TestClient(app)


def test_api_create_lead_honeypot() -> None:
    """Test creating a lead with honeypot data returns a fake success response."""
    response = client.post(
        "/api/v1/leads",
        json={
            "name": "Spam Bot",
            "phone_number": "0931234567",
            "contact_method": "telegram",
            "honeypot": "spammed_data",
        },
    )

    # The endpoint is configured with status_code=201
    assert response.status_code == 201
    assert response.json() == {"status": "success", "message": "Lead received"}


@patch("app.api.v1.endpoints.leads.BackgroundTasks.add_task")
@patch("app.services.lead_service.LeadService.create_contact_lead", new_callable=AsyncMock)
def test_api_create_lead_success(mock_create_lead: AsyncMock, mock_add_task: MagicMock) -> None:
    """Test successful creation of a lead via the API."""
    mock_create_lead.return_value = (1, "Test message", "lead")

    response = client.post(
        "/api/v1/leads",
        json={"name": "Real User", "phone_number": "+380931234567", "contact_method": "telegram"},
    )

    assert response.status_code == 201
    assert response.json() == {"status": "success", "message": "Lead received"}

    # Verify DB insertion logic was triggered
    mock_create_lead.assert_called_once()

    # Verify background task was queued
    mock_add_task.assert_called_once()


def test_api_create_lead_payload_too_large_header() -> None:
    """Test creating a lead with a content-length header exceeding the maximum allowed."""
    response = client.post(
        "/api/v1/leads",
        headers={"content-length": "3000", "X-Forwarded-For": "10.0.0.2"},
        json={"name": "Test"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Payload Too Large"}


def test_api_create_lead_payload_too_large_stream() -> None:
    """Test creating a lead with a payload stream exceeding the maximum allowed."""
    # Send a payload larger than 2048 bytes
    large_payload = {
        "name": "A" * 3000,
        "phone_number": "0931234567",
        "contact_method": "telegram",
    }
    response = client.post(
        "/api/v1/leads", json=large_payload, headers={"X-Forwarded-For": "10.0.0.3"}
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Payload Too Large"}


def test_api_create_lead_invalid_json() -> None:
    """Test creating a lead with invalid JSON data returns 422."""
    response = client.post(
        "/api/v1/leads",
        json={"wrong_field": "data"},  # missing name, phone, etc.
        headers={"X-Forwarded-For": "10.0.0.4"},
    )
    assert response.status_code == 422
    assert "Invalid JSON format or validation error" in response.json()["detail"]


@patch("app.services.lead_service.AsyncSessionLocal")
@patch("app.services.telegram_service.TelegramService.send_alert", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_process_lead_background_success(
    mock_send_tg: AsyncMock, mock_session_local: MagicMock
) -> None:
    """Test processing a lead in the background successfully."""
    from app.models.lead import Lead
    from app.services.chat_memory_service import ChatMemoryService
    from app.services.lead_service import LeadService

    mock_session = AsyncMock()
    mock_lead = MagicMock(spec=Lead)
    mock_session.get.return_value = mock_lead
    mock_session_local.return_value.__aenter__.return_value = mock_session

    tg_service = TelegramService(MagicMock())
    chat_service = ChatMemoryService()
    lead_service = LeadService(tg_service, chat_service)

    await lead_service.process_lead_background(1, "Test Message")

    mock_send_tg.assert_called_once_with(
        "Test Message",
        alert_type="lead",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "✅ Успіх (Продано)", "callback_data": "lead_status:1:success"},
                    {"text": "❌ Відмова", "callback_data": "lead_status:1:decline"},
                ],
                [{"text": "⏳ В процесі", "callback_data": "lead_status:1:in_progress"}],
            ]
        },
        session_id=None,
    )
    assert mock_lead.notification_status == "sent"
    mock_session.commit.assert_called_once()


@patch("app.services.lead_service.AsyncSessionLocal")
@patch("app.services.telegram_service.TelegramService.send_alert", new_callable=AsyncMock)
@patch("app.services.lead_service.sentry_sdk.capture_exception")
@pytest.mark.asyncio
async def test_process_lead_background_error(
    mock_sentry: MagicMock, mock_send_tg: AsyncMock, mock_session_local: MagicMock
) -> None:
    """Test background lead processing handles Exception and logs to Sentry."""
    from app.models.lead import Lead
    from app.services.chat_memory_service import ChatMemoryService
    from app.services.lead_service import LeadService

    mock_session = AsyncMock()
    mock_lead = MagicMock(spec=Lead)
    mock_session.get.return_value = mock_lead
    mock_session_local.return_value.__aenter__.return_value = mock_session

    tg_service = TelegramService(MagicMock())
    chat_service = ChatMemoryService()
    lead_service = LeadService(tg_service, chat_service)

    # Simulate an Exception from send_alert
    error = Exception("Network Error")
    mock_send_tg.side_effect = error

    await lead_service.process_lead_background(1, "Test Message")

    # Verify Sentry was called
    mock_sentry.assert_called_once_with(error)

    # Verify DB status updated to failed
    assert mock_lead.notification_status == "failed"
    mock_session.commit.assert_called_once()


def test_api_create_lead_rate_limiting() -> None:
    """Test that the API correctly rate limits lead creation requests."""
    # Use a unique IP header to ensure rate limit buckets are fresh for this test
    headers = {"X-Forwarded-For": "10.0.0.5"}

    # 3 requests allowed per minute, so the 4th should fail with 429
    for _ in range(3):
        res = client.post(
            "/api/v1/leads",
            json={
                "name": "Rate Limit",
                "phone_number": "0931234567",
                "contact_method": "telegram",
                "honeypot": "spam",
            },
            headers=headers,
        )
        assert res.status_code == 201

    res = client.post(
        "/api/v1/leads",
        json={
            "name": "Rate Limit",
            "phone_number": "0931234567",
            "contact_method": "telegram",
            "honeypot": "spam",
        },
        headers=headers,
    )
    assert res.status_code == 429
    assert "Rate limit exceeded" in res.text
