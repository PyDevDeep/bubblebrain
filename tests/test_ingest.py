from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.ingest import get_openai_service, get_vector_service
from app.core.security import verify_api_key
from app.main import app

client = TestClient(app)


@pytest.fixture
def mock_openai_service():
    service = AsyncMock()
    service.generate_embeddings_batch.return_value = [[0.1] * 1536, [0.2] * 1536]
    return service


@pytest.fixture
def mock_vector_service():
    service = AsyncMock()
    return service


@pytest.fixture
def setup_auth(mock_openai_service, mock_vector_service):
    app.dependency_overrides[verify_api_key] = lambda: "fake-key"
    app.dependency_overrides[get_openai_service] = lambda: mock_openai_service
    app.dependency_overrides[get_vector_service] = lambda: mock_vector_service
    yield
    app.dependency_overrides.clear()


@patch("app.api.v1.endpoints.ingest.extract_text")
@patch("app.api.v1.endpoints.ingest.chunk_text")
def test_upload_document_success(
    mock_chunk_text, mock_extract_text, setup_auth, mock_vector_service
):
    # Arrange
    mock_extract_text.return_value = "extracted text"
    mock_chunk_text.return_value = ["chunk 1", "chunk 2"]

    # Act
    response = client.post(
        "/api/v1/ingest/document",
        files={"file": ("test.txt", b"dummy content", "text/plain")},
        headers={"X-API-Key": "fake-key"},
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["status"] == "indexed"
    assert response.json()["chunks_count"] == 2
    mock_vector_service.upsert_vectors.assert_called_once()


@patch("app.api.v1.endpoints.ingest.extract_text")
def test_upload_document_extract_error(mock_extract_text, setup_auth):
    # Arrange
    mock_extract_text.side_effect = ValueError("Unsupported file type")

    # Act
    response = client.post(
        "/api/v1/ingest/document",
        files={"file": ("test.png", b"dummy image", "image/png")},
        headers={"X-API-Key": "fake-key"},
    )

    # Assert
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


@patch("app.api.v1.endpoints.ingest.chunk_text")
def test_upload_text_success(mock_chunk_text, setup_auth, mock_vector_service):
    # Arrange
    mock_chunk_text.return_value = ["chunk 1", "chunk 2"]

    # Act
    response = client.post(
        "/api/v1/ingest/text",
        json={"text": "some text here", "metadata": {"source": "test"}},
        headers={"X-API-Key": "fake-key"},
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["status"] == "indexed"
    assert response.json()["chunks_count"] == 2
    mock_vector_service.upsert_vectors.assert_called_once()
