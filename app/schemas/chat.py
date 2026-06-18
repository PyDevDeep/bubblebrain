import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.constants import ERR_INVALID_PHONE


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None


class LeadData(BaseModel):
    name: str | None = Field(default=None, description="Client name")
    phone: str = Field(..., description="Contact phone number (Viber/Telegram)")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Validates and cleans the phone number."""
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^(?:\+380|380|0)\d{9}$", cleaned):
            raise ValueError(ERR_INVALID_PHONE)
        return cleaned


class LinkItem(BaseModel):
    text: str
    url: str


class RAGResponse(BaseModel):
    answer: str
    sources: list[str]
    has_context: bool
    links: list[LinkItem] = Field(default=[], description="Extracted links for frontend")
    requires_lead: bool = Field(
        default=False, description="Flag to activate contact form on frontend"
    )
    lead_form_type: Literal["contact", "checkout"] | None = Field(
        default=None, description="Type of form to display on frontend"
    )


class ChatResponse(RAGResponse):
    session_id: str | None = None


class StreamEvent(BaseModel):
    event: str
    data: str


@dataclass
class PipelineContext:
    is_valid: bool
    fallback_response: str | None
    final_context: list[str]
    sources: list[str]
    extracted_links: list[dict[str, str]]
    requires_lead: bool
    lead_form_type: Literal["contact", "checkout"] | None
    extended_user_message: str


@dataclass
class IntentContextResult:
    product_facts: list[str]
    system_instructions: list[str]
    extracted_links: list[dict[str, str]]
    requires_lead: bool
    lead_form_type: Literal["contact", "checkout"] | None = None
    new_intent_type: str | None = None
