import re
from typing import Any

from bs4 import BeautifulSoup

from app.core.logging_config import get_logger

logger = get_logger(__name__)


def parse_product(raw_product: dict[str, Any], max_desc_length: int = 400) -> dict[str, Any]:
    """
    Cleans and structures raw WooCommerce product data for further use (e.g., in LLM).
    """
    clean_data: dict[str, Any] = {
        "id": raw_product.get("id"),
        "name": raw_product.get("name"),
        "sku": raw_product.get("sku"),
        "price": raw_product.get("price"),
    }

    clean_data["attributes"] = {}
    clean_data["short_description"] = ""

    try:
        # 1. Attributes (Deduplication and Visibility)
        attributes: dict[str, str] = {}
        for attr in raw_product.get("attributes", []):
            if attr.get("visible") is True:
                name = str(attr.get("name", ""))
                options = attr.get("options", [])
                attributes[name] = ", ".join(map(str, options)) if options else ""
        clean_data["attributes"] = attributes

        # 2. Cleaning and truncating HTML short description
        html_desc = raw_product.get("short_description", "")
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
            clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)

            # 3. Truncation (Context window protection)
            if len(clean_text) > max_desc_length:
                # Truncate to limit without breaking the last word
                clean_text = clean_text[:max_desc_length].rsplit(" ", 1)[0] + "..."

            clean_data["short_description"] = clean_text
    except Exception as e:
        logger.error(
            "Smart Parser crashed",
            sku=raw_product.get("sku"),
            product_id=raw_product.get("id"),
            error=str(e),
        )

    return clean_data
