import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.schemas.cache import CacheEntry
from app.services.cache_service import CacheService


@pytest.mark.asyncio
async def test_cache_service_flow(mock_settings):
    service = CacheService(mock_settings)

    # Test initialization
    await service.initialize()

    # Test get missing
    entry = await service.get("unknown_sku")
    assert entry is None

    # Test set
    now = datetime.now(UTC)
    new_entry = CacheEntry(
        sku="TEST_SKU",
        product_name="Test Product",
        price_eur=100.0,
        price_uah=4000.0,
        availability_status="in_stock",
        delivery_time_description="1-2 days",
        updated_at=now,
    )
    await service.set(new_entry)

    # Test get existing
    fetched = await service.get("TEST_SKU")
    assert fetched is not None
    assert fetched.sku == "TEST_SKU"
    assert fetched.product_name == "Test Product"
    assert fetched.price_eur == 100.0

    # Test invalidate
    await service.invalidate("TEST_SKU")
    fetched_after_delete = await service.get("TEST_SKU")
    assert fetched_after_delete is None


@pytest.mark.asyncio
async def test_purge_expired(mock_settings):
    service = CacheService(mock_settings)
    await service.initialize()

    # Insert old record manually to bypass `set` updating `updated_at` to now
    old_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    import aiosqlite

    async with aiosqlite.connect(service.db_path) as db:
        await db.execute(
            "INSERT INTO product_cache (sku, product_name, price_eur, price_uah, availability_status, delivery_time_description, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("OLD_SKU", "Old", 10.0, 400.0, "in_stock", "now", old_date),
        )
        await db.commit()

    deleted_count = await service.purge_expired()
    assert deleted_count == 1

    fetched = await service.get("OLD_SKU")
    assert fetched is None


@pytest.mark.asyncio
@patch("app.services.cache_service.aiosqlite.connect")
async def test_cache_service_error_handling(mock_connect, mock_settings):
    # Setup mock to raise error
    mock_connect.side_effect = sqlite3.Error("Mock DB Error")
    service = CacheService(mock_settings)

    # None of these should throw exceptions, they catch and log
    await service.initialize()
    res = await service.get("TEST")
    assert res is None

    await service.set(
        CacheEntry(
            sku="1",
            product_name="1",
            price_eur=1.0,
            price_uah=1.0,
            availability_status="1",
            delivery_time_description="1",
            updated_at=datetime.now(UTC),
        )
    )

    await service.invalidate("TEST")

    deleted = await service.purge_expired()
    assert deleted == 0
