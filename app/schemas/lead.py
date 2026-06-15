import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ContactFormLead(BaseModel):
    name: str = Field(..., max_length=50, pattern=r"^[A-Za-zА-Яа-яЄєІіЇїҐґ\s\-]+$")
    surname: str | None = Field(
        default=None, max_length=50, pattern=r"^[A-Za-zА-Яа-яЄєІіЇїҐґ\s\-]+$"
    )
    phone_number: str = Field(..., max_length=50, description="Телефон")
    contact_method: Literal["telegram", "viber", "phone"]
    lead_type: Literal["contact", "checkout"] = Field(default="contact")
    delivery_address: str | None = Field(default=None, max_length=255)
    honeypot: str | None = Field(default=None, max_length=50)

    @field_validator("phone_number", mode="before")
    @classmethod
    def clean_and_validate_phone(cls, v: str) -> str:
        v = str(v)
        cleaned = re.sub(r"[^\d+]", "", v)
        if not re.match(r"^(?:\+?38)?0\d{9}$", cleaned):
            raise ValueError("Некоректний формат телефону")
        return cleaned
