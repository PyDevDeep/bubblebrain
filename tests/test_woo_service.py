# pyright: reportPrivateUsage=false
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.services.woo_service import WooService


@pytest.mark.asyncio
async def test_search_product_async_success(mock_settings):
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
    service = WooService(mock_settings)
    service.client.get = AsyncMock(return_value=mock_response)
    res = await service.search_product_async("TEST1", category_id=1)

    assert res is not None
    assert res.sku == "TEST1"
    assert res.price_uah == 100.0


@pytest.mark.asyncio
async def test_search_product_async_fallback_sku(mock_settings):
    resp_empty = Mock()
    resp_empty.status_code = 200
    resp_empty.json.return_value = []

    resp_ok = Mock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = [{"sku": "TEST1", "name": "Prod", "price": "100"}]

    service = WooService(mock_settings)
    service.client.get = AsyncMock(side_effect=[resp_empty, resp_ok])
    res = await service.search_product_async("TEST1")

    assert res is not None
    assert service.client.get.call_count == 2


@pytest.mark.asyncio
async def test_search_products_async_success(mock_settings):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"sku": "1", "name": "P1", "price": "10"},
        {"sku": "2", "name": "P2", "price": "20"},
    ]
    service = WooService(mock_settings)
    service.client.get = AsyncMock(return_value=mock_response)
    res = await service.search_products_async("Test", category_id=1)

    assert len(res) == 2


@pytest.mark.asyncio
async def test_search_products_by_category_async_success(mock_settings):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"sku": "1", "name": "P1", "price": "10"}]
    service = WooService(mock_settings)
    service.client.get = AsyncMock(return_value=mock_response)
    res = await service.search_products_by_category_async(1)

    assert len(res) == 1


@pytest.mark.asyncio
async def test_woo_service_timeout(mock_settings):
    service = WooService(mock_settings)
    service.client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
    res = await service.search_product_async("Test")
    assert res is None

    res2 = await service.search_products_async("Test")
    assert res2 == []

    res3 = await service.search_products_by_category_async(1)
    assert res3 == []


@pytest.mark.asyncio
async def test_close_woo_client():
    from app.services.woo_service import WooService

    service = WooService(Mock())
    service.client = AsyncMock()

    await service.close()

    service.client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_and_parse_single_exceptions(mock_settings):
    service = WooService(mock_settings)
    service.client.get = AsyncMock(side_effect=Exception("API Error"))
    res = await service._fetch_and_parse_single({"search": "test"})
    assert res is None


@pytest.mark.asyncio
async def test_fetch_products_list_exceptions(mock_settings):
    service = WooService(mock_settings)

    service.client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("Err", request=Mock(), response=Mock())
    )
    res = await service._fetch_products_list({}, "Ctx")
    assert res == []

    service.client.get = AsyncMock(side_effect=httpx.RequestError("Err", request=Mock()))
    res = await service._fetch_products_list({}, "Ctx")
    assert res == []

    service.client.get = AsyncMock(side_effect=Exception("Err"))
    res = await service._fetch_products_list({}, "Ctx")
    assert res == []


@pytest.mark.asyncio
async def test_get_daily_orders_stats(mock_settings):
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
    service = WooService(mock_settings)
    service.client.get = AsyncMock(return_value=mock_response)
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
async def test_get_daily_orders_stats_exception(mock_settings):
    service = WooService(mock_settings)
    service.client.get = AsyncMock(side_effect=Exception("API Error"))
    stats = await service.get_daily_orders_stats()
    assert stats["total"] == 0


@pytest.mark.asyncio
async def test_get_order_async(mock_settings):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": 123, "status": "processing"}
    service = WooService(mock_settings)
    service.client.get = AsyncMock(return_value=mock_response)
    order = await service.get_order_async(123)
    assert order is not None
    assert order["id"] == 123

    # Exception paths
    service.client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
    order = await service.get_order_async(123)
    assert order is None

    mock_resp_404 = Mock()
    mock_resp_404.status_code = 404
    service.client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("404", request=Mock(), response=mock_resp_404)
    )
    order = await service.get_order_async(123)
    assert order is None

    mock_resp_500 = Mock()
    mock_resp_500.status_code = 500
    service.client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("500", request=Mock(), response=mock_resp_500)
    )
    order = await service.get_order_async(123)
    assert order is None

    service.client.get = AsyncMock(side_effect=httpx.RequestError("Err", request=Mock()))
    order = await service.get_order_async(123)
    assert order is None

    service.client.get = AsyncMock(side_effect=Exception("Err"))
    order = await service.get_order_async(123)
    assert order is None
