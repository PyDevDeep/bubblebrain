from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
@patch("app.api.v1.endpoints.telegram.process_telegram_update")
async def test_telegram_webhook(mock_process, async_client):
    payload = {"update_id": 12345}
    response = await async_client.post("/api/v1/telegram/webhook", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
