import enum

from sqlalchemy import Column, DateTime, Enum, Integer, String
from sqlalchemy.sql import func

from app.core.db import Base


class LeadType(enum.Enum):
    contact = "contact"
    checkout = "checkout"


class ContactMethod(enum.Enum):
    telegram = "telegram"
    viber = "viber"
    phone = "phone"


class NotificationStatus(enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class LeadStatus(enum.Enum):
    new = "new"
    success = "success"
    decline = "decline"
    in_progress = "in_progress"


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    surname = Column(String(50), nullable=True)
    phone_number = Column(String(50), nullable=False)
    contact_method = Column(Enum(ContactMethod), nullable=False)
    lead_type = Column(Enum(LeadType), default=LeadType.contact)
    delivery_address = Column(String(255), nullable=True)
    notification_status = Column(Enum(NotificationStatus), default=NotificationStatus.pending)
    status = Column(Enum(LeadStatus), default=LeadStatus.new)
    session_id = Column(String(100), nullable=True, index=True)
    woo_order_id = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
