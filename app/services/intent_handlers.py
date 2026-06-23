import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.core.constants import (
    BTN_CHANGE_PRICE,
    BTN_VIEW_PRODUCT,
    FACT_CHECKOUT_PRODUCT,
    FACT_INFO_PRODUCT,
    INSTR_NO_PREPAYMENT,
    INSTR_ORDER_ID_MISSING,
    INSTR_ORDER_NOT_FOUND,
    INSTR_ORDER_STATUS,
    INSTR_PRICE_CHANGED_ALERT,
    INSTR_SEARCH_FALLBACK,
    INTENT_CHECKOUT,
    INTENT_HYBRID,
    INTENT_PRODUCT,
    INTENT_SEARCH,
    LINK_CHECKOUT,
    LINK_TELEGRAM,
    LINK_VIBER,
    SEARCH_FOUND_HEADER,
    STATUS_INSTOCK,
    STATUS_OUT_OF_STOCK,
)
from app.schemas.chat import IntentContextResult
from app.services.notification_builder import NotificationBuilder
from app.services.price_comparator import PriceComparator
from app.services.telegram_service import TelegramService
from app.utils.prompts import (
    INSTR_ALERT_FAILED,
    INSTR_CHECKOUT_TELEGRAM,
    INSTR_NO_DUPLICATE_LINKS,
    INSTR_NOTHING_FOUND,
    INSTR_PRICE_CHECKING,
    INSTR_PRICE_DISCLAIMER,
    INSTR_PRODUCT_CONTEXT,
    INSTR_PRODUCT_FOUND,
)
from app.utils.url_helpers import add_tracking_params

logger = logging.getLogger(__name__)


