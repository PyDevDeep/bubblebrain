import contextlib
import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from app.core.config import Settings
from app.core.constants import SCRAPER_TIMEOUT_CONNECT, SCRAPER_TIMEOUT_DEFAULT, SCRAPER_USER_AGENT
from app.core.logging_config import get_logger
from app.schemas.scraper import HotlineProduct, SupplierProduct

logger = get_logger(__name__)


class ScraperService:
    """Service for scraping products from supplier websites and hotline."""

    def __init__(self, settings: Settings) -> None:
        self.euro_rate = settings.euro_rate
        self.supplier_url = settings.supplier_url
        self.user_agent = SCRAPER_USER_AGENT
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "uk,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        # Hard timeout for parsing
        self.timeout = httpx.Timeout(SCRAPER_TIMEOUT_DEFAULT, connect=SCRAPER_TIMEOUT_CONNECT)
        self.client = httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True, headers=self.headers
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()

    async def _fetch_html(self, url: str) -> httpx.Response | None:
        try:
            resp = await self.client.get(url)
            if resp.status_code == 200:
                return resp
            return None
        except httpx.TimeoutException:
            logger.error("Scraper fetch timeout", url=url)
            return None
        except httpx.RequestError:
            logger.exception("Scraper fetch error", url=url)
            return None

    async def scrape_supplier(self, search_term: str) -> SupplierProduct | None:
        """Search supplier using single item fallback to multi API."""
        products = await self.scrape_supplier_multi(search_term, limit=1)
        return products[0] if products else None

    async def scrape_hotline(self, search_term: str) -> HotlineProduct | None:
        url = "https://hotline.ua/sr/?q=" + urllib.parse.quote(search_term)
        resp = await self._fetch_html(url)
        if not resp:
            return None

        try:
            soup = BeautifulSoup(resp.text, "lxml")
            price_node = soup.find(class_=re.compile("(many__price-sum|price__value|price-value)"))

            raw_price = None
            if price_node:
                raw_price = price_node.get_text(strip=True)
            else:
                patterns = [
                    r"(\d{1,3}(?:[ \xA0]\d{3})*(?:,\d{2})?)\s*(?:–|-)\s*(\d{1,3}(?:[ \xA0]\d{3})*(?:,\d{2})?)\s*₴",
                    r"(\d{1,3}(?:[ \xA0]\d{3})*(?:,\d{2})?)\s*₴",
                ]
                for p in patterns:
                    matches = re.findall(p, resp.text, re.IGNORECASE)
                    if matches:
                        match = matches[0]
                        if isinstance(match, tuple):
                            raw_price = f"{match[0]} – {match[1]} ₴"
                        else:
                            raw_price = f"{match} ₴"
                        break

                if not raw_price:
                    return None

            clean_price = re.sub(r"[\s\xA0\t\n\r]", "", raw_price)
            clean_price = clean_price.replace("&nbsp;", "")

            m = re.search(r"(\d+)", clean_price)
            if m:
                min_price = float(m.group(1))
                display_price = re.sub(r"\s+", " ", raw_price)
                return HotlineProduct(
                    min_price_uah=min_price, raw_price=display_price.strip(), url=str(resp.url)
                )

            return None
        except Exception:
            logger.exception("Error parsing Hotline HTML", search_term=search_term)
            return None

    async def scrape_supplier_multi(
        self, search_term: str, limit: int = 5
    ) -> list[SupplierProduct]:
        base_url = self.supplier_url.rstrip("/")
        url = f"{base_url}/default.asp?cls=stoitems&fulltext=" + urllib.parse.quote(search_term)
        resp = await self._fetch_html(url)
        if not resp:
            return []

        try:
            soup = BeautifulSoup(resp.text, "lxml")
            name_nodes = soup.find_all("a", class_="stiplname")
            if not name_nodes:
                return []

            products: list[SupplierProduct] = []
            for name_node in name_nodes[:limit]:
                name = name_node.get_text(strip=True)
                href_attr = name_node.get("href")
                href_str = str(href_attr) if href_attr is not None else ""
                link = f"{base_url}/" + href_str if name_node.has_attr("href") else str(resp.url)

                parent = name_node
                price_node = None
                stock_node = None
                inet_node = None
                for _ in range(5):
                    parent = parent.parent
                    if not parent:
                        break
                    price_node = parent.find("div", class_="wvat")
                    stock_node = parent.select_one(".availability .stock")
                    inet_node = parent.select_one("div.availability.inet")
                    if price_node:
                        break

                price = None
                if price_node:
                    price_str = price_node.get_text(strip=True)
                    price_str = re.sub(r"[^\d,.]", "", price_str)
                    price_str = price_str.replace(",", ".")
                    if price_str:
                        with contextlib.suppress(ValueError):
                            price = float(price_str)

                availability: list[str] = []
                if stock_node and stock_node.get_text(strip=True):
                    availability.append(stock_node.get_text(strip=True))
                if inet_node and inet_node.get_text(strip=True):
                    availability.append(inet_node.get_text(strip=True))

                stock = " | ".join(availability) if availability else "Невідомо"
                price_uah = round(price * self.euro_rate, 2) if price else None

                products.append(
                    SupplierProduct(
                        name=name,
                        price_eur=price,
                        price_uah=price_uah,
                        availability_status=stock,
                        url=link,
                    )
                )

            return products
        except Exception:
            logger.exception("Error parsing Supplier Multi HTML", search_term=search_term)
            return []
