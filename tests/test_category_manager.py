import os

import pytest

from app.services.category_manager import CategoryManager


@pytest.fixture
def temp_csv(tmp_path):
    csv_file = tmp_path / "categories.csv"
    content = "ID,Name,Slug,Parent ID,Count\n1,Category A,cat-a,0,5\n2,Category B,cat-b,0,0\n3,Category C,cat-c,0,10\n"
    csv_file.write_text(content, encoding="utf-8")
    return csv_file


@pytest.mark.asyncio
async def test_category_manager_flow(temp_csv):
    manager = CategoryManager(csv_path=str(temp_csv))

    # Init
    await manager.initialize()

    # get_categories_string should ignore Category B (count 0)
    cat_str = await manager.get_categories_string()
    assert "Category A" in cat_str
    assert "Category C" in cat_str
    assert "Category B" not in cat_str

    # get_category_id
    cat_id_a = await manager.get_category_id("Category A")
    assert cat_id_a == 1

    cat_id_c = await manager.get_category_id("category c")  # case insensitive
    assert cat_id_c == 3

    cat_id_b = await manager.get_category_id("Category B")
    assert cat_id_b is None

    # Test hot reload
    new_content = "ID,Name,Slug,Parent ID,Count\n4,Category D,cat-d,0,5\n"
    temp_csv.write_text(new_content, encoding="utf-8")

    # We need to change mtime to trigger hot reload because filesystem precision might be low
    stat = temp_csv.stat()
    current_mtime = stat.st_mtime
    os.utime(str(temp_csv), (stat.st_atime, current_mtime + 10))

    cat_id_d = await manager.get_category_id("Category D")
    assert cat_id_d == 4

    # Check old is gone
    cat_id_a_new = await manager.get_category_id("Category A")
    assert cat_id_a_new is None


@pytest.mark.asyncio
async def test_category_manager_missing_file():
    manager = CategoryManager(csv_path="/fake/path/missing.csv")
    await manager.initialize()

    res = await manager.get_categories_string()
    assert res == ""

    cat_id = await manager.get_category_id("Category A")
    assert cat_id is None


@pytest.mark.asyncio
async def test_category_manager_corrupted_file(tmp_path):
    csv_file = tmp_path / "corrupt.csv"
    csv_file.write_text("ID,Name\n1,Test", encoding="utf-8")  # missing count column

    manager = CategoryManager(csv_path=str(csv_file))
    await manager.initialize()

    res = await manager.get_categories_string()
    assert res == ""
