from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.scraper import DatacompProduct
from app.services.price_comparator import PriceComparator


@pytest.fixture
def woo_service_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def scraper_service_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def cache_service_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def settings_mock() -> MagicMock:
    mock = MagicMock()
    mock.margin_threshold = 200.0
    return mock


@pytest.fixture
def price_comparator(
    woo_service_mock: AsyncMock,
    scraper_service_mock: AsyncMock,
    cache_service_mock: AsyncMock,
    settings_mock: MagicMock,
) -> PriceComparator:
    return PriceComparator(
        woo_service=woo_service_mock,
        scraper_service=scraper_service_mock,
        cache_service=cache_service_mock,
        settings=settings_mock,
    )


# --- 1. Тестування мапінгу статусів наявності (map_availability) ---


@pytest.mark.parametrize(
    ("dc_status", "expected"),
    [
        ("skladom", "В наявності (доставка 3-5 днів)"),
        ("Tovar je ihneď k odberu", "В наявності (доставка 3-5 днів)"),
        ("po objednaní", "В наявності (доставка 3-5 днів)"),
        ("Dostupné na objednávku", "Під замовлення (14-21 днів)"),
        ("aktuálne nedostupné", "Немає в наявності"),
        ("Neznámy status", "Уточнюється у постачальника"),
        ("", "Уточнюється у постачальника"),
        (None, "Уточнюється у постачальника"),
    ],
)
def test_map_availability(price_comparator: PriceComparator, dc_status: Any, expected: str) -> None:
    assert price_comparator.map_availability(dc_status) == expected


# --- 2. Тестування процесу порівняння цін (compare) ---


@pytest.mark.asyncio
async def test_compare_woo_not_found(
    price_comparator: PriceComparator,
    woo_service_mock: AsyncMock,
    scraper_service_mock: AsyncMock,
    cache_service_mock: AsyncMock,
) -> None:
    """Сценарій 2.1: Товар не знайдено на нашому сайті (WooCommerce)"""
    woo_service_mock.search_product_async.return_value = None

    result = await price_comparator.compare("Unknown Product")

    assert result.product_name == "Unknown Product"
    assert result.woo_price is None
    assert result.datacomp_price_uah is None
    assert result.needs_alert is False

    scraper_service_mock.scrape_datacomp.assert_not_called()
    cache_service_mock.get.assert_not_called()


@pytest.mark.asyncio
async def test_compare_woo_found_no_sku(
    price_comparator: PriceComparator,
    woo_service_mock: AsyncMock,
    scraper_service_mock: AsyncMock,
    cache_service_mock: AsyncMock,
) -> None:
    """Сценарій 2.2: Товар знайдено на Woo, але без SKU"""
    woo_mock_result = MagicMock()
    woo_mock_result.sku = ""
    woo_mock_result.name = "Test Product"
    woo_mock_result.price_uah = 1000.0
    woo_mock_result.url = "http://test"
    woo_mock_result.attributes = []
    woo_mock_result.short_description = ""
    woo_service_mock.search_product_async.return_value = woo_mock_result

    result = await price_comparator.compare("Test Product")

    assert result.needs_alert is True
    assert result.alert_reason == "scraper_failed_no_sku"
    assert result.availability_status == "Уточнюється у постачальника"

    scraper_service_mock.scrape_datacomp.assert_not_called()
    cache_service_mock.get.assert_not_called()


@pytest.mark.asyncio
async def test_compare_cache_hit(
    price_comparator: PriceComparator,
    woo_service_mock: AsyncMock,
    scraper_service_mock: AsyncMock,
    cache_service_mock: AsyncMock,
) -> None:
    """Сценарій 2.3: Кеш-хіт (Cache Hit) для звичайного пошуку"""
    woo_mock_result = MagicMock()
    woo_mock_result.sku = "123"
    woo_mock_result.name = "Test Product"
    woo_mock_result.price_uah = 1000.0
    woo_service_mock.search_product_async.return_value = woo_mock_result

    cache_entry = MagicMock()
    cache_entry.is_expired.return_value = False
    cache_entry.price_uah = 700.0
    cache_entry.availability_status = "skladom"
    cache_service_mock.get.return_value = cache_entry

    result = await price_comparator.compare("Test Product", is_checkout=False)

    scraper_service_mock.scrape_datacomp.assert_not_called()
    assert result.datacomp_price_uah == 700.0
    assert result.availability_status == "В наявності (доставка 3-5 днів)"
    assert result.needs_alert is False  # 1000 - 700 = 300 > 200 (threshold)


