import html
import logging
from typing import Any

from app.core.config import Settings
from app.core.constants import (
    ALERT_MARGIN_ISSUE,
    ALERT_SCRAPER_FAILED,
    INTENT_CHECKOUT,
    INTENT_SEARCH,
    LINK_CHECKOUT,
    LINK_TELEGRAM,
    LINK_VIBER,
    SEARCH_FOUND_HEADER,
    STATUS_INSTOCK,
    STATUS_OUT_OF_STOCK,
)
from app.schemas.chat import IntentContextResult
from app.services.price_comparator import PriceComparator
from app.services.telegram_service import TelegramService
from app.utils.prompts import (
    INSTR_ALERT_FAILED,
    INSTR_BROAD_SEARCH_FALLBACK,
    INSTR_CHECKOUT_PRICE_ISSUE,
    INSTR_CHECKOUT_TELEGRAM,
    INSTR_DISCOUNT_AVAILABLE,
    INSTR_FALLBACK_CATEGORY,
    INSTR_NO_DUPLICATE_LINKS,
    INSTR_NOTHING_FOUND,
    INSTR_PRICE_CHECKING,
    INSTR_PRODUCT_FOUND,
)

logger = logging.getLogger(__name__)


class ProductCheckoutIntentHandler:
    def __init__(
        self,
        price_comparator: PriceComparator,
        telegram_service: TelegramService,
        settings: Settings,
    ):
        self.price_comparator = price_comparator
        self.telegram_service = telegram_service
        self.settings = settings

    async def handle(
        self,
        intent_type: str,
        product_name: str,
        category_id: int | None,
        system_instructions: list[str],
        product_facts: list[str],
        extracted_links: list[dict[str, str]],
    ) -> IntentContextResult:
        is_checkout = intent_type == INTENT_CHECKOUT
        requires_lead = False
        new_intent_type = intent_type

        logger.info(
            "Product/Checkout intent detected",
            extra={"product": product_name, "is_checkout": is_checkout},
        )

        try:
            result = await self.price_comparator.compare(
                product_name, is_checkout=is_checkout, category_id=category_id
            )
        except Exception:
            logger.exception("Price comparator failed during intent handling")
            return IntentContextResult(
                product_facts=product_facts,
                system_instructions=system_instructions,
                extracted_links=extracted_links,
                requires_lead=requires_lead,
                new_intent_type=INTENT_SEARCH,
            )

        if result.needs_alert:
            requires_lead = True
            safe_product_name = (
                html.escape(str(result.product_name)) if result.product_name else "Unknown Product"
            )

            if result.alert_reason in ["low_margin", "checkout_margin_issue"]:
                msg = ALERT_MARGIN_ISSUE.format(
                    safe_product_name=safe_product_name,
                    woo_price=result.woo_price,
                    datacomp_price=result.datacomp_price_uah,
                    diff_woo=result.diff_woo_uah,
                )
                alert_success = await self.telegram_service.send_alert(msg)

                if not alert_success:
                    system_instructions.append(INSTR_ALERT_FAILED)
                elif is_checkout:
                    system_instructions.append(INSTR_CHECKOUT_PRICE_ISSUE)
                else:
                    system_instructions.append(INSTR_DISCOUNT_AVAILABLE)
            else:
                msg = ALERT_SCRAPER_FAILED.format(safe_product_name=safe_product_name)
                alert_success = await self.telegram_service.send_alert(msg)

                if not alert_success:
                    system_instructions.append(INSTR_ALERT_FAILED)
                else:
                    system_instructions.append(
                        INSTR_PRICE_CHECKING.format(product_name=product_name)
                    )

        elif is_checkout:
            requires_lead = True
            if result.woo_url:
                extracted_links.append({"text": LINK_CHECKOUT, "url": result.woo_url})
            extracted_links.append(
                {"text": LINK_TELEGRAM, "url": self.settings.telegram_contact_url}
            )
            extracted_links.append({"text": LINK_VIBER, "url": self.settings.viber_contact_url})

            system_instructions.append(INSTR_CHECKOUT_TELEGRAM.format(product_name=product_name))

        else:
            if result.woo_price:
                if result.woo_url:
                    extracted_links.append(
                        {"text": f"View {result.product_name}", "url": result.woo_url}
                    )
                system_instructions.append(
                    INSTR_PRODUCT_FOUND.format(product_name=result.product_name)
                )

                status_text = (
                    STATUS_INSTOCK
                    if result.availability_status == "instock"
                    else STATUS_OUT_OF_STOCK
                )
                product_facts.append(
                    f"Data: Product '{result.product_name}', {result.woo_price} UAH. Conditions: {status_text}.\n"
                    f"CRITICAL: If 'In stock' - 1-3 days. 'Under order' - 14-20 days. DO NOT PUT LINKS IN TEXT!"
                )
                if result.attributes:
                    attr_str = "\n".join(f"- {k}: {v}" for k, v in result.attributes.items())
                    product_facts.append(f"Characteristics:\n{attr_str}")
                if result.short_description:
                    product_facts.append(f"Description:\n{result.short_description}")
            else:
                logger.info(
                    "Product not found by price_comparator, falling back to search cascade",
                    extra={"product": product_name},
                )
                new_intent_type = INTENT_SEARCH

        return IntentContextResult(
            product_facts=product_facts,
            system_instructions=system_instructions,
            extracted_links=extracted_links,
            requires_lead=requires_lead,
            new_intent_type=new_intent_type,
        )


