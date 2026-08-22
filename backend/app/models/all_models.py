import os
import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey, Date, Boolean, UniqueConstraint
from sqlalchemy.sql import func
from app.db.session import Base, DEMO_MODE

from sqlalchemy.types import TypeDecorator, CHAR
import uuid

class GUID(TypeDecorator):
    """Platform-independent GUID type."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import UUID
            return dialect.type_descriptor(UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if not isinstance(value, uuid.UUID):
                return "%.32x" % uuid.UUID(value).int
            else:
                return "%.32x" % value.int

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                value = uuid.UUID(value)
            return value

def uuid_column(**kwargs):
    return Column(GUID(), **kwargs)

class Product(Base):
    __tablename__ = "products"

    id = uuid_column(primary_key=True, default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())
    merchant_id = uuid_column(default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())
    name = Column(String(255), nullable=False)
    description = Column(String)
    category = Column(String(100))
    price_paise = Column(Integer, nullable=False)
    inventory = Column(Integer, nullable=False, default=0)
    agent_policy = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Mandate(Base):
    __tablename__ = "mandates"

    id = uuid_column(primary_key=True, default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())
    principal_id = uuid_column(default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())
    allowed_categories = Column(JSON)  # JSON works in both SQLite and PostgreSQL
    merchant_whitelist = Column(JSON, nullable=True)
    transaction_limit_paise = Column(Integer, nullable=False)
    daily_limit_paise = Column(Integer, nullable=False)
    auto_approve_limit_paise = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True))
    hmac_signature = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AgentOrder(Base):
    __tablename__ = "agent_orders"

    id = uuid_column(primary_key=True, default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())
    session_id = uuid_column(nullable=False)
    mandate_id = uuid_column(nullable=True)
    product_id = uuid_column(nullable=True)
    razorpay_order_id = Column(String(255), unique=True)
    razorpay_payment_id = Column(String(255))
    idempotency_key = Column(String(255), unique=True, nullable=False)
    amount_paise = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = uuid_column(primary_key=True, default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())
    session_id = uuid_column(nullable=False)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

class DailySpend(Base):
    __tablename__ = "daily_spend"

    mandate_id = uuid_column(primary_key=True)
    spend_date = Column(Date, primary_key=True, default=date.today)
    total_paise = Column(Integer, nullable=False, default=0)
