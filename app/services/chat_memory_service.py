import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete, select

from app.core.db import AsyncSessionLocal, commit_with_retry
from app.models.chat_memory import ChatMessage

logger = logging.getLogger(__name__)


class ChatMemoryService:
    def __init__(self, session_factory: Callable[..., Any] = AsyncSessionLocal) -> None:
        self.session_factory = session_factory

    async def get_history(
        self, session_id: str, limit: int = 6, ignore_reset: bool = False
    ) -> list[dict[str, str]]:
        """
        Retrieves the last N messages for a given session.
        If ignore_reset is False, filters out messages before the last '---context-reset---' marker.
        Returns a list of dicts: [{"role": "user", "content": "..."}]
        """
        try:
            async with self.session_factory() as session:
                stmt = (
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                messages = result.scalars().all()

                # They are ordered desc (newest first), we want them in chronological order
                history: list[dict[str, str]] = []
                for msg in reversed(messages):
                    if not ignore_reset and msg.content == "---context-reset---":
                        history.clear()  # Drop all older messages up to this reset point
                        continue

                    if msg.content == "---context-reset---":
                        continue  # Skip the marker itself even in full logs

                    history.append({"role": str(msg.role), "content": str(msg.content)})

                return history
        except Exception as e:
            logger.exception("Failed to retrieve chat history from SQLite", extra={"error": str(e)})
            raise

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        """Adds a single message to the history."""
        async with self.session_factory() as session:
            try:
                msg = ChatMessage(session_id=session_id, role=role, content=content)
                session.add(msg)
                await commit_with_retry(session)
            except Exception as e:
                logger.exception("Failed to save chat message to SQLite", extra={"error": str(e)})
                await session.rollback()
                raise

    async def add_interaction(self, session_id: str, user_msg: str, bot_msg: str) -> None:
        """Adds a pair of user and bot messages."""
        async with self.session_factory() as session:
            try:
                user_m = ChatMessage(session_id=session_id, role="user", content=user_msg)
                bot_m = ChatMessage(session_id=session_id, role="bot", content=bot_msg)
                session.add_all([user_m, bot_m])
                await commit_with_retry(session)
            except Exception as e:
                logger.exception(
                    "Failed to save chat interaction to SQLite", extra={"error": str(e)}
                )
                await session.rollback()
                raise

    async def clear_history(self, session_id: str) -> None:
        """Clears the history for a given session."""
        async with self.session_factory() as session:
            try:
                stmt = delete(ChatMessage).where(ChatMessage.session_id == session_id)
                await session.execute(stmt)
                await commit_with_retry(session)
            except Exception as e:
                logger.exception("Failed to clear chat history", extra={"error": str(e)})
                await session.rollback()
                raise

    async def reset_rag_context(self, session_id: str) -> None:
        """Adds a context reset marker to clear RAG context while keeping logging history."""
        await self.add_message(session_id, role="system", content="---context-reset---")
