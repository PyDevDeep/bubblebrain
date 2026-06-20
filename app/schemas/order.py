from typing import Any

from pydantic import BaseModel, Field


class WooOrderLineItem(BaseModel):
    name: str = ""
    quantity: int = 0
    price: float = 0.0
    total: float = 0.0
    sku: str = ""


class WooOrderShipping(BaseModel):
    method_title: str = ""
    meta_data: list[dict[str, Any]] = []


class WooOrderBilling(BaseModel):
    first_name: str = ""
    last_name: str = ""
    phone: str = ""


class WooOrder(BaseModel):
    id: int
    status: str = ""
    total: float = 0.0
    currency: str = "UAH"
    date_created: str = ""
    billing: WooOrderBilling = Field(default_factory=WooOrderBilling)
    payment_method_title: str = ""
    shipping_lines: list[WooOrderShipping] = []
    line_items: list[WooOrderLineItem] = []
