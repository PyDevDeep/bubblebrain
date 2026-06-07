import contextlib
import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.schemas.scraper import DatacompProduct, HotlineProduct

logger = get_logger(__name__)


class ScraperService:
    def __init__(self, settings: Settings) -> None:
        self.euro_rate = settings.euro_rate
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "uk,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    async def _fetch_html(self, url: str) -> httpx.Response | None:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url, headers=self.headers)
                if resp.status_code == 200:
                    return resp
                return None
            except httpx.RequestError as e:
                logger.error("Scraper fetch error", error=str(e), url=url)
                return None

    async def scrape_datacomp(self, search_term: str) -> DatacompProduct | None:
        url = "https://datacomp.sk/default.asp?cls=stoitems&fulltext=" + urllib.parse.quote(
            search_term
        )
        resp = await self._fetch_html(url)
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        name_node = soup.find("a", class_="stiplname")
        if not name_node:
            return None

        name = name_node.get_text(strip=True)

        href_attr = name_node.get("href")
        href_str = str(href_attr) if href_attr is not None else ""
        link = "https://datacomp.sk/" + href_str if name_node.has_attr("href") else str(resp.url)

        price_node = soup.find("div", class_="wvat")
        price = None
        if price_node:
            price_str = price_node.get_text(strip=True)
            price_str = re.sub(r"[^\d,.]", "", price_str)
            price_str = price_str.replace(",", ".")
            if price_str:
                price = float(price_str)

        stock_node = soup.select_one(".availability .stock")
        inet_node = soup.select_one("div.availability.inet")

        availability: list[str] = []
        if stock_node and stock_node.get_text(strip=True):
            availability.append(stock_node.get_text(strip=True))
        if inet_node and inet_node.get_text(strip=True):
            availability.append(inet_node.get_text(strip=True))

        stock = " | ".join(availability) if availability else "Невідомо"

        price_uah = round(price * self.euro_rate, 2) if price else None

        return DatacompProduct(
            name=name, price_eur=price, price_uah=price_uah, availability_status=stock, url=link
        )

    async def scrape_hotline(self, search_term: str) -> HotlineProduct | None:
        url = "https://hotline.ua/sr/?q=" + urllib.parse.quote(search_term)
        resp = await self._fetch_html(url)
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        price_node = soup.find(class_=re.compile("(many__price-sum|price__value|price-value)"))

        raw_price = None
        if price_node:
            raw_price = price_node.get_text(strip=True)
        else:
            matches = re.findall(
                r"(\d{1,3}(?:[ \xA0]\d{3})*(?:,\d{2})?)\s*(?:–|-)\s*(\d{1,3}(?:[ \xA0]\d{3})*(?:,\d{2})?)\s*₴",
                resp.text,
                re.IGNORECASE,
            )
            if matches:
                raw_price = matches[0][0] + " – " + matches[0][1] + " ₴"
            else:
                matches2 = re.findall(
                    r"(\d{1,3}(?:[ \xA0]\d{3})*(?:,\d{2})?)\s*₴", resp.text, re.IGNORECASE
                )
                if matches2:
                    raw_price = matches2[0] + " ₴"
                else:
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

    async def scrape_datacomp_multi(
        self, search_term: str, limit: int = 5
    ) -> list[DatacompProduct]:
        """Пошук кількох товарів на Datacomp за запитом."""
        url = "https://datacomp.sk/default.asp?cls=stoitems&fulltext=" + urllib.parse.quote(
            search_term
        )
        resp = await self._fetch_html(url)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        name_nodes = soup.find_all("a", class_="stiplname")
        if not name_nodes:
            return []

        products: list[DatacompProduct] = []
        for name_node in name_nodes[:limit]:
            name = name_node.get_text(strip=True)
            href_attr = name_node.get("href")
            href_str = str(href_attr) if href_attr is not None else ""
            link = (
                "https://datacomp.sk/" + href_str if name_node.has_attr("href") else str(resp.url)
            )

            # Переходимо вгору по ієрархії, щоб знайти контейнер товару з ціною та наявністю
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
                DatacompProduct(
                    name=name,
                    price_eur=price,
                    price_uah=price_uah,
                    availability_status=stock,
                    url=link,
                )
            )

        return products
