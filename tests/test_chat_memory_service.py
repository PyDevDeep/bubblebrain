from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.chat_memory import ChatMessage
from app.services.chat_memory_service import ChatMemoryService


@pytest.fixture
def service():
    return ChatMemoryService()


@pytest.mark.asyncio
@patch("app.services.chat_memory_service.AsyncSessionLocal")
async def test_get_history(mock_session_local, service):
    # Arrange
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session

    mock_result = MagicMock()

    msg1 = ChatMessage(session_id="test", role="user", content="Hi")
    msg2 = ChatMessage(session_id="test", role="bot", content="Hello")

    mock_result.scalars.return_value.all.return_value = [msg2, msg1]
    mock_session.execute.return_value = mock_result

    # Act
    history = await service.get_history("test", limit=2)

    # Assert
    assert len(history) == 2
    # Reversed order expected because DB returns desc
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hi"
    assert history[1]["role"] == "bot"
    assert history[1]["content"] == "Hello"


@pytest.mark.asyncio
@patch("app.services.chat_memory_service.commit_with_retry")
@patch("app.services.chat_memory_service.AsyncSessionLocal")
async def test_add_message(mock_session_local, mock_commit, service):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session

    await service.add_message("test", "user", "Hi")

    mock_session.add.assert_called_once()
    mock_commit.assert_called_once_with(mock_session)


@pytest.mark.asyncio
@patch("app.services.chat_memory_service.commit_with_retry")
@patch("app.services.chat_memory_service.AsyncSessionLocal")
async def test_add_message_error(mock_session_local, mock_commit, service):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session
    mock_commit.side_effect = Exception("DB error")

    await service.add_message("test", "user", "Hi")

    mock_session.rollback.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.chat_memory_service.commit_with_retry")
@patch("app.services.chat_memory_service.AsyncSessionLocal")
async def test_add_interaction(mock_session_local, mock_commit, service):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session

    await service.add_interaction("test", "Hi user", "Hi bot")

    mock_session.add_all.assert_called_once()
    mock_commit.assert_called_once_with(mock_session)


@pytest.mark.asyncio
@patch("app.services.chat_memory_service.commit_with_retry")
@patch("app.services.chat_memory_service.AsyncSessionLocal")
async def test_add_interaction_error(mock_session_local, mock_commit, service):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session
    mock_commit.side_effect = Exception("DB error")

    await service.add_interaction("test", "Hi user", "Hi bot")

    mock_session.rollback.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.chat_memory_service.commit_with_retry")
@patch("app.services.chat_memory_service.AsyncSessionLocal")
async def test_clear_history(mock_session_local, mock_commit, service):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session

    await service.clear_history("test")

    mock_session.execute.assert_called_once()
    mock_commit.assert_called_once_with(mock_session)


@pytest.mark.asyncio
@patch("app.services.chat_memory_service.commit_with_retry")
@patch("app.services.chat_memory_service.AsyncSessionLocal")
async def test_clear_history_error(mock_session_local, mock_commit, service):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session_local.return_value.__aenter__.return_value = mock_session
    mock_commit.side_effect = Exception("DB error")

    await service.clear_history("test")

    mock_session.rollback.assert_called_once()