class ProductCheckoutIntentHandler:
    """Handler for product and checkout intents."""

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
        session_id: str,
    ) -> IntentContextResult:
        """Handles the product or checkout intent."""
        is_checkout = intent_type == INTENT_CHECKOUT
        requires_lead = False
        lead_form_type = None
        new_intent_type = intent_type

        logger.info(
            "Product/Checkout intent detected",
            extra={"product": product_name, "is_checkout": is_checkout},
        )

        try:
            result = await self.price_comparator.compare(
                product_name, is_checkout=is_checkout, category_id=category_id
            )
        except Exception as e:
            logger.exception(
                "Price comparator failed during intent handling", extra={"error": str(e)}
            )
            return IntentContextResult(
                product_facts=product_facts,
                system_instructions=system_instructions,
                extracted_links=extracted_links,
                requires_lead=requires_lead,
                lead_form_type=lead_form_type,
                new_intent_type=INTENT_SEARCH,
            )

        # Move the characteristics formatting into a separate block so they are always available
        attributes_facts: list[str] = []
        if result.categories:
            attributes_facts.append(f"Categories: {', '.join(result.categories)}")
        if result.attributes:
            attr_str = "\n".join(f"- {k}: {v}" for k, v in result.attributes.items())
            attributes_facts.append(f"Characteristics:\n{attr_str}")
        if result.short_description:
            attributes_facts.append(f"Description:\n{result.short_description}")

        # MAIN LOGIC DISTRIBUTION
        if is_checkout:
            # 1. CLIENT WANTS TO BUY: strict margin check rules apply here
            if result.needs_alert:
                requires_lead = True
                lead_form_type = "contact"

                if result.alert_reason in ["low_margin", "checkout_margin_issue"]:
                    msg = NotificationBuilder.build_margin_alert(
                        product_name=result.product_name,
                        woo_price=result.woo_price,
                        supplier_price=result.supplier_price_uah,
                        diff_woo=result.diff_woo_uah,
                        margin_threshold=self.price_comparator.margin_threshold,
                    )

                    reply_markup = None
                    if result.woo_url:
                        reply_markup = {
                            "inline_keyboard": [[{"text": BTN_CHANGE_PRICE, "url": result.woo_url}]]
                        }

                    alert_success = await self.telegram_service.send_alert(
                        msg, alert_type="price", session_id=session_id, reply_markup=reply_markup
                    )

                    extracted_links.append(
                        {"text": LINK_TELEGRAM, "url": self.settings.telegram_contact_url}
                    )
                    extracted_links.append(
                        {"text": LINK_VIBER, "url": self.settings.viber_contact_url}
                    )

                    if result.woo_url:
                        extracted_links.append({"text": "hidden_woo_link", "url": result.woo_url})

                    if not alert_success:
                        system_instructions.append(INSTR_ALERT_FAILED)
                    else:
                        system_instructions.append(INSTR_PRICE_CHANGED_ALERT)
                    product_facts.extend(attributes_facts)
                else:
                    msg = NotificationBuilder.build_scraper_failed_alert(
                        product_name=result.product_name
                    )
                    alert_success = await self.telegram_service.send_alert(
                        msg, alert_type="error", session_id=session_id
                    )

                    if not alert_success:
                        system_instructions.append(INSTR_ALERT_FAILED)
                    else:
                        system_instructions.append(
                            INSTR_PRICE_CHECKING.format(product_name=product_name)
                        )
                    product_facts.extend(attributes_facts)

            else:
                # Margin is okay, client can buy
                requires_lead = True
                lead_form_type = "checkout"
                if result.woo_url:
                    tracked_url = add_tracking_params(result.woo_url, session_id)
                    extracted_links.append({"text": LINK_CHECKOUT, "url": tracked_url})
                extracted_links.append(
                    {"text": LINK_TELEGRAM, "url": self.settings.telegram_contact_url}
                )
                extracted_links.append({"text": LINK_VIBER, "url": self.settings.viber_contact_url})

                system_instructions.append(
                    INSTR_CHECKOUT_TELEGRAM.format(product_name=product_name)
                )
                status_text = (
                    STATUS_INSTOCK
                    if result.availability_status == "instock"
                    else STATUS_OUT_OF_STOCK
                )

                if (
                    result.availability_status == "instock"
                    and result.woo_price is not None
                    and result.woo_price < 40000
                ):
                    system_instructions.append(INSTR_NO_PREPAYMENT)

                product_facts.append(
                    FACT_CHECKOUT_PRODUCT.format(
                        product_name=result.product_name,
                        woo_price=result.woo_price,
                        status_text=status_text,
                    )
                )
                product_facts.extend(attributes_facts)

        else:
            # 2. CLIENT JUST ASKING FOR INFO: return data, ignoring blocking
            if result.woo_price:
                if result.woo_url:
                    tracked_url = add_tracking_params(result.woo_url, session_id)
                    extracted_links.append(
                        {
                            "text": BTN_VIEW_PRODUCT.format(product_name=result.product_name),
                            "url": tracked_url,
                        }
                    )

                if intent_type in [INTENT_HYBRID, INTENT_PRODUCT]:
                    system_instructions.append(
                        INSTR_PRODUCT_CONTEXT.format(product_name=result.product_name)
                    )
                else:
                    system_instructions.append(
                        INSTR_PRODUCT_FOUND.format(product_name=result.product_name)
                    )
                system_instructions.append(INSTR_PRICE_DISCLAIMER)

                status_text = (
                    STATUS_INSTOCK
                    if result.availability_status == "instock"
                    else STATUS_OUT_OF_STOCK
                )

                if result.availability_status == "instock" and result.woo_price < 40000:
                    system_instructions.append(INSTR_NO_PREPAYMENT)

                # For a normal request, the price is always "Estimated"
                product_facts.append(
                    FACT_INFO_PRODUCT.format(
                        product_name=result.product_name,
                        woo_price=result.woo_price,
                        status_text=status_text,
                    )
                )
                product_facts.extend(attributes_facts)
            else:
                logger.info(
                    "Product not found by price_comparator, falling back to search cascade",
                    extra={"product": product_name},
                )
                new_intent_type = INTENT_SEARCH

        viewed_products = (
            [result.product_name] if "result" in locals() and result and result.product_name else []
        )

        return IntentContextResult(
            product_facts=product_facts,
            system_instructions=system_instructions,
            extracted_links=extracted_links,
            requires_lead=requires_lead,
            lead_form_type=lead_form_type,
            new_intent_type=new_intent_type,
            viewed_products=viewed_products,
        )


