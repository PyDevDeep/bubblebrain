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