class SearchIntentHandler:
    def __init__(self, price_comparator: PriceComparator):
        self.price_comparator = price_comparator

    async def handle(
        self,
        intent_data: dict[str, Any],
        category_id: int | None,
        system_instructions: list[str],
        product_facts: list[str],
        extracted_links: list[dict[str, str]],
    ) -> IntentContextResult:
        requires_lead = False
        strict_term = str(
            intent_data.get("strict_query")
            or intent_data.get("search_term")
            or intent_data.get("search_query")
            or ""
        ).strip()
        broad_term = str(intent_data.get("broad_query") or "").strip()

        woo_products = []
        try:
            if strict_term:
                logger.info(
                    "Search intent detected (strict)",
                    extra={"query": strict_term, "category_id": category_id},
                )
                woo_products = await self.price_comparator.woo_service.search_products_async(
                    strict_term, category_id=category_id, limit=3
                )
        except Exception:
            logger.exception("WooCommerce strict search failed")

        is_fallback_broad = False
        is_fallback_category = False

        if not woo_products and broad_term and broad_term != strict_term:
            logger.info(
                "Strict search failed, trying fallback broad search",
                extra={"query": broad_term, "category_id": category_id},
            )
            try:
                woo_products = await self.price_comparator.woo_service.search_products_async(
                    broad_term, category_id=category_id, limit=3
                )
                if woo_products:
                    is_fallback_broad = True
            except Exception:
                logger.exception("WooCommerce broad search failed")

        if not woo_products:
            if category_id is not None:
                logger.info(
                    "Text search failed or empty, trying fallback category search",
                    extra={"category_id": category_id},
                )
                try:
                    woo_products = (
                        await self.price_comparator.woo_service.search_products_by_category_async(
                            category_id, limit=3
                        )
                    )
                    if woo_products:
                        is_fallback_category = True
                except Exception:
                    logger.exception("WooCommerce category search failed")
            else:
                logger.info("Search cascade aborted: category_id is None")

        search_facts: list[str] = []
        if woo_products:
            search_facts.append(SEARCH_FOUND_HEADER)
            for product in woo_products:
                status = (
                    STATUS_INSTOCK if product.stock_status == "instock" else STATUS_OUT_OF_STOCK
                )
                search_facts.append(
                    f"- Name: {product.name}\n  Price: {product.price_uah} UAH\n  Status: {status}"
                )

                if product.attributes:
                    top_attrs = list(product.attributes.items())[:5]
                    attr_str = "\n".join(f"    * {k}: {v}" for k, v in top_attrs)
                    search_facts.append(f"  Characteristics:\n{attr_str}")

                if product.url:
                    extracted_links.append({"text": product.name, "url": product.url})

            search_facts.append(INSTR_NO_DUPLICATE_LINKS)
            product_facts.append("\n".join(search_facts))

            if is_fallback_category:
                system_instructions.append(INSTR_FALLBACK_CATEGORY)
            elif is_fallback_broad:
                system_instructions.append(
                    INSTR_BROAD_SEARCH_FALLBACK.format(
                        broad_term=broad_term, strict_term=strict_term
                    )
                )
        else:
            requires_lead = True
            system_instructions.append(INSTR_NOTHING_FOUND)

        return IntentContextResult(
            product_facts=product_facts,
            system_instructions=system_instructions,
            extracted_links=extracted_links,
            requires_lead=requires_lead,
        )
