from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.chat import get_rag_engine
from app.core.constants import MSG_STREAM_CHAT_FAILED, MSG_SYNC_CHAT_FAILED
from app.core.security import verify_api_key
from app.main import app
from app.schemas.chat import RAGResponse

client = TestClient(app)


@pytest.fixture
def mock_rag_engine():
    engine = AsyncMock()
    return engine


@pytest.fixture
def setup_auth(mock_rag_engine):
    app.dependency_overrides[verify_api_key] = lambda: "fake-key"
    app.dependency_overrides[get_rag_engine] = lambda: mock_rag_engine
    yield
    app.dependency_overrides.clear()


def test_chat_completion_success(mock_rag_engine, setup_auth):
    # Arrange
    mock_response = RAGResponse(
        answer="Hello there!", sources=["doc1"], has_context=True, links=[], requires_lead=False
    )
    mock_rag_engine.process_query.return_value = mock_response

    # Act
    response = client.post(
        "/api/v1/chat",
        json={"question": "Hi", "session_id": "test-session"},
        headers={"X-API-Key": "fake-key"},
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Hello there!"
    assert data["sources"] == ["doc1"]
    assert data["has_context"] is True
    assert data["session_id"] == "test-session"


def test_chat_completion_exception_fallback(mock_rag_engine, setup_auth):
    # Arrange
    mock_rag_engine.process_query.side_effect = Exception("Engine died")

    # Act
    response = client.post(
        "/api/v1/chat", json={"question": "Hi"}, headers={"X-API-Key": "fake-key"}
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == MSG_SYNC_CHAT_FAILED
    assert data["has_context"] is False


def test_chat_stream_success(mock_rag_engine, setup_auth):
    # Arrange
    async def mock_stream(*args, **kwargs):
        yield "token1"
        yield "token2"

    mock_rag_engine.process_query_stream = mock_stream

    # Act
    response = client.post(
        "/api/v1/chat/stream", json={"question": "Hi"}, headers={"X-API-Key": "fake-key"}
    )

    # Assert
    assert response.status_code == 200
    content = response.text
    assert "data: token1" in content
    assert "data: token2" in content
    assert "data: [DONE]" in content


def test_chat_stream_exception_fallback(mock_rag_engine, setup_auth):
    # Arrange
    async def mock_stream_error(*args, **kwargs):
        raise Exception("Stream failed")
        yield "never"

    mock_rag_engine.process_query_stream = mock_stream_error

    # Act
    response = client.post(
        "/api/v1/chat/stream", json={"question": "Hi"}, headers={"X-API-Key": "fake-key"}
    )

    # Assert
    assert response.status_code == 200
    content = response.text
    assert f"data: {MSG_STREAM_CHAT_FAILED}" in content
    assert "data: [DONE]" in content
