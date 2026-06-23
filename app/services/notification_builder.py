import html

from app.core.constants import ALERT_MARGIN_ISSUE, ALERT_SCRAPER_FAILED


class NotificationBuilder:
    """Builds formatted notification messages for Telegram alerts."""

    @staticmethod
    def build_margin_alert(
        product_name: str | None,
        woo_price: float | None,
        supplier_price: float | None,
        diff_woo: float | None,
        margin_threshold: float,
    ) -> str:
        safe_product_name = html.escape(str(product_name)) if product_name else "Unknown Product"
        return ALERT_MARGIN_ISSUE.format(
            safe_product_name=safe_product_name,
            woo_price=woo_price,
            supplier_price=supplier_price,
            diff_woo=diff_woo,
            margin_threshold=margin_threshold,
        )

    @staticmethod
    def build_scraper_failed_alert(product_name: str | None) -> str:
        safe_product_name = html.escape(str(product_name)) if product_name else "Unknown Product"
        return ALERT_SCRAPER_FAILED.format(safe_product_name=safe_product_name)
