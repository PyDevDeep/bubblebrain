from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from pinecone import PineconeException  # type: ignore

from app.services.vector_service import VectorService


@patch("app.services.vector_service.Pinecone")
def test_vector_service_init(mock_pinecone_class, mock_settings):
    # Arrange & Act
    service = VectorService(mock_settings)

    # Assert
    mock_pinecone_class.assert_called_once_with(api_key="fake-pinecone-key")
    assert service.index_name == "test-index"
    assert service.index == mock_pinecone_class.return_value.Index.return_value


@patch("app.services.vector_service.Pinecone")
def test_ensure_index_exists_already_exists(mock_pinecone_class, mock_settings):
    # Arrange
    service = VectorService(mock_settings)
    mock_idx = MagicMock()
    mock_idx.name = "test-index"
    mock_pc = cast(Any, service.pc)
    mock_pc.list_indexes.return_value = [mock_idx]

    # Act
    service.ensure_index_exists()

    # Assert
    mock_pc.create_index.assert_not_called()


@patch("app.services.vector_service.Pinecone")
def test_ensure_index_exists_creates_index(mock_pinecone_class, mock_settings):
    # Arrange
    service = VectorService(mock_settings)
    mock_pc = cast(Any, service.pc)
    mock_pc.list_indexes.return_value = []

    # Act
    service.ensure_index_exists()

    # Assert
    mock_pc.create_index.assert_called_once()
    kwargs = mock_pc.create_index.call_args[1]
    assert kwargs["name"] == "test-index"
    assert kwargs["dimension"] == 1536
    assert kwargs["metric"] == "cosine"


@pytest.mark.asyncio
@patch("app.services.vector_service.Pinecone")
async def test_upsert_vectors(mock_pinecone_class, mock_settings):
    # Arrange
    service = VectorService(mock_settings)

    vectors = [
        ("id1", [0.1] * 1536, {"source": "test1"}),
        ("id2", [0.2] * 1536, {"source": "test2"}),
    ]

    # Act
    total_upserted = await service.upsert_vectors(vectors)

    # Assert
    assert total_upserted == 2
    service.index.upsert.assert_called_once()
    upsert_args = service.index.upsert.call_args[1]
    formatted_batch = upsert_args["vectors"]
    assert len(formatted_batch) == 2
    assert formatted_batch[0]["id"] == "id1"
    assert formatted_batch[0]["values"] == [0.1] * 1536
    assert formatted_batch[0]["metadata"] == {"source": "test1"}


@patch("app.services.vector_service.Pinecone")
def test_query_similar(mock_pinecone_class, mock_settings):
    # Arrange
    service = VectorService(mock_settings)

    mock_response = MagicMock()
    mock_match1 = MagicMock()
    mock_match1.id = "id1"
    mock_match1.score = 0.9
    mock_match1.metadata = {"source": "test1"}

    mock_match2 = MagicMock()
    mock_match2.id = "id2"
    mock_match2.score = 0.5
    mock_match2.metadata = {"source": "test2"}

    mock_response.matches = [mock_match1, mock_match2]
    service.index.query.return_value = mock_response

    # Act
    results = service.query_similar(query_vector=[0.1] * 1536, top_k=2, score_threshold=0.8)

    # Assert
    service.index.query.assert_called_once_with(
        vector=[0.1] * 1536,
        top_k=2,
        include_metadata=True,
        include_values=False,
    )
    assert len(results) == 1
    assert results[0]["id"] == "id1"
    assert results[0]["score"] == 0.9
    assert results[0]["metadata"] == {"source": "test1"}


@patch("app.services.vector_service.Pinecone")
def test_delete_by_source(mock_pinecone_class, mock_settings):
    # Arrange
    service = VectorService(mock_settings)

    # Act
    service.delete_by_source("test_source")

    # Assert
    service.index.delete.assert_called_once_with(filter={"source": "test_source"})


@patch("app.services.vector_service.Pinecone")
def test_delete_by_source_exception(mock_pinecone_class, mock_settings):
    # Arrange
    service = VectorService(mock_settings)
    service.index.delete.side_effect = PineconeException("DB error")

    # Act & Assert
    with pytest.raises(PineconeException, match="DB error"):
        service.delete_by_source("test_source")
