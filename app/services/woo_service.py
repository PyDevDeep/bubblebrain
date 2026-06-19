import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.schemas.scraper import WooProduct
from app.services.woo_smart_parser import parse_product

logger = get_logger(__name__)

_global_client: httpx.AsyncClient | None = None


async def close_woo_client() -> None:
    """Close the global WooCommerce HTTP client."""
    global _global_client
    if _global_client is not None:
        await _global_client.aclose()
        _global_client = None


class WooService:
    def __init__(self, settings: Settings) -> None:
        """Initialize WooService with settings."""
        self.woo_ck = settings.woo_ck
        self.woo_cs = settings.woo_cs
        self.base_url = f"{settings.woo_url.rstrip('/')}/wp-json/wc/v3/products"
        # Increased timeout due to slow WooCommerce search
        self.timeout = httpx.Timeout(15.0, connect=3.0)

    def _get_client(self) -> httpx.AsyncClient:
        global _global_client
        if _global_client is None:
            _global_client = httpx.AsyncClient()
        return _global_client

    def _parse_product_list(self, data: list[dict[str, Any]]) -> list[WooProduct]:
        """Parse a list of raw WooCommerce products into a list of WooProduct."""
        products: list[WooProduct] = []
        for raw_item in data:
            parsed = parse_product(raw_item)
            if parsed.get("price"):
                products.append(
                    WooProduct(
                        sku=str(parsed.get("sku") or ""),
                        name=str(parsed.get("name") or ""),
                        price_uah=float(parsed.get("price") or 0.0),
                        url=str(raw_item.get("permalink") or ""),
                        stock_status=str(raw_item.get("stock_status") or "instock"),
                        attributes=parsed.get("attributes", {}),
                        short_description=parsed.get("short_description"),
                        categories=parsed.get("categories", []),
                    )
                )
        return products

    async def _fetch_and_parse_single(self, params: dict[str, str | int]) -> WooProduct | None:
        """Fetch and parse a single product from WooCommerce."""
        client = self._get_client()
        try:
            resp = await client.get(
                self.base_url, params=params, auth=(self.woo_ck, self.woo_cs), timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                items = cast(list[dict[str, Any]], data)
                if items:
                    item = items[0]
                    parsed = await asyncio.to_thread(parse_product, item)
                    if parsed.get("price"):
                        return WooProduct(
                            sku=str(parsed.get("sku") or ""),
                            name=str(parsed.get("name") or ""),
                            price_uah=float(parsed.get("price") or 0.0),
                            url=str(item.get("permalink") or ""),
                            stock_status=str(item.get("stock_status") or "instock"),
                            attributes=parsed.get("attributes", {}),
                            short_description=parsed.get("short_description"),
                            categories=parsed.get("categories", []),
                        )
        except Exception as e:
            logger.error("WooCommerce API Single Search Error", error=str(e), params=params)
        return None

    async def _fetch_products_list(self, params: dict[str, Any], context: str) -> list[WooProduct]:
        """Helper to fetch and parse a list of products."""
        client = self._get_client()
        products: list[WooProduct] = []
        try:
            resp = await client.get(
                self.base_url, params=params, auth=(self.woo_ck, self.woo_cs), timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                products = await asyncio.to_thread(
                    self._parse_product_list, cast(list[dict[str, Any]], data)
                )
        except httpx.TimeoutException:
            logger.error(f"WooCommerce API {context} Timeout", params=params)
        except httpx.HTTPStatusError as e:
            logger.error(
                f"WooCommerce API {context} HTTP Status Error", error=str(e), params=params
            )
        except httpx.RequestError as e:
            logger.error(f"WooCommerce API {context} Request Error", error=str(e), params=params)
        except Exception as e:
            logger.error(f"WooCommerce API {context} Unexpected Error", error=str(e), params=params)

        return products

    async def search_product_async(
        self, search_term: str, category_id: int | None = None
    ) -> WooProduct | None:
        """Asynchronous product search in WooCommerce by name or SKU."""
        params: dict[str, str | int] = {
            "search": search_term,
            "per_page": 1,
        }
        if category_id is not None:
            params["category"] = category_id

        result = await self._fetch_and_parse_single(params)
        if result:
            return result

        params_sku: dict[str, str | int] = params.copy()
        params_sku.pop("search", None)
        params_sku["sku"] = search_term

        return await self._fetch_and_parse_single(params_sku)

    async def search_products_async(
        self, search_term: str, category_id: int | None = None, limit: int = 5
    ) -> list[WooProduct]:
        """Asynchronous search for multiple products in WooCommerce by name."""
        params: dict[str, str | int] = {
            "search": search_term,
            "per_page": limit,
        }
        if category_id is not None:
            params["category"] = category_id

        return await self._fetch_products_list(params, "Multi Search")

    async def search_products_by_category_async(
        self, category_id: int, limit: int = 5
    ) -> list[WooProduct]:
        """Asynchronous search for multiple products in WooCommerce by category ID."""
        params: dict[str, str | int] = {
            "category": category_id,
            "per_page": limit,
        }
        return await self._fetch_products_list(params, "Category Search")

    async def get_daily_orders_stats(self) -> dict[str, Any]:
        """Gets order statistics for the last 24 hours."""
        after_date = (datetime.now(UTC) - timedelta(days=1)).isoformat()

        params: dict[str, str | int] = {
            "after": after_date,
            "per_page": 100,
        }

        total = 0
        processing = 0
        on_hold = 0
        completed = 0
        paid = 0
        tags: dict[str, int] = {}

        orders_url = self.base_url.replace("/products", "/orders")
        client = self._get_client()

        try:
            resp = await client.get(
                orders_url, params=params, auth=(self.woo_ck, self.woo_cs), timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                orders = cast(list[dict[str, Any]], data)
                total = len(orders)
                for order in orders:
                    status = str(order.get("status", ""))
                    if status == "processing":
                        processing += 1
                    elif status == "on-hold":
                        on_hold += 1
                    elif status == "completed":
                        completed += 1
                        paid += 1

                    # Parsing tags from meta_data (e.g., utm_source)
                    meta_data_raw = order.get("meta_data", [])
                    if isinstance(meta_data_raw, list):
                        meta_data = cast(list[dict[str, Any]], meta_data_raw)
                        for meta in meta_data:
                            key = str(meta.get("key", ""))
                            if key in ("utm_source", "source", "bot_tag", "created_via"):
                                val = str(meta.get("value", "")).strip().lower()
                                if val:
                                    tags[val] = tags.get(val, 0) + 1
        except Exception as e:
            logger.error("WooCommerce API Orders Stats Error", error=str(e))

        return {
            "total": total,
            "processing": processing,
            "on-hold": on_hold,
            "completed": completed,
            "paid": paid,
            "tags": tags,
        }
