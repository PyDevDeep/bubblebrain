import asyncio
from typing import Any, cast

import httpx

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.schemas.scraper import WooProduct
from app.services.woo_smart_parser import parse_product

logger = get_logger(__name__)


class WooService:
    def __init__(self, settings: Settings) -> None:
        self.woo_ck = settings.woo_ck
        self.woo_cs = settings.woo_cs
        self.base_url = f"{settings.woo_url.rstrip('/')}/wp-json/wc/v3/products"
        # Збільшено таймаут через повільний пошук WooCommerce
        self.timeout = httpx.Timeout(15.0, connect=3.0)

    def _parse_product_list(self, data: list[dict[str, Any]]) -> list[WooProduct]:
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
                    )
                )
        return products

    async def _fetch_and_parse_single(
        self, client: httpx.AsyncClient, params: dict[str, str | int]
    ) -> WooProduct | None:
        resp = await client.get(self.base_url, params=params)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                parsed = await asyncio.to_thread(parse_product, data[0])
                if parsed.get("price"):
                    return WooProduct(
                        sku=str(parsed.get("sku") or ""),
                        name=str(parsed.get("name") or ""),
                        price_uah=float(parsed.get("price") or 0.0),
                        url=str(data[0].get("permalink") or ""),
                        stock_status=str(data[0].get("stock_status") or "instock"),
                        attributes=parsed.get("attributes", {}),
                        short_description=parsed.get("short_description"),
                    )
        return None

    async def search_product_async(
        self, search_term: str, category_id: int | None = None
    ) -> WooProduct | None:
        """Асинхронний пошук товару у WooCommerce за назвою або SKU."""
        params: dict[str, str | int] = {
            "search": search_term,
            "consumer_key": self.woo_ck,
            "consumer_secret": self.woo_cs,
            "per_page": 1,
        }
        if category_id is not None:
            params["category"] = category_id

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                result = await self._fetch_and_parse_single(client, params)
                if result:
                    return result

                params_sku: dict[str, str | int] = params.copy()
                params_sku.pop("search", None)
                params_sku["sku"] = search_term

                return await self._fetch_and_parse_single(client, params_sku)
            except httpx.TimeoutException:
                logger.error("WooCommerce API Timeout", search_term=search_term)
            except httpx.RequestError as e:
                logger.error("WooCommerce API Request Error", error=str(e), search_term=search_term)
            except Exception as e:
                logger.error(
                    "WooCommerce API Unexpected Error", error=str(e), search_term=search_term
                )

        return None

    async def search_products_async(
        self, search_term: str, category_id: int | None = None, limit: int = 5
    ) -> list[WooProduct]:
        """Асинхронний пошук кількох товарів у WooCommerce за назвою."""
        params: dict[str, str | int] = {
            "search": search_term,
            "consumer_key": self.woo_ck,
            "consumer_secret": self.woo_cs,
            "per_page": limit,
        }
        if category_id is not None:
            params["category"] = category_id

        products: list[WooProduct] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(self.base_url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        products = await asyncio.to_thread(
                            self._parse_product_list, cast(list[dict[str, Any]], data)
                        )
            except httpx.TimeoutException:
                logger.error("WooCommerce API Multi Search Timeout", search_term=search_term)
            except httpx.RequestError as e:
                logger.error(
                    "WooCommerce API Multi Search Error", error=str(e), search_term=search_term
                )
            except Exception as e:
                logger.error(
                    "WooCommerce API Multi Search Unexpected Error",
                    error=str(e),
                    search_term=search_term,
                )

        return products

    async def search_products_by_category_async(
        self, category_id: int, limit: int = 5
    ) -> list[WooProduct]:
        """Асинхронний пошук кількох товарів у WooCommerce за ID категорії."""
        params: dict[str, str | int] = {
            "category": category_id,
            "consumer_key": self.woo_ck,
            "consumer_secret": self.woo_cs,
            "per_page": limit,
        }

        products: list[WooProduct] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(self.base_url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        products = await asyncio.to_thread(
                            self._parse_product_list, cast(list[dict[str, Any]], data)
                        )
            except httpx.TimeoutException:
                logger.error("WooCommerce API Multi Search Timeout", category_id=category_id)
            except httpx.RequestError as e:
                logger.error(
                    "WooCommerce API Multi Search Error", error=str(e), category_id=category_id
                )
            except Exception as e:
                logger.error(
                    "WooCommerce API Multi Search Unexpected Error",
                    error=str(e),
                    category_id=category_id,
                )

        return products

    async def get_daily_orders_stats(self) -> dict[str, Any]:
        """Отримує статистику замовлень за останні 24 години."""
        from datetime import UTC, datetime, timedelta
        from typing import Any, cast

        after_date = (datetime.now(UTC) - timedelta(days=1)).isoformat()

        params: dict[str, str | int] = {
            "consumer_key": self.woo_ck,
            "consumer_secret": self.woo_cs,
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

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(orders_url, params=params)
                if resp.status_code == 200:
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

                            # Парсинг міток з meta_data (наприклад, utm_source)
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
