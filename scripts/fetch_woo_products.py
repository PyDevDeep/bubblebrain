import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import get_settings


async def main():
    """Main entry point to fetch WooCommerce products and perform analysis."""
    settings = get_settings()
    url = f"{settings.woo_url.rstrip('/')}/wp-json/wc/v3/products"

    products: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Fetch categories first
        cat_url = f"{settings.woo_url.rstrip('/')}/wp-json/wc/v3/products/categories"
        params = {
            "consumer_key": settings.woo_ck,
            "consumer_secret": settings.woo_cs,
            "per_page": 20,
        }
        resp = await client.get(cat_url, params=params)
        categories: list[dict[str, Any]] = resp.json()

        for cat in categories[:10]:  # take up to 10 categories
            params = {
                "consumer_key": settings.woo_ck,
                "consumer_secret": settings.woo_cs,
                "category": cat["id"],
                "per_page": 10,  # 10 products per category
            }
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                products.extend(resp.json())

        # Save to JSON
        json_path = Path(__file__).parent.parent / "woo_products_sample.json"
        with open(json_path, "w", encoding="utf-8") as f:  # noqa: ASYNC230
            json.dump(products, f, ensure_ascii=False, indent=2)

        print(f"Fetched {len(products)} products and saved to {json_path}")

        # Analyze SKUs and parts
        skus: list[tuple[str, str, str]] = []
        for p in products:
            sku = str(p.get("sku", ""))
            name = str(p.get("name", ""))
            if sku:
                skus.append((sku, name, "sku"))

            # Also check attributes for "part number" or similar
            attributes: list[dict[str, Any]] = p.get("attributes", [])
            for attr in attributes:
                attr_name = str(attr.get("name", "")).lower()
                if any(
                    x in attr_name
                    for x in ["part", "парт", "pn", "p/n", "артикул", "код", "модель"]
                ):
                    opts: list[Any] = attr.get("options", [])
                    if opts:
                        for opt in opts:
                            skus.append((str(opt), name, attr_name))

        print("\nExtracted identifiers (SKUs, Part Numbers, etc.):")
        for val, name, src in skus[:20]:  # print first 20 as sample
            print(f"- {val} (from {src}, product: {name[:30]}...)")

        print(f"\nTotal identifiers extracted: {len(skus)}")

        # Simple analysis
        patterns: Counter[str] = Counter()
        lengths: Counter[int] = Counter()

        for val, _, _ in skus:
            val = str(val).strip()
            lengths[len(val)] += 1
            if re.match(r"^\d+$", val):
                patterns["Digits only"] += 1
            elif re.match(r"^[A-Za-z0-9]+$", val):
                patterns["Alphanumeric"] += 1
            elif re.match(r"^[A-Za-z0-9\-]+$", val):
                patterns["Alphanumeric with dashes"] += 1
            elif re.match(r"^[A-Za-z0-9\-\.]+$", val):
                patterns["Alphanumeric with dashes and dots"] += 1
            else:
                patterns["Mixed with spaces or other symbols"] += 1

        print("\nAnalysis by type:")
        for k, v in patterns.items():
            print(f"  {k}: {v}")

        print("\nAnalysis by length:")
        for k, v in sorted(lengths.items()):
            print(f"  Length {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
