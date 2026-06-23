from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_openai_service, get_vector_service
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
async def test_readiness_check_success(async_client):
    mock_openai_service = AsyncMock()
    mock_vector_service = MagicMock()

    app.dependency_overrides[get_openai_service] = lambda: mock_openai_service
    app.dependency_overrides[get_vector_service] = lambda: mock_vector_service

    try:
        response = await async_client.get("/api/v1/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "ready", "pinecone": "ok", "openai": "ok"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_readiness_check_openai_fails(async_client):
    mock_openai_service = AsyncMock()
    # Explicitly set the mock to raise an exception when called
    mock_list = AsyncMock(side_effect=Exception("OpenAI error"))
    mock_openai_service.client.models.list = mock_list
    mock_vector_service = MagicMock()

    app.dependency_overrides[get_openai_service] = lambda: mock_openai_service
    app.dependency_overrides[get_vector_service] = lambda: mock_vector_service

    try:
        response = await async_client.get("/api/v1/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["status"] == "error"
        assert data["detail"]["openai"] == "failed"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_readiness_check_pinecone_fails(async_client):
    mock_openai_service = AsyncMock()
    mock_vector_service = MagicMock()
    mock_list_indexes = MagicMock(side_effect=Exception("Pinecone error"))
    mock_vector_service.pc.list_indexes = mock_list_indexes

    app.dependency_overrides[get_openai_service] = lambda: mock_openai_service
    app.dependency_overrides[get_vector_service] = lambda: mock_vector_service

    try:
        response = await async_client.get("/api/v1/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["status"] == "error"
        assert data["detail"]["pinecone"] == "failed"
    finally:
        app.dependency_overrides.clear()
