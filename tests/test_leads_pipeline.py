from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tenacity import RetryError

from app.api.v1.endpoints.leads import send_telegram_notification
from app.main import app
from app.middleware.rate_limiter import limiter
from app.schemas.lead import ContactFormLead
from app.services.telegram_service import TelegramService


@pytest.fixture(autouse=True)
def reset_rate_limit() -> None:
    limiter._storage.reset()  # type: ignore[reportPrivateUsage]


# 1. Pydantic schema tests
def test_clean_and_validate_phone_success() -> None:
    lead = ContactFormLead(
        name="Test", phone_number="+38 (093) 123-45-67", contact_method="telegram"
    )
    assert lead.phone_number == "+380931234567"


def test_clean_and_validate_phone_no_country_code() -> None:
    lead = ContactFormLead(name="Test", phone_number="093 123 45 67", contact_method="telegram")
    assert lead.phone_number == "0931234567"


def test_clean_and_validate_phone_too_short() -> None:
    with pytest.raises(ValidationError) as exc:
        ContactFormLead(name="Test", phone_number="093 123", contact_method="telegram")
    assert "Некоректний формат телефону" in str(exc.value)


def test_clean_and_validate_phone_integer() -> None:
    lead = ContactFormLead(
        name="Test",
        phone_number=380931234567,  # type: ignore
        contact_method="telegram",
    )
    assert lead.phone_number == "380931234567"


# 2. TelegramService tests
@pytest.mark.asyncio
async def test_telegram_service_success() -> None:
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
    service = TelegramService(
        MagicMock(telegram_bot_token="test", telegram_chat_id="test", tg_leads_chat_id="test")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Network Error")

        result = await service.send_alert("Test message")
        assert result is False
        assert mock_post.call_count == 3


# 3. Tenacity tests
@pytest.mark.asyncio
async def test_send_telegram_notification_retry_limit() -> None:
    with patch(
        "app.services.telegram_service.TelegramService.send_alert", new_callable=AsyncMock
    ) as mock_send_alert:
        # Mock telegram service to always raise ConnectError
        mock_send_alert.side_effect = httpx.ConnectError("Network Error")

        with pytest.raises(RetryError):
            # This should retry exactly 3 times as configured
            await send_telegram_notification(lead_id=1, message="Test retry", alert_type="lead")

        assert mock_send_alert.call_count == 3


# 4. API Endpoint tests
client = TestClient(app)


def test_api_create_lead_honeypot() -> None:
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


@patch("app.api.v1.endpoints.leads.AsyncSessionLocal")
@patch("app.api.v1.endpoints.leads.BackgroundTasks.add_task")
def test_api_create_lead_success(mock_add_task: MagicMock, mock_session_local: MagicMock) -> None:
    # Set up the async context manager mock
    mock_session = AsyncMock()

    # session.add is a synchronous method in SQLAlchemy AsyncSession
    mock_session.add = MagicMock()

    import typing

    async def mock_refresh(instance: typing.Any) -> None:
        instance.id = 1

    mock_session.refresh = AsyncMock(side_effect=mock_refresh)
    mock_session_local.return_value.__aenter__.return_value = mock_session

    response = client.post(
        "/api/v1/leads",
        json={"name": "Real User", "phone_number": "+380931234567", "contact_method": "telegram"},
    )

    assert response.status_code == 201
    assert response.json() == {"status": "success", "message": "Lead received"}

    # Verify DB insertion
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()

    # Verify background task was queued
    mock_add_task.assert_called_once()


def test_api_create_lead_payload_too_large_header() -> None:
    response = client.post(
        "/api/v1/leads",
        headers={"content-length": "3000", "X-Forwarded-For": "10.0.0.2"},
        json={"name": "Test"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Payload Too Large"}


def test_api_create_lead_payload_too_large_stream() -> None:
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
    response = client.post(
        "/api/v1/leads",
        json={"wrong_field": "data"},  # missing name, phone, etc.
        headers={"X-Forwarded-For": "10.0.0.4"},
    )
    assert response.status_code == 422
    assert "Invalid JSON format or validation error" in response.json()["detail"]


@patch("app.api.v1.endpoints.leads.AsyncSessionLocal")
@patch("app.api.v1.endpoints.leads.send_telegram_notification", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_process_lead_background_success(
    mock_send_tg: AsyncMock, mock_session_local: MagicMock
) -> None:
    from app.api.v1.endpoints.leads import process_lead_background
    from app.models.lead import Lead

    mock_session = AsyncMock()
    mock_lead = MagicMock(spec=Lead)
    mock_session.get.return_value = mock_lead
    mock_session_local.return_value.__aenter__.return_value = mock_session

    await process_lead_background(1, "Test Message")

    mock_send_tg.assert_called_once_with(
        1,
        "Test Message",
        "lead",
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


@patch("app.api.v1.endpoints.leads.AsyncSessionLocal")
@patch("app.api.v1.endpoints.leads.send_telegram_notification", new_callable=AsyncMock)
@patch("app.api.v1.endpoints.leads.sentry_sdk.capture_message")
@pytest.mark.asyncio
async def test_process_lead_background_retry_error(
    mock_sentry: MagicMock, mock_send_tg: AsyncMock, mock_session_local: MagicMock
) -> None:
    from tenacity import RetryError

    from app.api.v1.endpoints.leads import process_lead_background
    from app.models.lead import Lead

    mock_session = AsyncMock()
    mock_lead = MagicMock(spec=Lead)
    mock_session.get.return_value = mock_lead
    mock_session_local.return_value.__aenter__.return_value = mock_session

    # Simulate a RetryError from send_telegram_notification
    mock_send_tg.side_effect = RetryError(last_attempt=MagicMock())

    await process_lead_background(1, "Test Message")

    # Verify Sentry was called
    mock_sentry.assert_called_once_with("Telegram API failed for lead_id=1", level="error")

    # Verify DB status updated to failed
    assert mock_lead.notification_status == "failed"
    mock_session.commit.assert_called_once()


def test_api_create_lead_rate_limiting() -> None:
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
