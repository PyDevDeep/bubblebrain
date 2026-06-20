# pyright: reportPrivateUsage=false
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
    settings.telegram_topic_general = None
    settings.telegram_topic_leads = None
    settings.telegram_topic_hot_leads = None
    settings.telegram_topic_conversions = None
    settings.telegram_topic_bot_stats = None
    settings.telegram_topic_prices = None
    settings.telegram_topic_errors = None
    return settings


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_send_alert_success(mock_client_class, mock_settings):
    # Arrange
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 200
    mock_client.post = AsyncMock(return_value=mock_response)

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
    mock_client_class.return_value = mock_client

    # Fail twice, succeed on third
    resp_fail = Mock()
    resp_fail.status_code = 500
    resp_ok = Mock()
    resp_ok.status_code = 200

    mock_client.post = AsyncMock(side_effect=[resp_fail, resp_fail, resp_ok])

    service = TelegramService(mock_settings)

    with patch("app.services.telegram_service.asyncio.sleep") as mock_sleep:
        # Act
        res = await service.send_alert("Test Alert", reply_markup={"inline_keyboard": []})

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
    mock_client_class.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 200
    mock_client.post = AsyncMock(return_value=mock_response)

    service = TelegramService(mock_settings)
    lead = LeadData(name="Test & Co", phone="+380000000000")

    # Act
    service.fallback_topic = None
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
    mock_client_class.return_value = mock_client
    mock_client.post = AsyncMock(side_effect=Exception("Network error"))

    service = TelegramService(mock_settings)

    with patch("app.services.telegram_service.asyncio.sleep"):
        res = await service.send_lead(LeadData(phone="+380123456789"), retries=2)

    assert res is False
    assert mock_client.post.call_count == 2

    # Missing credentials
    service.api_base = None
    res_no_creds = await service.send_lead(LeadData(phone="+380123456789"))
    assert res_no_creds is False


@pytest.mark.asyncio
async def test_close(mock_settings):
    service = TelegramService(mock_settings)
    service.client.aclose = AsyncMock()
    await service.close()
    service.client.aclose.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_make_request_with_files(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    service = TelegramService(mock_settings)
    mock_client.post.return_value = Mock(status_code=200)
    await service._make_request("test", data={"a": 1}, files={"f": "file"})
    mock_client.post.assert_called_once_with(
        f"{service.api_base}/test", data={"a": 1}, files={"f": "file"}, timeout=60.0
    )

    # test missing api_base
    service.api_base = None
    res = await service._make_request("test")
    assert res is None


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_send_alert_with_history(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    service = TelegramService(mock_settings)
    service.send_document = AsyncMock(return_value=True)
    mock_client.post.return_value = Mock(status_code=200)
    # With history and session_id
    await service.send_alert("msg", history=[{"role": "user", "content": "hi"}], session_id="123")
    service.send_document.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_update_message_reply_markup(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    mock_client.post.return_value = Mock(status_code=200)
    service = TelegramService(mock_settings)
    res = await service.update_message_reply_markup(123, {"inline_keyboard": []})
    assert res is True
    # Test without api base
    service.api_base = None
    res = await service.update_message_reply_markup(123)
    assert res is False


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_edit_message_text(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    mock_client.post.return_value = Mock(status_code=200)
    service = TelegramService(mock_settings)
    res = await service.edit_message_text(123, "text", {"kb": 1})
    assert res is True
    service.api_base = None
    res = await service.edit_message_text(123, "text")
    assert res is False


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_send_document(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    mock_client.post.return_value = Mock(status_code=200)
    service = TelegramService(mock_settings)
    service.fallback_topic = None
    res = await service.send_document("doc.txt", "content", "cap", "general")
    assert res is True

    # Missing credentials
    service.api_base = None
    res2 = await service.send_document("doc.txt", "content", "cap", "general")
    assert res2 is False


@pytest.mark.asyncio
@patch("app.services.telegram_service.httpx.AsyncClient")
async def test_topics_present(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    mock_settings.telegram_topic_general = 12345
    service = TelegramService(mock_settings)

    mock_client.post.return_value = Mock(status_code=200)

    await service.send_alert("msg")
    await service.send_lead(LeadData(phone="+380000000000"))
    await service.send_document("doc.txt", "content")

    assert mock_client.post.call_count == 3

    # Assert that message_thread_id was sent in the payload
    for call in mock_client.post.call_args_list:
        if "data" in call.kwargs:
            assert call.kwargs["data"]["message_thread_id"] == 12345
        else:
            assert call.kwargs["json"]["message_thread_id"] == 12345
