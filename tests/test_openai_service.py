from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import RateLimitError

from app.services.openai_service import OpenAIService


@pytest.mark.asyncio
@patch("app.services.openai_service.AsyncOpenAI")
async def test_generate_embedding(mock_async_openai_class, mock_settings):
    # Arrange
    mock_client = AsyncMock()
    mock_async_openai_class.return_value = mock_client

    service = OpenAIService(mock_settings)
    # Re-assign the client since it was created during init
    service.client = mock_client

    mock_response = MagicMock()
    mock_data = MagicMock()
    mock_data.embedding = [0.1, 0.2, 0.3]
    mock_response.data = [mock_data]
    mock_client.embeddings.create.return_value = mock_response

    # Act
    result = await service.generate_embedding("test text")

    # Assert
    assert result == [0.1, 0.2, 0.3]
    mock_client.embeddings.create.assert_called_once_with(
        model="text-embedding-ada-002", input="test text"
    )


@pytest.mark.asyncio
@patch("app.services.openai_service.AsyncOpenAI")
async def test_generate_embedding_empty_text(mock_async_openai_class, mock_settings):
    # Arrange
    service = OpenAIService(mock_settings)

    # Act & Assert
    with pytest.raises(ValueError, match="Input text for embedding cannot be empty"):
        await service.generate_embedding("   ")


@pytest.mark.asyncio
@patch("app.services.openai_service.AsyncOpenAI")
async def test_get_chat_completion(mock_async_openai_class, mock_settings):
    # Arrange
    mock_client = AsyncMock()
    mock_async_openai_class.return_value = mock_client
    service = OpenAIService(mock_settings)
    service.client = mock_client

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Chat completion response"
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    # Act
    result = await service.get_chat_completion(
        system_prompt="System: {context}", user_message="Hello", context_chunks=["chunk1", "chunk2"]
    )

    # Assert
    assert result == "Chat completion response"
    mock_client.chat.completions.create.assert_called_once()
    kwargs = mock_client.chat.completions.create.call_args[1]
    assert kwargs["model"] == "gpt-4"
    assert kwargs["messages"][0]["content"] == "System: chunk1\n\nchunk2"
    assert kwargs["messages"][1]["content"] == "Hello"


@pytest.mark.asyncio
@patch("app.services.openai_service.AsyncOpenAI")
async def test_stream_chat_completion(mock_async_openai_class, mock_settings):
    # Arrange
    mock_client = AsyncMock()
    mock_async_openai_class.return_value = mock_client
    service = OpenAIService(mock_settings)
    service.client = mock_client

    async def mock_stream():
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "Stream"

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = " response"

        for c in [chunk1, chunk2]:
            yield c

    mock_client.chat.completions.create.return_value = mock_stream()

    # Act
    chunks = []
    async for chunk in service.stream_chat_completion("System prompt", "User msg", ["c1"]):
        chunks.append(chunk)

    # Assert
    assert chunks == ["Stream", " response"]


@pytest.mark.asyncio
@patch("app.services.openai_service.AsyncOpenAI")
async def test_get_chat_completion_rate_limit(mock_async_openai_class, mock_settings):
    # Arrange
    mock_client = AsyncMock()
    mock_async_openai_class.return_value = mock_client
    service = OpenAIService(mock_settings)
    service.client = mock_client

    import httpx

    # RateLimitError init requires 'message', 'response', 'body'
    response = httpx.Response(429, request=httpx.Request("GET", "http://test"))
    error = RateLimitError("Rate limit exceeded", response=response, body=None)
    mock_client.chat.completions.create.side_effect = error

    import tenacity

    # Act & Assert
    with pytest.raises(tenacity.RetryError):
        await service.get_chat_completion("sys", "user", [])