class SearchIntentHandler:
    """Handler for search intents."""

    def __init__(self, price_comparator: PriceComparator):
        self.price_comparator = price_comparator

    async def _fetch_products(self, query: str, category_id: int | None) -> list[Any]:
        """Helper to fetch products by strict or broad query."""
        woo_products = await self.price_comparator.woo_service.search_products_async(
            query, category_id=category_id, limit=3
        )
        if not woo_products:
            single_prod = await self.price_comparator.woo_service.search_product_async(
                query, category_id=category_id
            )
            if single_prod:
                woo_products = [single_prod]
        return woo_products

    async def handle(
        self,
        intent_data: dict[str, Any],
        category_id: int | None,
        system_instructions: list[str],
        product_facts: list[str],
        extracted_links: list[dict[str, str]],
        session_id: str,
    ) -> IntentContextResult:
        """Handles the search intent."""
        requires_lead = False
        lead_form_type = None
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
                woo_products = await self._fetch_products(strict_term, category_id)
        except httpx.RequestError as e:
            logger.exception("WooCommerce strict search failed", extra={"error": str(e)})

        is_fallback_broad = False
        is_fallback_category = False

        if not woo_products and broad_term and broad_term != strict_term:
            logger.info(
                "Strict search failed, trying fallback broad search",
                extra={"query": broad_term, "category_id": category_id},
            )
            try:
                woo_products = await self._fetch_products(broad_term, category_id)

                if woo_products:
                    is_fallback_broad = True
            except httpx.RequestError as e:
                logger.exception("WooCommerce broad search failed", extra={"error": str(e)})

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
                except httpx.RequestError as e:
                    logger.exception("WooCommerce category search failed", extra={"error": str(e)})
            else:
                logger.info("Search cascade aborted: category_id is None")

        search_facts: list[str] = []
        if woo_products:
            search_facts.append(SEARCH_FOUND_HEADER)

            # Add a disclaimer about price estimation once
            system_instructions.append(INSTR_PRICE_DISCLAIMER)

            for product in woo_products:
                status = (
                    STATUS_INSTOCK if product.stock_status == "instock" else STATUS_OUT_OF_STOCK
                )

                # Add SKU so LLM accurately identifies the product by its article
                sku_line = f"\n  Артикул (SKU): {product.sku}" if product.sku else ""

                search_facts.append(
                    f"- Name: {product.name}{sku_line}\n  Ціна: {product.price_uah} UAH\n  Status: {status}"
                )

                if product.attributes:
                    top_attrs = list(product.attributes.items())[:15]
                    attr_str = "\n".join(f"    * {k}: {v}" for k, v in top_attrs)
                    search_facts.append(f"  Characteristics:\n{attr_str}")

                if product.url:
                    tracked_url = add_tracking_params(product.url, session_id)
                    extracted_links.append({"text": product.name, "url": tracked_url})

            search_facts.append(INSTR_NO_DUPLICATE_LINKS)
            product_facts.append("\n".join(search_facts))

            if is_fallback_category or is_fallback_broad:
                system_instructions.append(INSTR_SEARCH_FALLBACK)
            else:
                system_instructions.append(
                    INSTR_PRODUCT_FOUND.format(product_name=woo_products[0].name)
                )
        else:
            requires_lead = True
            system_instructions.append(INSTR_NOTHING_FOUND)

        viewed_products = [p.name for p in woo_products] if woo_products else []

        return IntentContextResult(
            product_facts=product_facts,
            system_instructions=system_instructions,
            extracted_links=extracted_links,
            requires_lead=requires_lead,
            lead_form_type=lead_form_type,
            viewed_products=viewed_products,
        )


