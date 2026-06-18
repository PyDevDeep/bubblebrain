import asyncio
import csv
import os
import sys
from pathlib import Path
from typing import Any

import httpx

# Add the project root to sys.path to import app modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Path initialization is moved to the module level
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "categories.csv"
TEMP_FILE = OUTPUT_DIR / "categories_temp.csv"


def _write_csv_sync(categories: list[dict[str, Any]]) -> None:
    """Synchronous file writing function for execution in a separate thread."""
    fieldnames = ["ID", "Name", "Slug", "Parent ID", "Count"]

    try:
        with open(TEMP_FILE, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for cat in categories:
                writer.writerow(
                    {
                        "ID": cat.get("id", ""),
                        "Name": cat.get("name", ""),
                        "Slug": cat.get("slug", ""),
                        "Parent ID": cat.get("parent", ""),
                        "Count": cat.get("count", ""),
                    }
                )
        # Atomic file replacement
        os.replace(TEMP_FILE, OUTPUT_FILE)
        logger.info(f"Успішно експортовано {len(categories)} категорій у файл {OUTPUT_FILE}")
    except Exception as e:
        logger.error(f"Помилка під час запису у файл: {e}")
        if TEMP_FILE.exists():
            TEMP_FILE.unlink(missing_ok=True)


async def export_categories_to_csv() -> None:
    """Asynchronously export categories from WooCommerce to a CSV file."""
    settings = get_settings()
    base_url = f"{settings.woo_url.rstrip('/')}/wp-json/wc/v3/products/categories"

    categories: list[dict[str, Any]] = []
    page = 1
    per_page = 100

    # API request timeout
    timeout = httpx.Timeout(10.0, connect=3.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            params: dict[str, str | int] = {
                "consumer_key": settings.woo_ck,
                "consumer_secret": settings.woo_cs,
                "per_page": per_page,
                "page": page,
            }
            logger.info(f"Отримання сторінки {page} категорій...")
            try:
                resp = await client.get(base_url, params=params)
                resp.raise_for_status()
                data = resp.json()

                if not data:
                    break

                categories.extend(data)

                # If the number of returned categories is less than per_page,
                # it means this is the last page
                if len(data) < per_page:
                    break

                page += 1
            except Exception as e:
                logger.error(
                    f"Критична помилка під час отримання сторінки {page}: {e}. Дамп скасовано для збереження цілісності."
                )
                return

    if not categories:
        logger.warning("Категорії не знайдено, дамп скасовано.")
        return

    # Asynchronous call of synchronous I/O in a separate thread (Event Loop protection)
    await asyncio.to_thread(_write_csv_sync, categories)


if __name__ == "__main__":
    asyncio.run(export_categories_to_csv())
