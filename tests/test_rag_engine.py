from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from app.core.config import Settings
from app.core.constants import MSG_GUARDRAIL_FAILED
from app.schemas.chat import RAGResponse
from app.services.rag_engine import RAGEngine


@pytest.fixture
def mock_rag_engine():
    """Fixture to provide a mocked RAGEngine."""
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
    """Test intent detection with a valid JSON response from LLM."""
    # Arrange
    mock_rag_engine.category_manager.get_categories_string.return_value = "cat1, cat2"
    mock_rag_engine.openai_service.get_chat_completion.return_value = (
        '{"intent": "FAQ", "product_name": null}'
    )

    # Act
    result = await mock_rag_engine.detect_intent("What is this?", "")

    # Assert
    assert result == {
        "intent": "FAQ",
        "product_name": None,
        "category_query": None,
        "strict_query": None,
        "broad_query": None,
        "normalized_faq_queries": [],
    }


@pytest.mark.asyncio
async def test_process_query_guardrail_failed(mock_rag_engine):
    """Test query processing when the guardrail check fails."""
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
    """Test successful query processing through the RAG engine."""
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

    mock_rag_engine.vector_service.query_similar = AsyncMock(
        return_value=[{"metadata": {"text": "Context 1", "source": "doc1.txt"}}]
    )

    # Act
    response = await mock_rag_engine.process_query("What is this?")

    # Assert
    assert isinstance(response, RAGResponse)
    assert response.has_context is True
    assert response.answer == "Here is the final answer"
    assert "doc1.txt" in response.sources


@pytest.mark.asyncio
async def test_detect_intent_fast_path_sku(mock_rag_engine):
    """Test intent detection fast path using an SKU."""
    from app.services.rag_engine import INTENT_SEARCH

    # Act
    result = await mock_rag_engine.detect_intent("123456", "")

    # Assert
    assert result["intent"] == INTENT_SEARCH
    assert result["strict_query"] == "123456"
    assert result["broad_query"] == "123456"
    # LLM should not be called
    mock_rag_engine.openai_service.get_chat_completion.assert_not_called()


@pytest.mark.asyncio
async def test_detect_intent_fast_path_part_number(mock_rag_engine):
    """Test intent detection fast path using a part number."""
    from app.services.rag_engine import INTENT_SEARCH

    # Act
    result = await mock_rag_engine.detect_intent("RNUC15CRKU700002", "")

    # Assert
    assert result["intent"] == INTENT_SEARCH
    assert result["strict_query"] == "RNUC15CRKU700002"
    assert result["broad_query"] == "RNUC15CRKU700002"
    mock_rag_engine.openai_service.get_chat_completion.assert_not_called()


@pytest.mark.asyncio
async def test_detect_intent_fallback_override(mock_rag_engine):
    """Test intent detection where fallback override forces a search intent."""
    from app.services.rag_engine import INTENT_GENERAL, INTENT_SEARCH

    # Arrange
    mock_rag_engine.category_manager.get_categories_string.return_value = "cat1"
    # LLM incorrectly returns general
    mock_rag_engine.openai_service.get_chat_completion.return_value = (
        f'{{"intent": "{INTENT_GENERAL}"}}'
    )

    # Act
    query = "Скільки коштує доставка для Barebone ASUS 90AR00R2-M00090"
    result = await mock_rag_engine.detect_intent(query, "")

    # Assert
    # Should be overridden to search because of the part number
    assert result["intent"] == INTENT_SEARCH
    assert result["strict_query"] == "90AR00R2-M00090"
    assert result["broad_query"] == query
    mock_rag_engine.openai_service.get_chat_completion.assert_called_once()
