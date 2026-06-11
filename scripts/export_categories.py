import asyncio
import csv
import sys
from pathlib import Path
from typing import Any

import httpx

# Додаємо корінь проекту до sys.path для імпорту модулів app
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


# Ініціалізацію шляхів винесено на рівень модуля
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "categories.csv"


async def export_categories_to_csv():
    settings = get_settings()
    base_url = "https://digitaldreams.com.ua/wp-json/wc/v3/products/categories"

    categories: list[dict[str, Any]] = []
    page = 1
    per_page = 100

    # Таймаут для запитів до API
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

                # Якщо кількість повернутих категорій менша за per_page,
                # значить це остання сторінка
                if len(data) < per_page:
                    break

                page += 1
            except Exception as e:
                logger.error(f"Помилка під час отримання сторінки {page}: {e}")
                break

    if not categories:
        logger.warning("Категорії не знайдено або сталася помилка.")
        return

    # Запис у CSV
    fieldnames = ["ID", "Name", "Slug", "Parent ID", "Count"]

    try:
        with open(OUTPUT_FILE, mode="w", newline="", encoding="utf-8") as f:  # noqa: ASYNC230
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
        logger.info(f"Успішно експортовано {len(categories)} категорій у файл {OUTPUT_FILE}")
    except Exception as e:
        logger.error(f"Помилка під час запису у файл: {e}")


if __name__ == "__main__":
    asyncio.run(export_categories_to_csv())
