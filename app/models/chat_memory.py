from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.core.db import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, nullable=False)
    role = Column(String(20), nullable=False)  # 'user' or 'bot'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class SessionState(Base):
    __tablename__ = "session_states"

    session_id = Column(String(100), primary_key=True, index=True)
    last_search_query = Column(String(255), nullable=True)
    last_products = Column(Text, nullable=True)  # JSON list
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )
