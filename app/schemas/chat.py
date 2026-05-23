from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None


class RAGResponse(BaseModel):
    answer: str
    sources: list[str]
    has_context: bool


class ChatResponse(RAGResponse):
    session_id: str | None = None


class StreamEvent(BaseModel):
    event: str
    data: str
