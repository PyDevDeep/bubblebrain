import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.core.db import Base


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    surname = Column(String(50), nullable=True)
    phone_number = Column(String(50), nullable=False)
    contact_method = Column(String(20), nullable=False)
    lead_type = Column(String(20), default="contact")  # contact, checkout
    delivery_address = Column(String(255), nullable=True)
    notification_status = Column(String(20), default="pending")  # pending, sent, failed
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
