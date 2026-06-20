import pytest
from pydantic import ValidationError

from app.schemas.order import (
    WooOrder,
    WooOrderBilling,
    WooOrderLineItem,
    WooOrderShipping,
)


def test_woo_order_line_item_default():
    item = WooOrderLineItem()
    assert item.name == ""
    assert item.quantity == 0
    assert item.price == 0.0
    assert item.total == 0.0
    assert item.sku == ""


def test_woo_order_line_item_custom():
    item = WooOrderLineItem(name="Test Product", quantity=2, price=10.5, total=21.0, sku="SKU123")
    assert item.name == "Test Product"
    assert item.quantity == 2
    assert item.price == 10.5
    assert item.total == 21.0
    assert item.sku == "SKU123"


def test_woo_order_shipping_default():
    shipping = WooOrderShipping()
    assert shipping.method_title == ""
    assert shipping.meta_data == []


def test_woo_order_shipping_custom():
    shipping = WooOrderShipping(
        method_title="Flat Rate", meta_data=[{"key": "cost", "value": "10.0"}]
    )
    assert shipping.method_title == "Flat Rate"
    assert shipping.meta_data == [{"key": "cost", "value": "10.0"}]


def test_woo_order_billing_default():
    billing = WooOrderBilling()
    assert billing.first_name == ""
    assert billing.last_name == ""
    assert billing.phone == ""


def test_woo_order_billing_custom():
    billing = WooOrderBilling(first_name="John", last_name="Doe", phone="+380991234567")
    assert billing.first_name == "John"
    assert billing.last_name == "Doe"
    assert billing.phone == "+380991234567"


def test_woo_order_required_fields():
    # id is required
    with pytest.raises(ValidationError):
        WooOrder()  # type: ignore[call-arg]


def test_woo_order_default_values():
    order = WooOrder(id=123)
    assert order.id == 123
    assert order.status == ""
    assert order.total == 0.0
    assert order.currency == "UAH"
    assert order.date_created == ""
    assert order.billing.first_name == ""
    assert order.payment_method_title == ""
    assert order.shipping_lines == []
    assert order.line_items == []


def test_woo_order_custom_values():
    order = WooOrder(
        id=1001,
        status="processing",
        total=500.5,
        currency="USD",
        date_created="2023-01-01T12:00:00",
        billing=WooOrderBilling(first_name="Alice", last_name="Smith"),
        payment_method_title="Credit Card",
        shipping_lines=[WooOrderShipping(method_title="Nova Poshta")],
        line_items=[WooOrderLineItem(name="Laptop", quantity=1)],
    )

    assert order.id == 1001
    assert order.status == "processing"
    assert order.total == 500.5
    assert order.currency == "USD"
    assert order.date_created == "2023-01-01T12:00:00"
    assert order.billing.first_name == "Alice"
    assert order.payment_method_title == "Credit Card"
    assert len(order.shipping_lines) == 1
    assert order.shipping_lines[0].method_title == "Nova Poshta"
    assert len(order.line_items) == 1
    assert order.line_items[0].name == "Laptop"
