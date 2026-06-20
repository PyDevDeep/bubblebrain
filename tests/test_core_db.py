import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.core.db import commit_with_retry, init_db, set_sqlite_pragma


def test_set_sqlite_pragma():
    # Arrange
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    # Act
    set_sqlite_pragma(mock_conn, None)

    # Assert
    mock_conn.cursor.assert_called_once()
    mock_cursor.execute.assert_any_call("PRAGMA journal_mode=WAL;")
    mock_cursor.execute.assert_any_call("PRAGMA busy_timeout=5000;")
    mock_cursor.close.assert_called_once()


@pytest.mark.asyncio
async def test_commit_with_retry_success():
    # Arrange
    mock_session = AsyncMock()

    # Act
    await commit_with_retry(mock_session)

    # Assert
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_commit_with_retry_retries_on_operational_error():
    # Arrange
    mock_session = AsyncMock()
    # Let it fail twice then succeed
    mock_session.commit.side_effect = [
        OperationalError("db locked", None, Exception("db locked")),
        OperationalError("db locked", None, Exception("db locked")),
        None,
    ]

    # Act
    await commit_with_retry(mock_session)

    # Assert
    assert mock_session.commit.await_count == 3


@pytest.mark.asyncio
async def test_commit_with_retry_fails_after_max_retries():
    # Arrange
    mock_session = AsyncMock()
    # Let it always fail
    mock_session.commit.side_effect = OperationalError("db locked", None, Exception("db locked"))

    # Act & Assert
    from tenacity import RetryError

    with pytest.raises(RetryError):
        await commit_with_retry(mock_session)

    assert mock_session.commit.await_count == 5


@pytest.mark.asyncio
@patch("app.core.db.engine")
@patch("app.core.db.Base.metadata.create_all")
async def test_init_db(mock_create_all, mock_engine):
    # Arrange
    mock_conn = AsyncMock()
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    # Act
    await init_db()

    # Assert
    mock_engine.begin.assert_called_once()
    mock_conn.run_sync.assert_awaited_once_with(mock_create_all)