class OrderStatusIntentHandler:
    """Handler for order status intent."""

    def __init__(self, woo_service: Any):
        self.woo_service = woo_service

    async def handle(
        self,
        intent_data: dict[str, Any],
        system_instructions: list[str],
        product_facts: list[str],
    ) -> IntentContextResult:
        order_id_str = str(intent_data.get("strict_query") or "").strip()

        # Витягуємо лише цифри, якщо LLM додала текст
        import re

        match = re.search(r"\d+", order_id_str)
        if match:
            order_id_str = match.group(0)

        if not order_id_str or not order_id_str.isdigit():
            system_instructions.append(INSTR_ORDER_ID_MISSING)
            return IntentContextResult(
                product_facts=product_facts,
                system_instructions=system_instructions,
                extracted_links=[],
                requires_lead=False,
                lead_form_type=None,
                new_intent_type=None,
            )

        order_id = int(order_id_str)
        try:
            order_data = await self.woo_service.get_order_async(order_id)
        except Exception as e:
            logger.exception("WooCommerce order fetch failed", extra={"error": str(e)})
            order_data = None

        if not order_data:
            system_instructions.append(INSTR_ORDER_NOT_FOUND.format(order_id=order_id))
        else:
            extracted_phone = intent_data.get("phone", "")
            extracted_phone_clean = re.sub(r"\D", "", str(extracted_phone))
            billing_phone = order_data.get("billing", {}).get("phone", "")
            billing_phone_clean = re.sub(r"\D", "", str(billing_phone))

            if not extracted_phone_clean:
                system_instructions.append(
                    f"Скажіть користувачу: 'Для перевірки статусу замовлення #{order_id}, з метою безпеки, вкажіть номер телефону, на який було оформлено замовлення.'"
                )
                return IntentContextResult(
                    product_facts=product_facts,
                    system_instructions=system_instructions,
                    extracted_links=[],
                    requires_lead=False,
                    lead_form_type=None,
                    new_intent_type=None,
                )

            if not billing_phone_clean or extracted_phone_clean[-9:] != billing_phone_clean[-9:]:
                system_instructions.append(
                    f"Скажіть користувачу: 'Вказаний номер телефону не збігається з номером у замовленні #{order_id}. Доступ заборонено.'"
                )
                return IntentContextResult(
                    product_facts=product_facts,
                    system_instructions=system_instructions,
                    extracted_links=[],
                    requires_lead=False,
                    lead_form_type=None,
                    new_intent_type=None,
                )

            status_map = {
                "pending": "Очікує оплати",
                "processing": "В обробці",
                "on-hold": "На утриманні",
                "completed": "Виконано",
                "cancelled": "Скасовано",
                "refunded": "Повернено",
                "failed": "Не вдалося",
            }
            raw_status = str(order_data.get("status", ""))
            status_ua = status_map.get(raw_status, raw_status)

            fact = f"Замовлення #{order_data.get('id')}. Статус: {status_ua}. Дата створення: {order_data.get('date_created')}. Сума: {order_data.get('total')} {order_data.get('currency')}."
            fact += f" Спосіб оплати: {order_data.get('payment_method_title')}."

            shipping = order_data.get("shipping_lines", [])
            if shipping:
                fact += f" Спосіб доставки: {shipping[0].get('method_title')}."

            items = order_data.get("line_items", [])
            if items:
                items_str = ", ".join(
                    f"{item.get('name')} (x{item.get('quantity')})" for item in items
                )
                fact += f" Товари: {items_str}."

            product_facts.append(fact)
            system_instructions.append(INSTR_ORDER_STATUS)

        return IntentContextResult(
            product_facts=product_facts,
            system_instructions=system_instructions,
            extracted_links=[],
            requires_lead=False,
            lead_form_type=None,
            new_intent_type=None,
        )
