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
        html_desc = product_input.short_description
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
