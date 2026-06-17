from unittest.mock import AsyncMock, Mock

import pytest

from app.core.constants import INTENT_CHECKOUT, INTENT_PRODUCT
from app.services.intent_handlers import ProductCheckoutIntentHandler, SearchIntentHandler


@pytest.fixture
def mock_price_comparator():
    comp = AsyncMock()
    return comp


@pytest.fixture
def mock_telegram_service():
    ts = AsyncMock()
    ts.send_alert.return_value = True
    return ts


@pytest.mark.asyncio
async def test_product_checkout_intent_checkout(
    mock_price_comparator, mock_telegram_service, mock_settings
):
    # Arrange
    handler = ProductCheckoutIntentHandler(
        mock_price_comparator, mock_telegram_service, mock_settings
    )

    mock_result = Mock()
    mock_result.needs_alert = False
    mock_result.woo_url = "http://woo"
    mock_result.product_name = "Test Product"
    mock_price_comparator.compare.return_value = mock_result

    # Act
    res = await handler.handle(
        intent_type=INTENT_CHECKOUT,
        product_name="Test Product",
        category_id=1,
        system_instructions=[],
        product_facts=[],
        extracted_links=[],
        session_id="test_sess",
    )

    # Assert
    assert res.requires_lead is True
    assert len(res.extracted_links) == 3
    assert res.extracted_links[0]["url"] == "http://woo?bot_source=direct&bot_chat_id=test_sess"
    assert res.extracted_links[1]["url"] == "http://tg"


@pytest.mark.asyncio
async def test_product_checkout_intent_alert(
    mock_price_comparator, mock_telegram_service, mock_settings
):
    # Arrange
    handler = ProductCheckoutIntentHandler(
        mock_price_comparator, mock_telegram_service, mock_settings
    )

    mock_result = Mock()
    mock_result.needs_alert = True
    mock_result.alert_reason = "low_margin"
    mock_result.product_name = "Test Product"
    mock_result.woo_price = 100
    mock_result.supplier_price_uah = 50
    mock_result.diff_woo_uah = 50
    mock_price_comparator.compare.return_value = mock_result

    # Act
    res = await handler.handle(
        intent_type=INTENT_PRODUCT,
        product_name="Test Product",
        category_id=1,
        system_instructions=[],
        product_facts=[],
        extracted_links=[],
        session_id="test_sess",
    )

    # Assert
    assert res.requires_lead is True
    mock_telegram_service.send_alert.assert_called_once()
    assert len(res.system_instructions) > 0


@pytest.mark.asyncio
async def test_search_intent_strict_success(mock_price_comparator):
    # Arrange
    handler = SearchIntentHandler(mock_price_comparator)

    mock_product = Mock()
    mock_product.name = "Test Prod"
    mock_product.price_uah = 100
    mock_product.stock_status = "instock"
    mock_product.attributes = {"Color": "Red"}
    mock_product.url = "http://test"

    mock_price_comparator.woo_service.search_products_async.return_value = [mock_product]

    # Act
    res = await handler.handle(
        intent_data={"strict_query": "Test Prod"},
        category_id=1,
        system_instructions=[],
        product_facts=[],
        extracted_links=[],
        session_id="test_sess",
    )

    # Assert
    assert res.requires_lead is False
    assert len(res.extracted_links) == 1
    assert "Test Prod" in res.product_facts[0]
    assert len(res.system_instructions) == 2
    assert "Бекенд знайшов товар" in res.system_instructions[1]


@pytest.mark.asyncio
async def test_search_intent_fallback_broad(mock_price_comparator):
    # Arrange
    handler = SearchIntentHandler(mock_price_comparator)

    mock_product = Mock()
    mock_product.name = "Broad Prod"
    mock_product.price_uah = 100
    mock_product.stock_status = "instock"
    mock_product.attributes = {}
    mock_product.url = ""

    # strict fails, broad succeeds
    mock_price_comparator.woo_service.search_products_async.side_effect = [[], [mock_product]]
    mock_price_comparator.woo_service.search_product_async.return_value = None

    # Act
    res = await handler.handle(
        intent_data={"strict_query": "Test", "broad_query": "Broad"},
        category_id=1,
        system_instructions=[],
        product_facts=[],
        extracted_links=[],
        session_id="test_sess",
    )

    # Assert
    assert mock_price_comparator.woo_service.search_products_async.call_count == 2
    assert "Broad Prod" in res.product_facts[0]


@pytest.mark.asyncio
async def test_search_intent_nothing_found(mock_price_comparator):
    # Arrange
    handler = SearchIntentHandler(mock_price_comparator)

    mock_price_comparator.woo_service.search_products_async.return_value = []
    mock_price_comparator.woo_service.search_product_async.return_value = None
    mock_price_comparator.woo_service.search_products_by_category_async.return_value = []

    # Act
    res = await handler.handle(
        intent_data={"strict_query": "Test"},
        category_id=1,
        system_instructions=[],
        product_facts=[],
        extracted_links=[],
        session_id="test_sess",
    )

    # Assert
    assert res.requires_lead is True
    assert len(res.system_instructions) > 0
