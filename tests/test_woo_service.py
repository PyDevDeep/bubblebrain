# pyright: reportPrivateUsage=false
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.services.woo_service import WooService


@pytest.mark.asyncio
@patch("app.services.woo_service.WooService._get_client")
async def test_search_product_async_success(mock_get_client, mock_settings):
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "sku": "TEST1",
            "name": "Prod",
            "price": "100",
            "permalink": "http://test",
            "stock_status": "instock",
        }
    ]
    mock_client.get = AsyncMock(return_value=mock_response)

    service = WooService(mock_settings)
    res = await service.search_product_async("TEST1", category_id=1)

    assert res is not None
    assert res.sku == "TEST1"
    assert res.price_uah == 100.0


@pytest.mark.asyncio
@patch("app.services.woo_service.WooService._get_client")
async def test_search_product_async_fallback_sku(mock_get_client, mock_settings):
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client

    resp_empty = Mock()
    resp_empty.status_code = 200
    resp_empty.json.return_value = []

    resp_ok = Mock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = [{"sku": "TEST1", "name": "Prod", "price": "100"}]

    mock_client.get = AsyncMock(side_effect=[resp_empty, resp_ok])

    service = WooService(mock_settings)
    res = await service.search_product_async("TEST1")

    assert res is not None
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
@patch("app.services.woo_service.WooService._get_client")
async def test_search_products_async_success(mock_get_client, mock_settings):
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"sku": "1", "name": "P1", "price": "10"},
        {"sku": "2", "name": "P2", "price": "20"},
    ]
    mock_client.get = AsyncMock(return_value=mock_response)

    service = WooService(mock_settings)
    res = await service.search_products_async("Test", category_id=1)

    assert len(res) == 2


@pytest.mark.asyncio
@patch("app.services.woo_service.WooService._get_client")
async def test_search_products_by_category_async_success(mock_get_client, mock_settings):
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"sku": "1", "name": "P1", "price": "10"}]
    mock_client.get = AsyncMock(return_value=mock_response)

    service = WooService(mock_settings)
    res = await service.search_products_by_category_async(1)

    assert len(res) == 1


@pytest.mark.asyncio
@patch("app.services.woo_service.WooService._get_client")
async def test_woo_service_timeout(mock_get_client, mock_settings):
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))

    service = WooService(mock_settings)
    res = await service.search_product_async("Test")
    assert res is None

    res2 = await service.search_products_async("Test")
    assert res2 == []

    res3 = await service.search_products_by_category_async(1)
    assert res3 == []


@pytest.mark.asyncio
async def test_close_woo_client():
    import app.services.woo_service as ws
    from app.services.woo_service import WooService, close_woo_client

    ws._global_client = None
    service = WooService(Mock())

    # Test _get_client branch
    c1 = service._get_client()
    c2 = service._get_client()
    assert c1 is c2

    ws._global_client = AsyncMock()
    await close_woo_client()
    assert ws._global_client is None


@pytest.mark.asyncio
@patch("app.services.woo_service.WooService._get_client")
async def test_fetch_and_parse_single_exceptions(mock_get_client, mock_settings):
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client
    mock_client.get = AsyncMock(side_effect=Exception("API Error"))

    service = WooService(mock_settings)
    res = await service._fetch_and_parse_single({"search": "test"})
    assert res is None


@pytest.mark.asyncio
@patch("app.services.woo_service.WooService._get_client")
async def test_fetch_products_list_exceptions(mock_get_client, mock_settings):
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client
    service = WooService(mock_settings)

    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("Err", request=Mock(), response=Mock())
    )
    res = await service._fetch_products_list({}, "Ctx")
    assert res == []

    mock_client.get = AsyncMock(side_effect=httpx.RequestError("Err", request=Mock()))
    res = await service._fetch_products_list({}, "Ctx")
    assert res == []

    mock_client.get = AsyncMock(side_effect=Exception("Err"))
    res = await service._fetch_products_list({}, "Ctx")
    assert res == []


@pytest.mark.asyncio
@patch("app.services.woo_service.WooService._get_client")
async def test_get_daily_orders_stats(mock_get_client, mock_settings):
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"status": "processing", "meta_data": [{"key": "utm_source", "value": "fb"}]},
        {"status": "on-hold", "meta_data": [{"key": "bot_tag", "value": "TEST"}]},
        {
            "status": "completed",
            "meta_data": [{"key": "_wc_order_attribution_utm_campaign", "value": "camp"}],
        },
        {
            "status": "completed",
            "meta_data": [{"key": "_wc_order_attribution_utm_medium", "value": "cpc"}],
        },
        {
            "status": "completed",
            "meta_data": [
                {"key": "_wc_order_attribution_referrer", "value": "https://google.com/path"}
            ],
        },
        {"status": "other", "meta_data": "invalid"},
        {"status": "completed", "meta_data": [{"key": "bot_tag", "value": ""}]},
    ]
    mock_client.get = AsyncMock(return_value=mock_response)

    service = WooService(mock_settings)
    stats = await service.get_daily_orders_stats()

    assert stats["total"] == 7
    assert stats["processing"] == 1
    assert stats["on-hold"] == 1
    assert stats["completed"] == 4
    assert stats["paid"] == 4
    assert "Джерело: fb" in stats["tags"]
    assert "Створено: test" in stats["tags"]
    assert "Кампанія: camp" in stats["tags"]
    assert "Канал: cpc" in stats["tags"]
    assert "Реферер: google.com" in stats["tags"]


@pytest.mark.asyncio
@patch("app.services.woo_service.WooService._get_client")
async def test_get_daily_orders_stats_exception(mock_get_client, mock_settings):
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client
    mock_client.get = AsyncMock(side_effect=Exception("API Error"))

    service = WooService(mock_settings)
    stats = await service.get_daily_orders_stats()
    assert stats["total"] == 0


@pytest.mark.asyncio
@patch("app.services.woo_service.WooService._get_client")
async def test_get_order_async(mock_get_client, mock_settings):
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": 123, "status": "processing"}
    mock_client.get = AsyncMock(return_value=mock_response)

    service = WooService(mock_settings)
    order = await service.get_order_async(123)
    assert order is not None
    assert order["id"] == 123

    # Exception paths
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
    order = await service.get_order_async(123)
    assert order is None

    mock_resp_404 = Mock()
    mock_resp_404.status_code = 404
    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("404", request=Mock(), response=mock_resp_404)
    )
    order = await service.get_order_async(123)
    assert order is None

    mock_resp_500 = Mock()
    mock_resp_500.status_code = 500
    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("500", request=Mock(), response=mock_resp_500)
    )
    order = await service.get_order_async(123)
    assert order is None

    mock_client.get = AsyncMock(side_effect=httpx.RequestError("Err", request=Mock()))
    order = await service.get_order_async(123)
    assert order is None

    mock_client.get = AsyncMock(side_effect=Exception("Err"))
    order = await service.get_order_async(123)
    assert order is None
