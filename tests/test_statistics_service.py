from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.statistics_service import (
    fetch_prometheus_data,
    fetch_unique_users_24h,
    gather_and_send_daily_report_job,
)


@pytest.mark.asyncio
@patch("app.services.statistics_service.httpx.AsyncClient.get")
async def test_fetch_prometheus_data_success(mock_get):
    # Arrange
    settings = MagicMock()
    settings.prometheus_url = "http://test-prom"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {"result": [{"value": [1600000000, "42.5"]}]}}
    mock_get.return_value = mock_response

    # Act
    metrics = await fetch_prometheus_data(settings)

    # Assert
    assert metrics["tokens"] == 42.5
    assert metrics["latency_avg"] == 42.5
    assert mock_get.call_count > 0


@pytest.mark.asyncio
@patch("app.services.statistics_service.httpx.AsyncClient.get")
async def test_fetch_prometheus_data_error(mock_get):
    # Arrange
    settings = MagicMock()
    settings.prometheus_url = "http://test-prom"

    mock_get.side_effect = httpx.RequestError("Network error")

    # Act
    metrics = await fetch_prometheus_data(settings)

    # Assert
    assert metrics["tokens"] == 0.0
    assert metrics["latency_avg"] == 0.0


@pytest.mark.asyncio
@patch("app.services.statistics_service.AsyncSessionLocal")
async def test_fetch_unique_users_24h_success(mock_session_local):
    # Arrange
    mock_session = AsyncMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session
    mock_result = MagicMock()
    mock_result.scalar.return_value = 15
    mock_session.execute.return_value = mock_result

    # Act
    users_count = await fetch_unique_users_24h()

    # Assert
    assert users_count == 15
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.statistics_service.AsyncSessionLocal")
async def test_fetch_unique_users_24h_exception(mock_session_local):
    # Arrange
    mock_session = AsyncMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session
    mock_session.execute.side_effect = Exception("DB Error")

    # Act
    users_count = await fetch_unique_users_24h()

    # Assert
    assert users_count == 0


@pytest.mark.asyncio
@patch("app.services.statistics_service.get_settings")
@patch("app.services.statistics_service.TelegramService")
@patch("app.services.statistics_service.WooService")
@patch("app.services.statistics_service.fetch_prometheus_data")
@patch("app.services.statistics_service.fetch_unique_users_24h")
@patch(
    "app.services.statistics_service.STATISTICS_TEMPLATE",
    ["Stats: {unique_users} users, {woo_total} orders"],
)
async def test_gather_and_send_daily_report_job(
    mock_fetch_users,
    mock_fetch_prom,
    mock_woo_service_class,
    mock_tg_service_class,
    mock_get_settings,
):
    # Arrange
    mock_fetch_users.return_value = 100
    mock_fetch_prom.return_value = {
        "tokens": 1000,
        "latency_avg": 0.5,
        "errors": 2,
        "price_alerts": 5,
        "leads_contact": 10,
        "leads_hot": 20,
        "conversions": 5,
    }

    mock_woo_service = AsyncMock()
    mock_woo_service.get_daily_orders_stats.return_value = {
        "total": 50,
        "processing": 10,
        "on-hold": 5,
        "paid": 35,
        "tags": {"organic": 30, "cpc": 20},
    }
    mock_woo_service_class.return_value = mock_woo_service

    mock_tg_service = AsyncMock()
    mock_tg_service_class.return_value = mock_tg_service

    # Act
    await gather_and_send_daily_report_job()

    # Assert
    mock_woo_service.get_daily_orders_stats.assert_awaited_once()
    mock_tg_service.send_alert.assert_awaited_once()

    # Check that message formatting worked
    call_args = mock_tg_service.send_alert.call_args[0]
    message = call_args[0]
    assert "Stats: 100 users, 50 orders" in message
    assert "organic: 30 (60.0%)" in message
    assert "cpc: 20 (40.0%)" in message
