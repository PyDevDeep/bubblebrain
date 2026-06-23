import logging
import sqlite3
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

DATABASE_URL = "sqlite+aiosqlite:///./data/leads.db"

engine = create_async_engine(DATABASE_URL, echo=False)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection: sqlite3.Connection, connection_record: Any) -> None:
    """Sets SQLite pragmas for performance and concurrency on connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.1, min=0.1, max=0.5),
    retry=retry_if_exception_type(OperationalError),
)
async def commit_with_retry(session: Any) -> None:
    """Executes session.commit() with retries to bypass SQLite locks."""
    await session.commit()


# TODO: If the number of workers (Uvicorn/Gunicorn) is increased > 1,
# it is necessary to migrate to PostgreSQL or use a separate message broker,
# because SQLite has limitations for multi-process writing.

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()


async def init_db():
    """Initializes the database and creates all tables."""
    # Import models here so that Base.metadata.create_all can see them,
    # while avoiding circular imports and E402 from Ruff.
    from app.models.chat_memory import ChatMessage, SessionState
    from app.models.lead import Lead

    # Stub so that Pylance/Ruff don't complain about "unused import"
    _ = ChatMessage
    _ = SessionState
    _ = Lead

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
