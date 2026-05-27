from datetime import UTC, datetime

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
    ) -> None:
        self.woo_service = woo_service
        self.scraper_service = scraper_service
        self.cache_service = cache_service
        self.margin_threshold = 200.0

    async def compare(self, product_name: str) -> PriceComparisonResult:
        logger.info("Starting price comparison", product=product_name)

        # 1. Шукаємо товар у нас на сайті
        woo_result = await self.woo_service.search_product_async(product_name)

        if not woo_result:
            logger.info("Product not found in WooCommerce", product=product_name)
            return PriceComparisonResult(
                product_name=product_name,
                woo_price=None,
                datacomp_price_uah=None,
                hotline_price_uah=None,
                diff_hotline_uah=None,
                diff_woo_uah=None,
                datacomp_url=None,
                hotline_url=None,
            )

        sku = woo_result.sku
        if not sku:
            sku = woo_result.name.replace(" ", "_").lower()
            logger.warning("Woo product has no SKU, using name as cache key", name=woo_result.name)

        # 2. Перевіряємо SQLite кеш
        dc_price_uah = None
        dc_availability = "Невідомо"
        dc_url = None

        cache_entry = await self.cache_service.get(sku)

        if cache_entry and not cache_entry.is_expired(self.cache_service.ttl_days):
            logger.info("Cache HIT", sku=sku)
            dc_price_uah = cache_entry.price_uah
            dc_availability = cache_entry.availability_status
        else:
            logger.info("Cache MISS or EXPIRED", sku=sku)
            # 3. Кеш пустий -> скрапимо Datacomp
            dc_result = await self.scraper_service.scrape_datacomp(sku)

            if not dc_result and sku != product_name:
                dc_result = await self.scraper_service.scrape_datacomp(product_name)

            if dc_result:
                dc_price_uah = dc_result.price_uah
                dc_availability = dc_result.availability_status
                dc_url = dc_result.url

                # Записуємо свіжі дані в кеш
                if dc_price_uah:
                    new_entry = CacheEntry(
                        sku=sku,
                        product_name=woo_result.name,
                        price_eur=dc_result.price_eur or 0.0,
                        price_uah=dc_price_uah,
                        availability_status=dc_availability,
                        delivery_time_description="Авто",
                        updated_at=datetime.now(UTC),
                    )
                    await self.cache_service.set(new_entry)
            else:
                logger.warning("Scraper returned None", sku=sku)

        # 4. Обчислюємо маржу
        diff_woo = None

        if woo_result.price_uah and dc_price_uah:
            diff_woo = round(woo_result.price_uah - dc_price_uah, 2)

            # Алгоритм: якщо різниця менша 200 грн або мінусова -> тривога
            if diff_woo < self.margin_threshold:
                logger.warning("Low margin detected", sku=sku, margin=diff_woo)
                # Інвалідуємо кеш, бо можливо ціна стрибнула і треба перевірити наступного разу
                await self.cache_service.invalidate(sku)

        # (Hotline скрапінг тут можна викликати фоново або асинхронно, але для швидкості поки пропускаємо,
        # оскільки він потрібен лише для аналітики, а не для відповіді клієнту).

        return PriceComparisonResult(
            product_name=woo_result.name,
            woo_price=woo_result.price_uah,
            datacomp_price_uah=dc_price_uah,
            hotline_price_uah=None,  # Заглушка для швидкодії
            diff_hotline_uah=None,
            diff_woo_uah=diff_woo,
            datacomp_url=dc_url,
            hotline_url=None,
        )
