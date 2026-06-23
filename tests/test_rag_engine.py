from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.core.config import Settings
from app.schemas.chat import PipelineContext
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
async def test_try_capture_lead_success(mock_rag_engine):
    # Arrange
    mock_rag_engine.chat_memory_service.get_history.return_value = [
        {"role": "bot", "content": "Here is a link https://example.com"}
    ]
    mock_rag_engine.telegram_service.send_alert.return_value = True

    # Mock LeadService
    mock_rag_engine.lead_service = AsyncMock()
    mock_rag_engine.lead_service.create_chat_lead.return_value = 1

    # Act
    is_lead, ctx = await mock_rag_engine._try_capture_lead("call me +380501234567", "sess")

    # Assert
    assert is_lead is True
    assert ctx is not None
    assert ctx.is_valid is False  # Lead triggers short-circuit


@pytest.mark.asyncio
async def test_try_capture_lead_exception(mock_rag_engine):
    from app.core.constants import MSG_LEAD_FAILED

    # Arrange
    mock_rag_engine.lead_service = AsyncMock()
    mock_rag_engine.lead_service.create_chat_lead.side_effect = Exception("DB error")

    # Act
    is_lead, ctx = await mock_rag_engine._try_capture_lead("call me +380501234567", "sess")

    # Assert
    assert is_lead is True
    assert ctx.fallback_response == MSG_LEAD_FAILED


@pytest.mark.asyncio
async def test_process_query_sync_exception(mock_rag_engine):
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
