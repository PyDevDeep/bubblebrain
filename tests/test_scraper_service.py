from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.services.scraper_service import ScraperService


@pytest.mark.asyncio
@patch("app.services.scraper_service.httpx.AsyncClient")
async def test_scrape_supplier_success(mock_client_class, mock_settings):
    # Arrange
    html_content = """
    <html>
        <body>
            <a class="stiplname" href="/product1">Product Name</a>
            <div class="wvat">10,50 &euro;</div>
            <div class="availability"><div class="stock">In Stock</div></div>
            <div class="availability inet">Online</div>
        </body>
    </html>
    """
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = html_content
    mock_response.url = "https://supplier.sk/"
    mock_client.get.return_value = mock_response

    service = ScraperService(mock_settings)

    # Act
    res = await service.scrape_supplier("Test")

    # Assert
    assert res is not None
    assert res.name == "Product Name"
    assert res.price_eur == 10.5
    assert res.price_uah == 420.0
    assert "In Stock" in res.availability_status
    assert "Online" in res.availability_status
    assert res.url == "https://mock-supplier.com//product1"


@pytest.mark.asyncio
@patch("app.services.scraper_service.httpx.AsyncClient")
async def test_scrape_supplier_not_found(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 404
    mock_client.get.return_value = mock_response

    service = ScraperService(mock_settings)
    res = await service.scrape_supplier("Test")
    assert res is None


@pytest.mark.asyncio
@patch("app.services.scraper_service.httpx.AsyncClient")
async def test_scrape_supplier_timeout(mock_client_class, mock_settings):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.get.side_effect = httpx.TimeoutException("Timeout")

    service = ScraperService(mock_settings)
    res = await service.scrape_supplier("Test")
    assert res is None


@pytest.mark.asyncio
@patch("app.services.scraper_service.httpx.AsyncClient")
async def test_scrape_hotline_success(mock_client_class, mock_settings):
    # Arrange
    html_content = """
    <html>
        <body>
            <div class="price__value">1 000 – 1 200 ₴</div>
        </body>
    </html>
    """
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = html_content
    mock_response.url = "https://hotline.ua/product"
    mock_client.get.return_value = mock_response

    service = ScraperService(mock_settings)

    # Act
    res = await service.scrape_hotline("Test")

    # Assert
    assert res is not None
    assert res.min_price_uah == 1000.0
    assert res.raw_price is not None
    assert "1 000 – 1 200 ₴" in res.raw_price


@pytest.mark.asyncio
@patch("app.services.scraper_service.httpx.AsyncClient")
async def test_scrape_hotline_fallback_regex(mock_client_class, mock_settings):
    # Arrange
    html_content = """
    <html>
        <body>
            Some text 1 500 – 2 000 ₴
        </body>
    </html>
    """
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = html_content
    mock_response.url = "https://hotline.ua/product"
    mock_client.get.return_value = mock_response

    service = ScraperService(mock_settings)

    # Act
    res = await service.scrape_hotline("Test")

    # Assert
    assert res is not None
    assert res.min_price_uah == 1500.0
    assert res.raw_price is not None
    assert "1 500 – 2 000 ₴" in res.raw_price


@pytest.mark.asyncio
@patch("app.services.scraper_service.httpx.AsyncClient")
async def test_scrape_supplier_multi(mock_client_class, mock_settings):
    html_content = """
    <html>
        <body>
            <div>
                <a class="stiplname" href="/product1">Product 1</a>
                <div class="wvat">10,00</div>
            </div>
            <div>
                <a class="stiplname" href="/product2">Product 2</a>
                <div class="wvat">20,00</div>
            </div>
        </body>
    </html>
    """
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = html_content
    mock_response.url = "https://supplier.sk/"
    mock_client.get.return_value = mock_response

    service = ScraperService(mock_settings)

    res = await service.scrape_supplier_multi("Test", limit=2)
    assert len(res) == 2
    assert res[0].name == "Product 1"
    assert res[1].name == "Product 2"
