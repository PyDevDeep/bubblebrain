import asyncio
import csv

from anyio import Path as AnyioPath

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class CategoryManager:
    def __init__(self, csv_path: str = "data/categories.csv"):
        self.csv_path = csv_path
        self._categories_map: dict[str, int] = {}
        self._categories_list_str: str = ""
        self._last_mtime: float = 0.0
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initializes the category manager by loading categories."""
        await self._load_categories()

    async def _load_categories(self) -> None:
        """Checks the file modification date and safely updates the cache."""
        csv_path_obj = AnyioPath(self.csv_path)
        if not await csv_path_obj.exists():
            logger.warning(
                "Category CSV not found, attempting to fetch from WooCommerce...",
                path=self.csv_path,
            )
            try:
                from scripts.export_categories import export_categories_to_csv

                await export_categories_to_csv()
            except Exception as e:
                logger.error("Failed to automatically export categories", error=str(e))

            if not await csv_path_obj.exists():
                logger.error(
                    "Category CSV still not found after export attempt.", path=self.csv_path
                )
                return

        try:
            stat = await csv_path_obj.stat()
            mtime = stat.st_mtime
            if mtime <= self._last_mtime:
                return  # File hasn't changed

            def _read_and_parse_csv() -> tuple[dict[str, int], list[str], int]:
                new_map: dict[str, int] = {}
                new_list: list[str] = []
                skipped_rows = 0

                with open(self.csv_path, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            count = int(row.get("Count", 0))
                            if count > 0:
                                cat_id = int(row["ID"])
                                name = row["Name"].strip()
                                new_map[name.lower()] = cat_id
                                new_list.append(name)
                        except (ValueError, KeyError, TypeError):
                            skipped_rows += 1
                            continue
                return new_map, new_list, skipped_rows

            new_map, new_list, skipped_rows = await asyncio.to_thread(_read_and_parse_csv)

            if new_map:
                async with self._lock:
                    if mtime > self._last_mtime:
                        self._categories_map = new_map
                        self._categories_list_str = ", ".join(new_list)
                        self._last_mtime = mtime
                logger.info(
                    "Hot-reloaded categories",
                    count=len(self._categories_map),
                    skipped_rows=skipped_rows,
                    path=self.csv_path,
                )

        except Exception as e:
            logger.error(
                "Failed to load categories, keeping old cache", path=self.csv_path, error=str(e)
            )

    async def get_categories_string(self) -> str:
        """Returns a string of categories for injection into the LLM prompt."""
        await self._load_categories()  # Hot reload check
        return self._categories_list_str

    async def get_category_id(self, name: str) -> int | None:
        """Returns the category ID by name (case-insensitive)."""
        await self._load_categories()  # Hot reload check
        if not name:
            return None
        return self._categories_map.get(name.strip().lower())
