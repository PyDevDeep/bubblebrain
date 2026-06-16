import sqlite3
from datetime import UTC, datetime, timedelta

import aiosqlite

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.schemas.cache import CacheEntry

logger = get_logger(__name__)


class CacheService:
    def __init__(self, settings: Settings) -> None:
        self.db_path = settings.cache_db_path
        self.ttl_days = settings.cache_ttl_days

    async def initialize(self) -> None:
        """Створення таблиці кешу. Якщо файл пошкоджено, він буде перестворений."""
        query = """
        CREATE TABLE IF NOT EXISTS product_cache (
            sku TEXT PRIMARY KEY,
            product_name TEXT NOT NULL,
            price_eur REAL NOT NULL,
            price_uah REAL NOT NULL,
            availability_status TEXT NOT NULL,
            delivery_time_description TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(query)
                await db.commit()
                logger.info("SQLite cache initialized", db_path=self.db_path)
        except sqlite3.Error as e:
            logger.error("Failed to initialize SQLite cache", error=str(e))
            # Не кидаємо exception, дозволяємо додатку працювати без кешу

    async def get(self, sku: str) -> CacheEntry | None:
        """Читання запису з кешу. Перевірка is_expired робиться на рівні виклику."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM product_cache WHERE sku = ?", (sku,)
                ) as cursor:
                    row = await cursor.fetchone()

                    if not row:
                        return None

                    return CacheEntry(
                        sku=row["sku"],
                        product_name=row["product_name"],
                        price_eur=row["price_eur"],
                        price_uah=row["price_uah"],
                        availability_status=row["availability_status"],
                        delivery_time_description=row["delivery_time_description"],
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                    )
        except sqlite3.Error as e:
            # --- ДОДАНО FAILSAFE ---
            if "no such table" in str(e):
                logger.warning("Cache table missing during GET. Initializing...", sku=sku)
                await self.initialize()
            else:
                logger.error("SQLite GET error", error=str(e), sku=sku)
            # -----------------------
            return None

    async def set(self, entry: CacheEntry) -> None:
        """Збереження або перезапис даних для SKU."""
        query = """
        INSERT OR REPLACE INTO product_cache
        (sku, product_name, price_eur, price_uah, availability_status, delivery_time_description, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        updated_at_iso = datetime.now(UTC).isoformat()

        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    query,
                    (
                        entry.sku,
                        entry.product_name,
                        entry.price_eur,
                        entry.price_uah,
                        entry.availability_status,
                        entry.delivery_time_description,
                        updated_at_iso,
                    ),
                )
                await db.commit()
        except sqlite3.Error as e:
            # --- ДОДАНО FAILSAFE ТА РЕТРАЙ ---
            if "no such table" in str(e):
                logger.warning(
                    "Cache table missing during SET. Initializing and retrying...", sku=entry.sku
                )
                await self.initialize()
                await self.set(entry)  # Повторюємо спробу збереження
            else:
                logger.error("SQLite SET error", error=str(e), sku=entry.sku)
            # ---------------------------------

    async def invalidate(self, sku: str) -> None:
        """Примусове видалення запису (наприклад, при аномаліях ціни)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM product_cache WHERE sku = ?", (sku,))
                await db.commit()
        except sqlite3.Error as e:
            logger.error("SQLite INVALIDATE error", error=str(e), sku=sku)

    async def purge_expired(self) -> int:
        """Видалення старих записів. Викликається при старті додатку."""
        cutoff_date = datetime.now(UTC) - timedelta(days=self.ttl_days)
        cutoff_iso = cutoff_date.isoformat()

        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM product_cache WHERE updated_at < ?", (cutoff_iso,)
                )
                deleted_count = cursor.rowcount
                await db.commit()
                return deleted_count
        except sqlite3.Error as e:
            logger.error("SQLite PURGE error", error=str(e))
            return 0
