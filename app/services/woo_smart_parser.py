import re
from typing import Any, TypedDict

from bs4 import BeautifulSoup
from pydantic import BaseModel, ValidationError

from app.core.logging_config import get_logger

logger = get_logger(__name__)

MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


class WooAttribute(BaseModel):
    name: str = ""
    visible: bool = False
    options: list[Any] = []


class WooProductInput(BaseModel):
    id: Any = None
    name: Any = None
    sku: Any = None
    price: Any = None
    short_description: str = ""
    attributes: list[WooAttribute] = []
    categories: list[dict[str, Any]] = []


class ParsedProduct(TypedDict):
    id: Any
    name: Any
    sku: Any
    price: Any
    attributes: dict[str, str]
    short_description: str
    categories: list[str]


def parse_product(raw_product: dict[str, Any] | None, max_desc_length: int = 400) -> ParsedProduct:
    """
    Cleans and structures raw WooCommerce product data for further use (e.g., in LLM).
    """
    if not isinstance(raw_product, dict):
        logger.warning("Smart Parser received invalid input: expected dict")
        return {
            "id": None,
            "name": None,
            "sku": None,
            "price": None,
            "attributes": {},
            "short_description": "",
            "categories": [],
        }

    try:
        product_input = WooProductInput(**raw_product)
    except ValidationError as e:
        logger.error(
            "Smart Parser validation failed",
            sku=raw_product.get("sku"),
            product_id=raw_product.get("id"),
            error=str(e),
        )
        return {
            "id": None,
            "name": None,
            "sku": None,
            "price": None,
            "attributes": {},
            "short_description": "",
            "categories": [],
        }

    clean_data: ParsedProduct = {
        "id": product_input.id,
        "name": product_input.name,
        "sku": product_input.sku,
        "price": product_input.price,
        "attributes": {},
        "short_description": "",
        "categories": [str(c.get("name", "")) for c in product_input.categories if c.get("name")],
    }

    try:
        # 1. Attributes (Deduplication and Visibility)
        attributes: dict[str, str] = {}
        for attr in product_input.attributes:
            if attr.visible:
                name = attr.name
                options = attr.options
                attributes[name] = ", ".join(map(str, options)) if options else ""
        clean_data["attributes"] = attributes

        # 2. Cleaning and truncating HTML short description
        html_desc = str(raw_product.get("short_description", ""))
        if html_desc:
            soup = BeautifulSoup(html_desc, "html.parser")

            # Rescue <br>, turning them into line breaks
            for br in soup.find_all("br"):
                br.replace_with("\n")

            # Format lists
            for li in soup.find_all("li"):
                li.insert_before("- ")
                li.insert_after("\n")
                li.unwrap()

            # Collect text, separating block elements by paragraphs (\n\n)
            clean_text = soup.get_text(separator="\n\n", strip=True)

            # Compress multiple empty lines (leave paragraphs)
            clean_text = MULTI_NEWLINE_RE.sub("\n\n", clean_text)

            # 3. Truncation (Context window protection)
            if len(clean_text) > max_desc_length:
                # Truncate to limit without breaking the last word
                clean_text = clean_text[:max_desc_length].rsplit(" ", 1)[0] + "..."

            clean_data["short_description"] = clean_text
    except Exception as e:
        logger.error(
            "Smart Parser crashed",
            sku=product_input.sku,
            product_id=product_input.id,
            error=str(e),
        )

    return clean_data


def parse_order(raw_order: dict[str, Any] | None) -> dict[str, Any]:
    """
    Cleans and structures raw WooCommerce order data for further use (e.g., in LLM).
    """
    if not isinstance(raw_order, dict):
        logger.warning("Smart Parser received invalid order input: expected dict")
        return {}

    try:
        from app.schemas.order import WooOrder, WooOrderBilling, WooOrderLineItem, WooOrderShipping

        billing_raw = dict(raw_order.get("billing") or {})
        billing = WooOrderBilling(
            first_name=str(billing_raw.get("first_name", "")),
            last_name=str(billing_raw.get("last_name", "")),
            phone=str(billing_raw.get("phone", "")),
        )
        from typing import cast

        shipping_lines: list[WooOrderShipping] = []
        raw_shipping = raw_order.get("shipping_lines")
        if isinstance(raw_shipping, list):
            shipping_list = cast(list[Any], raw_shipping)
            for sl_item in shipping_list:
                if isinstance(sl_item, dict):
                    sl_dict = cast(dict[str, Any], sl_item)
                    meta_data = sl_dict.get("meta_data")
                    meta_data_list = (
                        cast(list[Any], meta_data) if isinstance(meta_data, list) else []
                    )
                    shipping_lines.append(
                        WooOrderShipping(
                            method_title=str(sl_dict.get("method_title", "")),
                            meta_data=meta_data_list,
                        )
                    )

        line_items: list[WooOrderLineItem] = []
        raw_items = raw_order.get("line_items")
        if isinstance(raw_items, list):
            items_list = cast(list[Any], raw_items)
            for li_item in items_list:
                if isinstance(li_item, dict):
                    li_dict = cast(dict[str, Any], li_item)
                    line_items.append(
                        WooOrderLineItem(
                            name=str(li_dict.get("name", "")),
                            quantity=int(li_dict.get("quantity", 0)),
                            price=float(li_dict.get("price", 0.0)),
                            total=float(li_dict.get("total", 0.0)),
                            sku=str(li_dict.get("sku", "")),
                        )
                    )

        order = WooOrder(
            id=int(raw_order.get("id", 0)),
            status=str(raw_order.get("status", "")),
            total=float(raw_order.get("total", 0.0)),
            currency=str(raw_order.get("currency", "UAH")),
            date_created=str(raw_order.get("date_created", "")),
            billing=billing,
            payment_method_title=str(raw_order.get("payment_method_title", "")),
            shipping_lines=shipping_lines,
            line_items=line_items,
        )
        return order.model_dump()
    except Exception as e:
        logger.error(
            "Smart Parser crashed on order",
            order_id=raw_order.get("id") if raw_order else None,
            error=str(e),
        )
        return {}
