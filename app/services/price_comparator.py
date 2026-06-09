from datetime import UTC, datetime

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.schemas.cache import CacheEntry
from app.schemas.scraper import PriceComparisonResult
from app.services.cache_service import CacheService
from app.services.scraper_service import ScraperService
from app.services.woo_service import WooService

logger = get_logger(__name__)


class PriceComparator:
    def __init__(
        self,
        woo_service: WooService,
        scraper_service: ScraperService,
        cache_service: CacheService,
        settings: Settings,
    ) -> None:
        self.woo_service = woo_service
        self.scraper_service = scraper_service
        self.cache_service = cache_service
        self.margin_threshold = settings.margin_threshold

    def map_availability(self, dc_status: str) -> str:
        s = dc_status.lower() if dc_status else ""
        if "ihneď" in s or "skladom" in s:
            return "В наявності (відправка 3-5 днів)"
        elif "objednávku" in s:
            return "Під замовлення від постачальника (доставка 14-20 днів)"
        return "Уточнюється у постачальника"

    async def compare(self, product_name: str) -> PriceComparisonResult:
        logger.info("Starting price comparison", product=product_name)

        # 1. Завжди спочатку перевіряємо наш магазин (WooCommerce)
        woo_result = await self.woo_service.search_product_async(product_name)

        if not woo_result:
            # Якщо товару взагалі немає на сайті, ми не гадаємо, а просто кажемо, що його немає.
            return PriceComparisonResult(
                product_name=product_name,
                woo_price=None,
                datacomp_price_uah=None,
                needs_alert=False,
            )

        sku = woo_result.sku
        woo_stock = getattr(woo_result, "stock_status", "instock")

        # 2. Якщо товар в наявності у нас - ВІДРАЗУ ВІДДАЄМО, НІЯКОГО DATACOMP
        if woo_stock == "instock":
            logger.info("Product is instock on Woo, skipping Datacomp", sku=sku)
            return PriceComparisonResult(
                product_name=woo_result.name,
                woo_price=woo_result.price_uah,
                datacomp_price_uah=None,
                availability_status="В наявності (відправка 1-3 дні)",
                diff_woo_uah=None,
                needs_alert=False,
                datacomp_url=None,
                woo_url=woo_result.url,
            )

        # 3. Товар "outofstock" -> Перевіряємо постачальника (Datacomp) ТІЛЬКИ по SKU
        if not sku:
            logger.error(
                "Product is outofstock but has no SKU to check supplier", product=woo_result.name
            )
            return PriceComparisonResult(
                product_name=woo_result.name,
                woo_price=woo_result.price_uah,
                datacomp_price_uah=None,
                availability_status="Уточнюється у постачальника",
                needs_alert=True,
                alert_reason="scraper_failed_no_sku",
                woo_url=woo_result.url,
            )

        dc_price_uah = None
        dc_availability_raw = ""
        dc_url = None

        cache_entry = await self.cache_service.get(sku)
        if cache_entry and not cache_entry.is_expired(self.cache_service.ttl_days):
            logger.info("Cache HIT", sku=sku)
            dc_price_uah = cache_entry.price_uah
            dc_availability_raw = cache_entry.availability_status
        else:
            logger.info("Cache MISS or EXPIRED, scraping Datacomp by SKU", sku=sku)
            dc_result = await self.scraper_service.scrape_datacomp(sku)

            if dc_result:
                dc_price_uah = dc_result.price_uah
                dc_availability_raw = dc_result.availability_status
                dc_url = dc_result.url

                if dc_price_uah:
                    new_entry = CacheEntry(
                        sku=sku,
                        product_name=woo_result.name,
                        price_eur=dc_result.price_eur or 0.0,
                        price_uah=dc_price_uah,
                        availability_status=dc_availability_raw,
                        delivery_time_description="Авто",
                        updated_at=datetime.now(UTC),
                    )
                    await self.cache_service.set(new_entry)

        # 4. Аналізуємо маржу для товарів від постачальника
        mapped_availability = "Під замовлення від постачальника (доставка 14-20 днів)"
        diff_woo = None
        needs_alert = False
        alert_reason = None

        if woo_result.price_uah and dc_price_uah:
            diff_woo = round(woo_result.price_uah - dc_price_uah, 2)

            if diff_woo < self.margin_threshold:
                needs_alert = True
                alert_reason = "low_margin"
                await self.cache_service.invalidate(sku)

        elif woo_result.price_uah and not dc_price_uah:
            needs_alert = True
            alert_reason = "scraper_failed"

        return PriceComparisonResult(
            product_name=woo_result.name,
            woo_price=woo_result.price_uah,
            datacomp_price_uah=dc_price_uah,
            availability_status=mapped_availability,
            diff_woo_uah=diff_woo,
            needs_alert=needs_alert,
            alert_reason=alert_reason,
            datacomp_url=dc_url,
            woo_url=woo_result.url,
        )
