import csv
import os

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class CategoryManager:
    def __init__(self, csv_path: str = "data/categories.csv"):
        self.csv_path = csv_path
        self._categories_map: dict[str, int] = {}
        self._categories_list_str: str = ""
        self._last_mtime: float = 0.0
        # Ініціалізація при старті
        self._load_categories()

    def _load_categories(self) -> None:
        """Перевіряє дату зміни файлу і безпечно оновлює кеш."""
        if not os.path.exists(self.csv_path):
            logger.warning("Category CSV not found", path=self.csv_path)
            return

        try:
            mtime = os.path.getmtime(self.csv_path)
            if mtime <= self._last_mtime:
                return  # Файл не змінювався

            new_map: dict[str, int] = {}
            new_list: list[str] = []

            with open(self.csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
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

    def get_categories_string(self) -> str:
        """Повертає рядок категорій для ін'єкції в промпт LLM."""
        self._load_categories()  # Hot reload перевірка
        return self._categories_list_str

    def get_category_id(self, name: str) -> int | None:
        """Повертає ID категорії за назвою (case-insensitive)."""
        self._load_categories()  # Hot reload перевірка
        if not name:
            return None
        return self._categories_map.get(name.strip().lower())
