from datetime import UTC, datetime

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.core.metrics import price_alerts_total
from app.schemas.cache import CacheEntry
from app.schemas.scraper import PriceComparisonResult
from app.services.cache_service import CacheService
from app.services.scraper_service import ScraperService
from app.services.woo_service import WooService

logger = get_logger(__name__)


class PriceComparator:
    """Comparator for checking product prices against supplier prices."""

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

    def map_availability(self, supp_status: str) -> str:
        """Map supplier availability status to standard text."""
        s = supp_status.lower() if supp_status else ""
        if "skladom" in s or "ihneď k odberu" in s or "po objednaní" in s:
            return "В наявності (доставка 3-5 днів)"
        elif "na objednávku" in s:
            return "Під замовлення (14-21 днів)"
        elif "aktuálne nedostupné" in s:
            return "Немає в наявності"
        return "Уточнюється у постачальника"

    async def compare(
        self, product_name: str, is_checkout: bool = False, category_id: int | None = None
    ) -> PriceComparisonResult:
        """Compare WooCommerce product price with supplier."""
        logger.info(
            "Starting price comparison",
            product=product_name,
            is_checkout=is_checkout,
            category_id=category_id,
        )

        woo_result = await self.woo_service.search_product_async(
            product_name, category_id=category_id
        )

        if not woo_result:
            return PriceComparisonResult(
                product_name=product_name,
                woo_price=None,
                supplier_price_uah=None,
                needs_alert=False,
            )

        sku = woo_result.sku

        import re

        match = re.search(r"\(([^)]+)\)$", woo_result.name.strip())
        if match:
            sku = match.group(1).strip()

        if not sku:
            return PriceComparisonResult(
                product_name=woo_result.name,
                woo_price=woo_result.price_uah,
                supplier_price_uah=None,
                availability_status="Уточнюється у постачальника",
                needs_alert=True,
                alert_reason="scraper_failed_no_sku",
                woo_url=woo_result.url,
                attributes=woo_result.attributes,
                short_description=woo_result.short_description,
            )

        supp_price_uah = None
        supp_availability_raw = ""
        supp_url = None

        cache_entry = await self.cache_service.get(sku)
        # BYPASS CACHE IF IT IS CHECKOUT
        if (
            not is_checkout
            and cache_entry
            and not cache_entry.is_expired(self.cache_service.ttl_days)
        ):
            logger.info("Cache HIT", sku=sku)
            supp_price_uah = cache_entry.price_uah
            supp_availability_raw = cache_entry.availability_status
        else:
            logger.info("Cache MISS or FORCE REFRESH", sku=sku, is_checkout=is_checkout)
            supp_result = await self.scraper_service.scrape_supplier(sku)

            if not supp_result:
                base_name = re.sub(r"\([^)]+\)$", "", woo_result.name).strip()
                words = base_name.split()
                start_idx = 0
                for i, w in enumerate(words):
                    if re.search(r"[A-Za-z]", w):
                        start_idx = i
                        break
                cleaned_name = " ".join(words[start_idx:])

                if cleaned_name and cleaned_name != sku:
                    logger.info(
                        "Fallback scraping by cleaned name", sku=sku, cleaned_name=cleaned_name
                    )
                    supp_result = await self.scraper_service.scrape_supplier(cleaned_name)

            if supp_result:
                supp_price_uah = supp_result.price_uah
                supp_availability_raw = supp_result.availability_status
                supp_url = supp_result.url

                if supp_price_uah:
                    new_entry = CacheEntry(
                        sku=sku,
                        product_name=woo_result.name,
                        price_eur=supp_result.price_eur or 0.0,
                        price_uah=supp_price_uah,
                        availability_status=supp_availability_raw,
                        delivery_time_description="Авто",
                        updated_at=datetime.now(UTC),
                    )
                    await self.cache_service.set(new_entry)

        mapped_availability = self.map_availability(supp_availability_raw)
        diff_woo = None
        needs_alert = False
        alert_reason = None

        if woo_result.price_uah and supp_price_uah:
            diff_woo = round(woo_result.price_uah - supp_price_uah, 2)

            if abs(diff_woo) > self.margin_threshold:
                needs_alert = True
                alert_reason = "checkout_margin_issue" if is_checkout else "low_margin"
                price_alerts_total.inc()
                await self.cache_service.invalidate(sku)

        elif woo_result.price_uah and not supp_price_uah:
            needs_alert = True
            alert_reason = "scraper_failed"
            price_alerts_total.inc()

        return PriceComparisonResult(
            product_name=woo_result.name,
            woo_price=woo_result.price_uah,
            supplier_price_uah=supp_price_uah,
            availability_status=mapped_availability,
            diff_woo_uah=diff_woo,
            needs_alert=needs_alert,
            alert_reason=alert_reason,
            supplier_url=supp_url,
            woo_url=woo_result.url,
            attributes=woo_result.attributes,
            short_description=woo_result.short_description,
        )
