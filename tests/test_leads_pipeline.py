from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tenacity import RetryError

from app.api.v1.endpoints.leads import send_telegram_notification
from app.main import app
from app.schemas.lead import ContactFormLead
from app.services.telegram_service import TelegramService


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
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        await service.send_alert("Test message")
        mock_post.assert_called_once()
        mock_response.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_telegram_service_http_error() -> None:
    service = TelegramService(
        MagicMock(telegram_bot_token="test", telegram_chat_id="test", tg_leads_chat_id="test")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP Error", request=MagicMock(), response=MagicMock()
        )
        mock_post.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            await service.send_alert("Test message")


@pytest.mark.asyncio
async def test_telegram_service_network_error() -> None:
    service = TelegramService(
        MagicMock(telegram_bot_token="test", telegram_chat_id="test", tg_leads_chat_id="test")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Network Error")

        with pytest.raises(httpx.ConnectError):
            await service.send_alert("Test message")


# 3. Tenacity tests
@pytest.mark.asyncio
async def test_send_telegram_notification_retry_limit() -> None:
    with patch(
        "app.api.v1.endpoints.leads.telegram_service.send_alert", new_callable=AsyncMock
    ) as mock_send_alert:
        # Mock telegram service to always raise ConnectError
        mock_send_alert.side_effect = httpx.ConnectError("Network Error")

        with pytest.raises(RetryError):
            # This should retry exactly 3 times as configured
            await send_telegram_notification(lead_id=1, message="Test retry")

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

    # Should return 200 OK to trick the bot, but not actually process it
    assert response.status_code == 200
    assert response.json() == {"status": "success"}


@patch("app.api.v1.endpoints.leads.AsyncSessionLocal")
@patch("app.api.v1.endpoints.leads.BackgroundTasks.add_task")
def test_api_create_lead_success(mock_add_task: MagicMock, mock_session_local: MagicMock) -> None:
    # Set up the async context manager mock
    mock_session = AsyncMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session

    response = client.post(
        "/api/v1/leads",
        json={"name": "Real User", "phone_number": "+380931234567", "contact_method": "telegram"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}

    # Verify DB insertion
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once()

    # Verify background task was queued
    mock_add_task.assert_called_once()
