from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.config import Settings
from app.schemas.chat import LeadData
from app.services.telegram_service import TelegramService


@pytest.fixture
def mock_settings_missing():
    settings = Mock(spec=Settings)
    settings.telegram_bot_token = ""
    settings.telegram_chat_id = ""
    return settings


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_send_alert_success(mock_client_class, mock_settings):
    # Arrange
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response

    service = TelegramService(mock_settings)

    # Act
    res = await service.send_alert("Test Alert")

    # Assert
    assert res is True
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_send_alert_retries(mock_client_class, mock_settings):
    # Arrange
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client

    # Fail twice, succeed on third
    resp_fail = Mock()
    resp_fail.status_code = 500
    resp_ok = Mock()
    resp_ok.status_code = 200

    mock_client.post.side_effect = [resp_fail, resp_fail, resp_ok]

    service = TelegramService(mock_settings)

    with patch("app.services.telegram_service.asyncio.sleep") as mock_sleep:
        # Act
        res = await service.send_alert("Test Alert")

    # Assert
    assert res is True
    assert mock_client.post.call_count == 3
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_send_alert_missing_creds(mock_settings_missing):
    service = TelegramService(mock_settings_missing)
    res = await service.send_alert("Test Alert")
    assert res is False


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_send_lead_success(mock_client_class, mock_settings):
    # Arrange
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response

    service = TelegramService(mock_settings)
    lead = LeadData(name="Test & Co", phone="+380000000000")

    # Act
    res = await service.send_lead(lead, context_info="Some context <tag>")

    # Assert
    assert res is True
    mock_client.post.assert_called_once()

    # Check escaping
    kwargs = mock_client.post.call_args[1]
    text = kwargs["json"]["text"]
    assert "Test &amp; Co" in text
    assert "&lt;tag&gt;" in text


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_send_lead_error(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.post.side_effect = Exception("Network error")

    service = TelegramService(mock_settings)

    with patch("app.services.telegram_service.asyncio.sleep"):
        res = await service.send_lead(LeadData(phone="+380123456789"), retries=2)

    assert res is False
    assert mock_client.post.call_count == 2
