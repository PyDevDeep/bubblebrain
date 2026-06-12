from typing import Literal

from pydantic import BaseModel, Field


class ContactFormLead(BaseModel):
    name: str = Field(..., max_length=50, pattern=r"^[A-Za-zА-Яа-яЄєІіЇїҐґ\s\-]+$")
    contact_info: str = Field(..., max_length=50, description="Телефон або Нікнейм")
    contact_method: Literal["telegram", "viber", "phone"]
    honeypot: str | None = Field(default=None, max_length=50)
