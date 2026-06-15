import logging

from sqlalchemy import delete, select

from app.core.db import AsyncSessionLocal
from app.models.chat_memory import ChatMessage

logger = logging.getLogger(__name__)


class ChatMemoryService:
    def __init__(self) -> None:
        pass

    async def get_history(self, session_id: str, limit: int = 6) -> list[dict[str, str]]:
        """
        Retrieves the last N messages for a given session.
        Returns a list of dicts: [{"role": "user", "content": "..."}]
        """
        async with AsyncSessionLocal() as session:
            stmt = (
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            messages = result.scalars().all()

            # They are ordered desc (newest first), we want them in chronological order
            history = [
                {"role": str(msg.role), "content": str(msg.content)} for msg in reversed(messages)
            ]
            return history

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        """Adds a single message to the history."""
        async with AsyncSessionLocal() as session:
            try:
                msg = ChatMessage(session_id=session_id, role=role, content=content)
                session.add(msg)
                await session.commit()
            except Exception:
                logger.exception("Failed to save chat message to SQLite")
                await session.rollback()

    async def add_interaction(self, session_id: str, user_msg: str, bot_msg: str) -> None:
        """Adds a pair of user and bot messages."""
        async with AsyncSessionLocal() as session:
            try:
                user_m = ChatMessage(session_id=session_id, role="user", content=user_msg)
                bot_m = ChatMessage(session_id=session_id, role="bot", content=bot_msg)
                session.add_all([user_m, bot_m])
                await session.commit()
            except Exception:
                logger.exception("Failed to save chat interaction to SQLite")
                await session.rollback()

    async def clear_history(self, session_id: str) -> None:
        """Clears the history for a given session."""
        async with AsyncSessionLocal() as session:
            try:
                stmt = delete(ChatMessage).where(ChatMessage.session_id == session_id)
                await session.execute(stmt)
                await session.commit()
            except Exception:
                logger.exception("Failed to clear chat history")
                await session.rollback()
