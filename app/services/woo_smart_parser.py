import re
from typing import Any

from bs4 import BeautifulSoup

from app.core.logging_config import get_logger

logger = get_logger(__name__)


def parse_product(raw_product: dict[str, Any], max_desc_length: int = 400) -> dict[str, Any]:
    """
    Очищає та структурує сирі дані товару WooCommerce для подальшого використання (наприклад, у LLM).
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
        # 1. Атрибути (Дедуплікація та Видимість)
        attributes: dict[str, str] = {}
        for attr in raw_product.get("attributes", []):
            if attr.get("visible") is True:
                name = str(attr.get("name", ""))
                options = attr.get("options", [])
                attributes[name] = ", ".join(map(str, options)) if options else ""
        clean_data["attributes"] = attributes

        # 2. Очищення та обрізання HTML короткого опису
        html_desc = raw_product.get("short_description", "")
        if html_desc:
            soup = BeautifulSoup(html_desc, "html.parser")

            # Рятуємо <br>, перетворюючи їх на перенесення рядків
            for br in soup.find_all("br"):
                br.replace_with("\n")

            # Форматуємо списки
            for li in soup.find_all("li"):
                li.insert_before("- ")
                li.insert_after("\n")
                li.unwrap()

            # Збираємо текст, розділяючи блокові елементи абзацами (\n\n)
            clean_text = soup.get_text(separator="\n\n", strip=True)

            # Стискаємо множинні порожні рядки (залишаємо абзаци)
            clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)

            # 3. Truncation (Захист контекстного вікна)
            if len(clean_text) > max_desc_length:
                # Обрізаємо до ліміту, не розриваючи останнє слово
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