@pytest.mark.asyncio
async def test_compare_checkout_forces_scrape(
    price_comparator: PriceComparator,
    woo_service_mock: AsyncMock,
    scraper_service_mock: AsyncMock,
    cache_service_mock: AsyncMock,
) -> None:
    """Сценарій 2.4: Пробивання кешу при оформленні замовлення (Checkout)"""
    woo_mock_result = MagicMock()
    woo_mock_result.sku = "123"
    woo_mock_result.name = "Test Product"
    woo_mock_result.price_uah = 1000.0
    woo_service_mock.search_product_async.return_value = woo_mock_result

    cache_entry = MagicMock()
    cache_entry.is_expired.return_value = False
    cache_service_mock.get.return_value = cache_entry

    scrape_result = DatacompProduct(
        name="Datacomp Product",
        price_eur=20.0,
        price_uah=750.0,
        availability_status="na objednávku",
        url="http://datacomp",
    )
    scraper_service_mock.scrape_datacomp.return_value = scrape_result

    result = await price_comparator.compare("Test Product", is_checkout=True)

    scraper_service_mock.scrape_datacomp.assert_called_once_with("123")
    cache_service_mock.set.assert_called_once()
    assert result.datacomp_price_uah == 750.0
    assert result.availability_status == "Під замовлення (14-21 днів)"
    assert result.needs_alert is False  # 1000 - 750 = 250 > 200


@pytest.mark.asyncio
async def test_compare_margin_ok(
    price_comparator: PriceComparator,
    woo_service_mock: AsyncMock,
    scraper_service_mock: AsyncMock,
    cache_service_mock: AsyncMock,
) -> None:
    """Сценарій 2.5: Перевірка маржі — маржа в нормі"""
    woo_mock_result = MagicMock()
    woo_mock_result.sku = "123"
    woo_mock_result.price_uah = 1000.0
    woo_service_mock.search_product_async.return_value = woo_mock_result

    cache_service_mock.get.return_value = None
    scrape_result = DatacompProduct(
        name="P",
        price_eur=20.0,
        price_uah=750.0,
        availability_status="skladom",
        url="",
    )
    scraper_service_mock.scrape_datacomp.return_value = scrape_result

    result = await price_comparator.compare("Test Product")

    assert result.needs_alert is False
    assert result.alert_reason is None


@pytest.mark.asyncio
async def test_compare_low_margin(
    price_comparator: PriceComparator,
    woo_service_mock: AsyncMock,
    scraper_service_mock: AsyncMock,
    cache_service_mock: AsyncMock,
) -> None:
    """Сценарій 2.6: Перевірка маржі — низька маржа (Low Margin)"""
    woo_mock_result = MagicMock()
    woo_mock_result.sku = "123"
    woo_mock_result.price_uah = 1000.0
    woo_service_mock.search_product_async.return_value = woo_mock_result

    cache_service_mock.get.return_value = None
    # 1000 - 900 = 100 < 200
    scrape_result = DatacompProduct(
        name="P",
        price_eur=20.0,
        price_uah=900.0,
        availability_status="skladom",
        url="",
    )
    scraper_service_mock.scrape_datacomp.return_value = scrape_result

    result = await price_comparator.compare("Test Product", is_checkout=False)

    assert result.needs_alert is True
    assert result.alert_reason == "low_margin"
    cache_service_mock.invalidate.assert_called_once_with("123")


@pytest.mark.asyncio
async def test_compare_checkout_margin_issue(
    price_comparator: PriceComparator,
    woo_service_mock: AsyncMock,
    scraper_service_mock: AsyncMock,
    cache_service_mock: AsyncMock,
) -> None:
    """Сценарій 2.7: Перевірка маржі під час Checkout — проблема з маржею"""
    woo_mock_result = MagicMock()
    woo_mock_result.sku = "123"
    woo_mock_result.price_uah = 1000.0
    woo_service_mock.search_product_async.return_value = woo_mock_result

    cache_service_mock.get.return_value = None
    scrape_result = DatacompProduct(
        name="P",
        price_eur=20.0,
        price_uah=900.0,
        availability_status="skladom",
        url="",
    )
    scraper_service_mock.scrape_datacomp.return_value = scrape_result

    result = await price_comparator.compare("Test Product", is_checkout=True)

    assert result.needs_alert is True
    assert result.alert_reason == "checkout_margin_issue"
    cache_service_mock.invalidate.assert_called_once_with("123")


@pytest.mark.asyncio
async def test_compare_scraper_failed(
    price_comparator: PriceComparator,
    woo_service_mock: AsyncMock,
    scraper_service_mock: AsyncMock,
    cache_service_mock: AsyncMock,
) -> None:
    """Сценарій 2.8: Помилка скрапера (Scraper Failed)"""
    woo_mock_result = MagicMock()
    woo_mock_result.sku = "123"
    woo_mock_result.price_uah = 1000.0
    woo_service_mock.search_product_async.return_value = woo_mock_result

    cache_service_mock.get.return_value = None
    scraper_service_mock.scrape_datacomp.return_value = None

    result = await price_comparator.compare("Test Product")

    assert result.datacomp_price_uah is None
    assert result.needs_alert is True
    assert result.alert_reason == "scraper_failed"
