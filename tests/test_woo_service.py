from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.services.woo_service import WooService


@pytest.mark.asyncio
@patch("app.services.woo_service.httpx.AsyncClient")
async def test_search_product_async_success(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client

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
    mock_client.get.return_value = mock_response

    service = WooService(mock_settings)
    res = await service.search_product_async("TEST1", category_id=1)

    assert res is not None
    assert res.sku == "TEST1"
    assert res.price_uah == 100.0


@pytest.mark.asyncio
@patch("app.services.woo_service.httpx.AsyncClient")
async def test_search_product_async_fallback_sku(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client

    resp_empty = Mock()
    resp_empty.status_code = 200
    resp_empty.json.return_value = []

    resp_ok = Mock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = [{"sku": "TEST1", "name": "Prod", "price": "100"}]

    mock_client.get.side_effect = [resp_empty, resp_ok]

    service = WooService(mock_settings)
    res = await service.search_product_async("TEST1")

    assert res is not None
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
@patch("app.services.woo_service.httpx.AsyncClient")
async def test_search_products_async_success(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"sku": "1", "name": "P1", "price": "10"},
        {"sku": "2", "name": "P2", "price": "20"},
    ]
    mock_client.get.return_value = mock_response

    service = WooService(mock_settings)
    res = await service.search_products_async("Test")

    assert len(res) == 2


@pytest.mark.asyncio
@patch("app.services.woo_service.httpx.AsyncClient")
async def test_search_products_by_category_async_success(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"sku": "1", "name": "P1", "price": "10"}]
    mock_client.get.return_value = mock_response

    service = WooService(mock_settings)
    res = await service.search_products_by_category_async(1)

    assert len(res) == 1


@pytest.mark.asyncio
@patch("app.services.woo_service.httpx.AsyncClient")
async def test_woo_service_timeout(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.get.side_effect = httpx.TimeoutException("Timeout")

    service = WooService(mock_settings)
    res = await service.search_product_async("Test")
    assert res is None

    res2 = await service.search_products_async("Test")
    assert res2 == []

    res3 = await service.search_products_by_category_async(1)
    assert res3 == []
