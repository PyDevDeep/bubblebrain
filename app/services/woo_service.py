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
        self.base_url = "https://digitaldreams.com.ua/wp-json/wc/v3/products"
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
