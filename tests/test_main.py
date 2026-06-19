import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_debug_fs(async_client):
    response = await async_client.get("/debug-fs")
    assert response.status_code == 200
    data = response.json()
    assert "exists" in data
    assert "files" in data
    assert "path" in data
