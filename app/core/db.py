import logging
import sqlite3
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

DATABASE_URL = "sqlite+aiosqlite:///./leads.db"

engine = create_async_engine(DATABASE_URL, echo=False)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection: sqlite3.Connection, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()


# TODO: Якщо кількість воркерів (Uvicorn/Gunicorn) буде збільшено > 1,
# необхідно мігрувати на PostgreSQL або використовувати окремий брокер повідомлень,
# оскільки SQLite має обмеження для multi-process запису.

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()


async def init_db():
    # Імпортуємо моделі тут, щоб Base.metadata.create_all їх побачив,
    # уникаючи при цьому circular imports та E402 від Ruff.
    from app.models.chat_memory import ChatMessage
    from app.models.lead import Lead

    # Заглушка, щоб Pylance/Ruff не сварилися на "unused import"
    _ = ChatMessage
    _ = Lead

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
