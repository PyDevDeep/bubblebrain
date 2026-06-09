import re

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None


class LeadData(BaseModel):
    name: str | None = Field(default=None, description="Ім'я клієнта")
    phone: str = Field(..., description="Контактний номер телефону (Viber/Telegram)")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^(?:\+380|380|0)\d{9}$", cleaned):
            raise ValueError(
                "Невірний формат номеру. Очікується формат +380XXXXXXXXX або 0XXXXXXXXX"
            )
        return cleaned


class LinkItem(BaseModel):
    text: str
    url: str


class RAGResponse(BaseModel):
    answer: str
    sources: list[str]
    has_context: bool
    links: list[LinkItem] = Field(default=[], description="Відокремлені посилання для фронтенду")
    requires_lead: bool = Field(
        default=False, description="Прапорець для активації форми збору контактів на фронтенді"
    )


class ChatResponse(RAGResponse):
    session_id: str | None = None


class StreamEvent(BaseModel):
    event: str
    data: str
