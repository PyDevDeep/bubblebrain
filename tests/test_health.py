from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_health_check(async_client):
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
@patch("app.api.v1.endpoints.health.AsyncOpenAI")
@patch("app.api.v1.endpoints.health.Pinecone")
async def test_readiness_check_success(mock_pinecone, mock_openai, async_client):
    mock_openai_instance = AsyncMock()
    mock_openai.return_value = mock_openai_instance

    mock_pinecone_instance = MagicMock()
    mock_pinecone.return_value = mock_pinecone_instance

    response = await async_client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "pinecone": "ok", "openai": "ok"}


@pytest.mark.asyncio
@patch("app.api.v1.endpoints.health.AsyncOpenAI")
@patch("app.api.v1.endpoints.health.Pinecone")
async def test_readiness_check_openai_fails(mock_pinecone, mock_openai, async_client):
    mock_openai_instance = AsyncMock()
    mock_openai_instance.models.list.side_effect = Exception("OpenAI error")
    mock_openai.return_value = mock_openai_instance

    mock_pinecone_instance = MagicMock()
    mock_pinecone.return_value = mock_pinecone_instance

    response = await async_client.get("/api/v1/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["status"] == "error"
    assert data["detail"]["openai"] == "failed"


@pytest.mark.asyncio
@patch("app.api.v1.endpoints.health.AsyncOpenAI")
@patch("app.api.v1.endpoints.health.Pinecone")
async def test_readiness_check_pinecone_fails(mock_pinecone, mock_openai, async_client):
    mock_openai_instance = AsyncMock()
    mock_openai.return_value = mock_openai_instance

    mock_pinecone_instance = MagicMock()
    mock_pinecone_instance.list_indexes.side_effect = Exception("Pinecone error")
    mock_pinecone.return_value = mock_pinecone_instance

    response = await async_client.get("/api/v1/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["status"] == "error"
    assert data["detail"]["pinecone"] == "failed"
