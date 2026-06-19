from pydantic import BaseModel


class WooProduct(BaseModel):
    sku: str
    name: str
    price_uah: float | None
    url: str
    stock_status: str | None = "instock"
    attributes: dict[str, str] = {}
    short_description: str | None = None
    categories: list[str] = []


class SupplierProduct(BaseModel):
    name: str
    price_eur: float | None
    price_uah: float | None
    availability_status: str
    url: str


class HotlineProduct(BaseModel):
    min_price_uah: float | None
    raw_price: str | None
    url: str


class PriceComparisonResult(BaseModel):
    product_name: str
    woo_price: float | None
    supplier_price_uah: float | None
    hotline_price_uah: float | None = None
    availability_status: str | None = None
    diff_woo_uah: float | None = None
    needs_alert: bool = False
    alert_reason: str | None = None
    supplier_url: str | None = None
    hotline_url: str | None = None
    woo_url: str | None = None
    attributes: dict[str, str] = {}
    short_description: str | None = None
    categories: list[str] = []
