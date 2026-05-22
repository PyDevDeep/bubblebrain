from typing import Any

from pydantic import BaseModel, Field


class TextIngestRequest(BaseModel):
    text: str = Field(..., min_length=10)
    metadata: dict[str, Any] | None = None


class IngestResponse(BaseModel):
    document_id: str
    chunks_count: int
    status: str
