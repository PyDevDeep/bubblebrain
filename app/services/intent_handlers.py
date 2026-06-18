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
    INSTR_CHECKOUT_TELEGRAM,
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
        session_id: str,
    ) -> IntentContextResult:
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
        except Exception:
            logger.exception("Price comparator failed during intent handling")
            return IntentContextResult(
                product_facts=product_facts,
                system_instructions=system_instructions,
                extracted_links=extracted_links,
                requires_lead=requires_lead,
                lead_form_type=lead_form_type,
                new_intent_type=INTENT_SEARCH,
            )

        # Виносимо формування характеристик в окремий блок, щоб вони завжди були доступні
        attributes_facts: list[str] = []
        if result.attributes:
            attr_str = "\n".join(f"- {k}: {v}" for k, v in result.attributes.items())
            attributes_facts.append(f"Characteristics:\n{attr_str}")
        if result.short_description:
            attributes_facts.append(f"Description:\n{result.short_description}")

        # ГОЛОВНИЙ РОЗПОДІЛ ЛОГІКИ
        if is_checkout:
            # 1. КЛІЄНТ ХОЧЕ КУПИТИ: тут діють жорсткі правила перевірки маржі
            if result.needs_alert:
                requires_lead = True
                lead_form_type = "contact"
                safe_product_name = (
                    html.escape(str(result.product_name))
                    if result.product_name
                    else "Unknown Product"
                )

                if result.alert_reason in ["low_margin", "checkout_margin_issue"]:
                    msg = ALERT_MARGIN_ISSUE.format(
                        safe_product_name=safe_product_name,
                        woo_price=result.woo_price,
                        supplier_price=result.supplier_price_uah,
                        diff_woo=result.diff_woo_uah,
                        margin_threshold=self.price_comparator.margin_threshold,
                    )

                    reply_markup = None
                    if result.woo_url:
                        reply_markup = {
                            "inline_keyboard": [
                                [{"text": "📦 Змінити ціну (WooCommerce)", "url": result.woo_url}]
                            ]
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
                        system_instructions.append(
                            "КРИТИЧНО: Ціна на товар змінилася і потребує уточнення. "
                            "КАТЕГОРИЧНО ЗАБОРОНЕНО пропонувати оформлення замовлення або давати посилання на чекаут. "
                            "Прямо зараз попроси клієнта залишити номер телефону тут або написати нашому менеджеру в Telegram/Viber для узгодження фінальної ціни."
                        )
                    product_facts.extend(attributes_facts)
                else:
                    msg = ALERT_SCRAPER_FAILED.format(safe_product_name=safe_product_name)
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
                # Маржа зійшлася, клієнт може купувати
                requires_lead = True
                lead_form_type = "checkout"
                if result.woo_url:
                    connector = "&" if "?" in result.woo_url else "?"
                    tracked_url = (
                        f"{result.woo_url}{connector}bot_source=direct&bot_chat_id={session_id}"
                    )
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
                product_facts.append(
                    f"Data: Product '{result.product_name}', актуальна та підтверджена ціна {result.woo_price} UAH. Conditions: {status_text}.\n"
                    f"CRITICAL: Якщо товар підтверджено, запропонуй оформити замовлення. If 'In stock' - 1-3 days. 'Under order' - 14-20 days. DO NOT PUT LINKS IN TEXT!"
                )
                product_facts.extend(attributes_facts)

        else:
            # 2. КЛІЄНТ ПРОСТО ЗАПИТУЄ ІНФОРМАЦІЮ: видаємо дані, ігноруючи блокування
            if result.woo_price:
                if result.woo_url:
                    connector = "&" if "?" in result.woo_url else "?"
                    tracked_url = (
                        f"{result.woo_url}{connector}bot_source=direct&bot_chat_id={session_id}"
                    )
                    extracted_links.append(
                        {"text": f"View {result.product_name}", "url": tracked_url}
                    )

                system_instructions.append(
                    INSTR_PRODUCT_FOUND.format(product_name=result.product_name)
                )
                system_instructions.append(
                    "⚠️ ВАЖЛИВО: Завжди повідомляй клієнту: 'Увага! Ціна та наявність товару можуть змінюватися протягом дня. "
                    "Будь ласка, уточнюйте актуальну вартість та наявність у менеджера перед оплатою (у чаті або за телефоном)'."
                )

                status_text = (
                    STATUS_INSTOCK
                    if result.availability_status == "instock"
                    else STATUS_OUT_OF_STOCK
                )
                # Для звичайного запиту ціна завжди "Орієнтовна"
                product_facts.append(
                    f"Data: Product '{result.product_name}', Ціна {result.woo_price} UAH. Conditions: {status_text}.\n"
                    f"CRITICAL: If 'In stock' - 1-3 days. 'Under order' - 14-20 days. DO NOT PUT LINKS IN TEXT!"
                )
                product_facts.extend(attributes_facts)
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
            lead_form_type=lead_form_type,
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
        session_id: str,
    ) -> IntentContextResult:
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
                woo_products = await self.price_comparator.woo_service.search_products_async(
                    strict_term, category_id=category_id, limit=3
                )
                if not woo_products:
                    single_prod = await self.price_comparator.woo_service.search_product_async(
                        strict_term, category_id=category_id
                    )
                    if single_prod:
                        woo_products = [single_prod]
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
                if not woo_products:
                    single_prod = await self.price_comparator.woo_service.search_product_async(
                        broad_term, category_id=category_id
                    )
                    if single_prod:
                        woo_products = [single_prod]

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

            # Додаємо дисклеймер щодо орієнтовності цін один раз
            system_instructions.append(
                "⚠️ ВАЖЛИВО: Завжди повідомляй клієнту: 'Увага! Ціна та наявність товару можуть змінюватися протягом дня. "
                "Будь ласка, уточнюйте актуальну вартість та наявність у менеджера перед оплатою (у чаті або за телефоном)'."
            )

            for product in woo_products:
                status = (
                    STATUS_INSTOCK if product.stock_status == "instock" else STATUS_OUT_OF_STOCK
                )

                # Додаємо SKU, щоб LLM точно ідентифікувала товар за артикулом
                sku_line = f"\n  Артикул (SKU): {product.sku}" if product.sku else ""

                search_facts.append(
                    f"- Name: {product.name}{sku_line}\n  Ціна: {product.price_uah} UAH\n  Status: {status}"
                )

                if product.attributes:
                    top_attrs = list(product.attributes.items())[:5]
                    attr_str = "\n".join(f"    * {k}: {v}" for k, v in top_attrs)
                    search_facts.append(f"  Characteristics:\n{attr_str}")

                if product.url:
                    connector = "&" if "?" in product.url else "?"
                    tracked_url = (
                        f"{product.url}{connector}bot_source=direct&bot_chat_id={session_id}"
                    )
                    extracted_links.append({"text": product.name, "url": tracked_url})

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
                system_instructions.append(
                    INSTR_PRODUCT_FOUND.format(product_name=woo_products[0].name)
                )
        else:
            requires_lead = True
            system_instructions.append(INSTR_NOTHING_FOUND)

        return IntentContextResult(
            product_facts=product_facts,
            system_instructions=system_instructions,
            extracted_links=extracted_links,
            requires_lead=requires_lead,
            lead_form_type=lead_form_type,
        )
