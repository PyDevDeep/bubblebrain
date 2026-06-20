import os

import pytest
from httpx import AsyncClient

# Read URL from env or fallback to a default (like localhost) if not set.
# When testing remotely, user will provide BOT_SERVER_URL=https://real-server.com
BOT_URL = os.getenv("BOT_SERVER_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY_SECRET", "fake-secret")


@pytest.fixture
async def remote_client():
    headers = {"X-API-Key": API_KEY}
    async with AsyncClient(base_url=BOT_URL, headers=headers) as client:
        yield client


@pytest.mark.remote
@pytest.mark.asyncio
async def test_remote_health_check(remote_client):
    """Smoke test to check if the remote server is up and responsive."""
    response = await remote_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.remote
@pytest.mark.asyncio
async def test_remote_readiness_check(remote_client):
    """Smoke test to check if the remote server has active connections to its dependencies."""
    response = await remote_client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["openai"] == "ok"
    assert data["pinecone"] == "ok"


@pytest.mark.remote
@pytest.mark.asyncio
async def test_remote_unauthorized_access() -> None:
    """Ensure that the remote server rejects requests without proper API Key."""
    async with AsyncClient(base_url=BOT_URL) as client:
        # Chat endpoint requires API key
        response = await client.post("/api/v1/chat", json={"message": "hello"})
        assert response.status_code == 401
