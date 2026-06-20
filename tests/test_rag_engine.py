from unittest.mock import AsyncMock, MagicMock, Mock, patch

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


@pytest.mark.asyncio
async def test_detect_intent_json_error(mock_rag_engine):
    mock_rag_engine.openai_service.get_chat_completion.return_value = "invalid json"

    from app.services.rag_engine import INTENT_FAQ

    result = await mock_rag_engine.detect_intent("help", "")
    assert result["intent"] == INTENT_FAQ


@pytest.mark.asyncio
async def test_detect_intent_generic_error(mock_rag_engine):
    mock_rag_engine.openai_service.get_chat_completion.side_effect = Exception("API error")

    from app.services.rag_engine import INTENT_FAQ

    result = await mock_rag_engine.detect_intent("help", "")
    assert result["intent"] == INTENT_FAQ


@pytest.mark.asyncio
async def test_retrieve_context(mock_rag_engine):
    mock_rag_engine.vector_service.query_similar = AsyncMock(
        return_value=[
            {"metadata": {"text": "Text snippet", "source": "src1"}},
            {"metadata": {"questions": "Q1", "answer": "A1", "source": "src2"}},
        ]
    )

    chunks, sources, timing = await mock_rag_engine._retrieve_context(
        "query", precomputed_vector=[0.1, 0.2]
    )

    assert len(chunks) == 2
    assert "Text snippet" in chunks[0]
    assert "Питання: Q1\nВідповідь: A1" in chunks[1]
    assert "src1" in sources
    assert "src2" in sources
    assert "embedding_ms" in timing
    assert "retrieval_ms" in timing


@pytest.mark.asyncio
async def test_get_intent_context_search(mock_rag_engine):
    from app.services.rag_engine import INTENT_SEARCH

    # Arrange
    intent_data = {"intent": INTENT_SEARCH, "strict_query": "laptop"}
    history = []

    # Mock search intent handler
    mock_res = MagicMock(
        product_facts=["Fact 1"],
        system_instructions=["Inst 1"],
        extracted_links=[],
        requires_lead=False,
        lead_form_type=None,
    )
    mock_rag_engine.search_intent_handler.handle = AsyncMock(return_value=mock_res)

    # Act
    ctx = await mock_rag_engine._get_intent_context(intent_data, history, "session_1")

    # Assert
    assert ctx.product_facts == ["Fact 1"]
    assert ctx.system_instructions == ["Inst 1"]


@pytest.mark.asyncio
async def test_get_intent_context_contact(mock_rag_engine):
    from app.services.rag_engine import INTENT_CONTACT

    # Arrange
    intent_data = {"intent": INTENT_CONTACT}
    history = []
    mock_rag_engine.settings.telegram_contact_url = "http://tg"
    mock_rag_engine.settings.viber_contact_url = "http://vb"

    # Act
    ctx = await mock_rag_engine._get_intent_context(intent_data, history, "session_1")

    # Assert
    assert ctx.requires_lead is True
    assert ctx.lead_form_type == "contact"
    assert len(ctx.extracted_links) == 2  # Telegram & Viber


@pytest.mark.asyncio
@patch("app.services.rag_engine.AsyncSessionLocal")
async def test_try_capture_lead_success(mock_session_local, mock_rag_engine):
    # Arrange
    from unittest.mock import MagicMock

    mock_session = MagicMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session

    mock_rag_engine.chat_memory_service.get_history.return_value = [
        {"role": "bot", "content": "Here is a link https://example.com"}
    ]
    mock_rag_engine.telegram_service.send_alert.return_value = True

    # Act
    is_lead, ctx = await mock_rag_engine._try_capture_lead("call me +380501234567", "sess")

    # Assert
    assert is_lead is True
    assert ctx is not None
    assert ctx.is_valid is False  # Lead triggers short-circuit


@pytest.mark.asyncio
@patch("app.services.rag_engine.AsyncSessionLocal")
async def test_try_capture_lead_exception(mock_session_local, mock_rag_engine):
    from app.services.rag_engine import MSG_LEAD_FAILED

    # Arrange
    mock_session_local.side_effect = Exception("DB error")

    # Act
    is_lead, ctx = await mock_rag_engine._try_capture_lead("call me +380501234567", "sess")

    # Assert
    assert is_lead is True
    assert ctx.fallback_response == MSG_LEAD_FAILED


@pytest.mark.asyncio
async def test_process_query_sync_exception(mock_rag_engine):
    from app.schemas.chat import PipelineContext

    with patch(
        "app.services.rag_engine.RAGEngine._prepare_rag_pipeline",
        return_value=PipelineContext(
            is_valid=True,
            fallback_response=None,
            final_context=["Fact"],
            sources=["doc1"],
            extracted_links=[],
            requires_lead=False,
            lead_form_type=None,
            extended_user_message="Msg",
        ),
    ):
        mock_rag_engine.openai_service.get_chat_completion.side_effect = Exception("API")

        resp = await mock_rag_engine.process_query("Q")
        from app.core.constants import MSG_SYSTEM_ERROR

        assert resp.answer == MSG_SYSTEM_ERROR


@pytest.mark.asyncio
async def test_process_query_stream_success(mock_rag_engine):
    from app.schemas.chat import PipelineContext

    with patch(
        "app.services.rag_engine.RAGEngine._prepare_rag_pipeline",
        return_value=PipelineContext(
            is_valid=True,
            fallback_response=None,
            final_context=["Fact"],
            sources=["doc1"],
            extracted_links=[],
            requires_lead=False,
            lead_form_type=None,
            extended_user_message="Msg",
        ),
    ):

        async def mock_stream(*args, **kwargs):
            yield "Hello "
            yield "World"

        mock_rag_engine.openai_service.stream_chat_completion = mock_stream

        tokens = []
        async for token in mock_rag_engine.process_query_stream("Q"):
            tokens.append(token)

        assert any("Hello " in t for t in tokens)
        assert any("World" in t for t in tokens)
