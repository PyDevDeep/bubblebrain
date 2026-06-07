from typing import Any, cast

import httpx

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.schemas.scraper import WooProduct

logger = get_logger(__name__)


class WooService:
    def __init__(self, settings: Settings) -> None:
        self.woo_ck = settings.woo_ck
        self.woo_cs = settings.woo_cs
        self.base_url = "https://digitaldreams.com.ua/wp-json/wc/v3/products"

    async def search_product_async(self, search_term: str) -> WooProduct | None:
        """Асинхронний пошук товару у WooCommerce за назвою або SKU."""
        params: dict[str, str | int] = {
            "search": search_term,
            "consumer_key": self.woo_ck,
            "consumer_secret": self.woo_cs,
            "per_page": 1,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(self.base_url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and len(data) > 0 and data[0].get("price"):
                        return WooProduct(
                            sku=data[0].get("sku", ""),
                            name=data[0].get("name", ""),
                            price_uah=float(data[0]["price"]),
                            url=data[0].get("permalink", ""),
                            stock_status=data[0].get("stock_status", "instock"),
                        )

                params_sku: dict[str, str | int] = params.copy()
                params_sku.pop("search", None)
                params_sku["sku"] = search_term

                resp_sku = await client.get(self.base_url, params=params_sku)
                if resp_sku.status_code == 200:
                    data_sku = resp_sku.json()
                    if data_sku and len(data_sku) > 0 and data_sku[0].get("price"):
                        return WooProduct(
                            sku=data_sku[0].get("sku", ""),
                            name=data_sku[0].get("name", ""),
                            price_uah=float(data_sku[0]["price"]),
                            url=data_sku[0].get("permalink", ""),
                            stock_status=data_sku[0].get("stock_status", "instock"),
                        )
            except httpx.RequestError as e:
                logger.error("WooCommerce API Error", error=str(e), search_term=search_term)

        return None

    async def search_products_async(self, search_term: str, limit: int = 5) -> list[WooProduct]:
        """Асинхронний пошук кількох товарів у WooCommerce за назвою."""
        params: dict[str, str | int] = {
            "search": search_term,
            "consumer_key": self.woo_ck,
            "consumer_secret": self.woo_cs,
            "per_page": limit,
        }

        products: list[WooProduct] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(self.base_url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        for raw_item in cast(list[dict[str, Any]], data):
                            if raw_item.get("price"):
                                products.append(
                                    WooProduct(
                                        sku=str(raw_item.get("sku") or ""),
                                        name=str(raw_item.get("name") or ""),
                                        price_uah=float(raw_item.get("price") or 0.0),
                                        url=str(raw_item.get("permalink") or ""),
                                        stock_status=str(raw_item.get("stock_status") or "instock"),
                                    )
                                )
            except httpx.RequestError as e:
                logger.error(
                    "WooCommerce API Multi Search Error",
                    error=str(e),
                    search_term=search_term,
                )

        return products
