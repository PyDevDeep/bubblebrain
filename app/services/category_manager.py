import asyncio
import csv
import os
from typing import Any

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class CategoryManager:
    def __init__(self, csv_path: str = "data/categories.csv"):
        self.csv_path = csv_path
        self._categories_map: dict[str, int] = {}
        self._categories_list_str: str = ""
        self._last_mtime: float = 0.0

    async def initialize(self) -> None:
        await self._load_categories()

    async def _load_categories(self) -> None:
        """Перевіряє дату зміни файлу і безпечно оновлює кеш."""
        if not await asyncio.to_thread(os.path.exists, self.csv_path):
            logger.warning("Category CSV not found", path=self.csv_path)
            return

        try:
            mtime = await asyncio.to_thread(os.path.getmtime, self.csv_path)
            if mtime <= self._last_mtime:
                return  # Файл не змінювався

            new_map: dict[str, int] = {}
            new_list: list[str] = []

            def _read_csv() -> list[dict[str, Any]]:
                rows: list[dict[str, Any]] = []
                with open(self.csv_path, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # type: ignore is used to suppress Pylance reportUnknownArgumentType for row
                        rows.append(dict(row))  # type: ignore
                return rows

            rows: list[dict[str, Any]] = await asyncio.to_thread(_read_csv)
            for row in rows:
                # Очікувані колонки: ID, Name, Slug, Parent ID, Count
                try:
                    count = int(row.get("Count", 0))
                    if count > 0:
                        cat_id = int(row["ID"])
                        name = row["Name"].strip()
                        new_map[name.lower()] = cat_id
                        new_list.append(name)
                except (ValueError, KeyError):
                    continue

            # Оновлюємо стан тільки якщо парсинг пройшов успішно і є дані
            if new_map:
                self._categories_map = new_map
                self._categories_list_str = ", ".join(new_list)
                self._last_mtime = mtime
                logger.info(
                    "Hot-reloaded categories", count=len(self._categories_map), path=self.csv_path
                )

        except Exception as e:
            logger.error(
                "Failed to load categories, keeping old cache", path=self.csv_path, error=str(e)
            )
            # Не обнуляємо старий кеш, просто логуємо помилку (запобігання Race Condition)

    async def get_categories_string(self) -> str:
        """Повертає рядок категорій для ін'єкції в промпт LLM."""
        await self._load_categories()  # Hot reload перевірка
        return self._categories_list_str

    async def get_category_id(self, name: str) -> int | None:
        """Повертає ID категорії за назвою (case-insensitive)."""
        await self._load_categories()  # Hot reload перевірка
        if not name:
            return None
        return self._categories_map.get(name.strip().lower())
