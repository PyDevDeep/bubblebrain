from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from app.core.config import Settings
from app.core.constants import MSG_GUARDRAIL_FAILED
from app.schemas.chat import RAGResponse
from app.services.rag_engine import RAGEngine


@pytest.fixture
def mock_rag_engine():
    settings = Mock(spec=Settings)
    settings.top_k_results = 3
    settings.similarity_threshold = 0.7

    openai_service = AsyncMock()
    vector_service = MagicMock()  # Use MagicMock for synchronous methods like query_similar
    price_comparator = AsyncMock()
    telegram_service = AsyncMock()
    category_manager = AsyncMock()
    guardrails_service = Mock()
    chat_memory_service = AsyncMock()

    engine = RAGEngine(
        openai_service=openai_service,
        vector_service=vector_service,
        price_comparator=price_comparator,
        telegram_service=telegram_service,
        category_manager=category_manager,
        guardrails_service=guardrails_service,
        chat_memory_service=chat_memory_service,
        settings=settings,
    )
    return engine


@pytest.mark.asyncio
async def test_detect_intent_valid_json(mock_rag_engine):
    # Arrange
    mock_rag_engine.category_manager.get_categories_string.return_value = "cat1, cat2"
    mock_rag_engine.openai_service.get_chat_completion.return_value = (
        '{"intent": "FAQ", "product_name": null}'
    )

    # Act
    result = await mock_rag_engine.detect_intent("What is this?", "")

    # Assert
    assert result == {"intent": "FAQ", "product_name": None}


@pytest.mark.asyncio
async def test_process_query_guardrail_failed(mock_rag_engine):
    # Arrange
    mock_rag_engine.guardrails_service.validate_input.return_value = False

    # Act
    response = await mock_rag_engine.process_query("Bad query")

    # Assert
    assert isinstance(response, RAGResponse)
    assert response.has_context is False
    assert response.answer == MSG_GUARDRAIL_FAILED


@pytest.mark.asyncio
async def test_process_query_success(mock_rag_engine):
    # Arrange
    mock_rag_engine.guardrails_service.validate_input.return_value = True
    mock_rag_engine.chat_memory_service.get_history.return_value = []

    # Mock intent detection
    mock_rag_engine.openai_service.get_chat_completion.side_effect = [
        '{"intent": "FAQ", "normalized_faq_queries": ["test"]}',  # detect_intent
        "Here is the final answer",  # final LLM answer
    ]

    # Mock retrieve context
    mock_rag_engine.openai_service.generate_embedding.return_value = [0.1] * 1536

    mock_rag_engine.vector_service.query_similar.return_value = [
        {"metadata": {"text": "Context 1", "source": "doc1.txt"}}
    ]

    # Act
    response = await mock_rag_engine.process_query("What is this?")

    # Assert
    assert isinstance(response, RAGResponse)
    assert response.has_context is True
    assert response.answer == "Here is the final answer"
    assert "doc1.txt" in response.sources
