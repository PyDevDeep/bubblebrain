from app.services.woo_smart_parser import parse_product


def test_parse_product_basic():
    raw = {"id": 1, "name": "Test", "sku": "SKU1", "price": "10.0"}
    res = parse_product(raw)
    assert res["id"] == 1
    assert res["name"] == "Test"
    assert res["price"] == "10.0"
    assert res["attributes"] == {}
    assert res["short_description"] == ""


def test_parse_product_attributes():
    raw = {
        "attributes": [
            {"visible": True, "name": "Color", "options": ["Red", "Blue"]},
            {"visible": False, "name": "Hidden", "options": ["X"]},
        ]
    }
    res = parse_product(raw)
    assert "Color" in res["attributes"]
    assert res["attributes"]["Color"] == "Red, Blue"
    assert "Hidden" not in res["attributes"]


def test_parse_product_short_description():
    raw = {
        "short_description": "<p>Line 1<br>Line 2</p><ul><li>Item 1</li><li>Item 2</li></ul><p>Lots of space\n\n\n\nHere</p>"
    }
    res = parse_product(raw)
    desc = res["short_description"]
    assert "Line 1\n\nLine 2" in desc
    assert "-\n\nItem 1" in desc
    assert "Lots of space\n\nHere" in desc


def test_parse_product_short_description_truncation():
    long_text = "A" * 500
    raw = {"short_description": f"<p>{long_text}</p>"}
    res = parse_product(raw, max_desc_length=100)
    assert len(res["short_description"]) <= 103  # including ...
    assert res["short_description"].endswith("...")


def test_parse_product_invalid_input():
    from app.services.woo_smart_parser import parse_product

    res = parse_product(None)
    assert res["id"] is None
    res2 = parse_product("not_a_dict")  # type: ignore[arg-type]
    assert res2["id"] is None


def test_parse_product_validation_error():
    from app.services.woo_smart_parser import parse_product

    # pass bad types to trigger ValidationError
    res = parse_product({"id": "valid", "attributes": "not_a_list"})
    assert res["id"] is None


def test_parse_product_exception():
    from unittest.mock import patch

    from app.services.woo_smart_parser import parse_product

    with patch("app.services.woo_smart_parser.BeautifulSoup", side_effect=Exception("BS Error")):
        res = parse_product({"id": 1, "short_description": "<div></div>"})
        assert res["id"] == 1


def test_parse_order():
    from app.services.woo_smart_parser import parse_order

    res = parse_order(None)
    assert res == {}

    res = parse_order("not a dict")  # type: ignore[arg-type]
    assert res == {}

    raw_order = {
        "id": 123,
        "status": "processing",
        "total": "500.0",
        "currency": "UAH",
        "date_created": "2023-01-01T10:00:00",
        "billing": {"first_name": "Ivan", "last_name": "Ivanov", "phone": "380991234567"},
        "shipping_lines": [{"method_title": "Nova Poshta", "meta_data": []}],
        "line_items": [
            {"name": "Product 1", "quantity": 2, "price": "250.0", "total": "500.0", "sku": "SKU-1"}
        ],
        "payment_method_title": "Card",
    }

    parsed = parse_order(raw_order)
    assert parsed["id"] == 123
    assert parsed["status"] == "processing"
    assert parsed["billing"]["first_name"] == "Ivan"
    assert parsed["shipping_lines"][0]["method_title"] == "Nova Poshta"
    assert parsed["line_items"][0]["sku"] == "SKU-1"


def test_parse_order_exception():
    from unittest.mock import patch

    from app.services.woo_smart_parser import parse_order

    with patch("app.schemas.order.WooOrder", side_effect=Exception("Model Error")):
        res = parse_order({"id": 1})
        assert res == {}
