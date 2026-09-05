"""
Recovery Models — SQLAlchemy models for RevenueMind Track 3.
Extends existing models without breaking them.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, JSON, Boolean, Float, Text
from sqlalchemy.sql import func
from app.db.session import Base, DEMO_MODE
from app.models.all_models import GUID, uuid_column


class RevenueRiskCase(Base):
    """
    One revenue-risk case = one failed/abandoned payment that RevenueMind tracks.
    Financial truth (recovered_amount_paise) is set ONLY by deterministic code
    after a verified payment event. AI never writes to this field.
    """
    __tablename__ = "revenue_risk_cases"

    id = uuid_column(primary_key=True, default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())
    case_ref = Column(String(20), unique=True, nullable=False, index=True)   # e.g. DEMO-001
    merchant_id = uuid_column(nullable=False)

    # Customer info
    customer_ref  = Column(String(100), nullable=False)
    customer_name = Column(String(200), nullable=False)

    # Failure classification
    amount_paise    = Column(Integer, nullable=False)
    failure_type    = Column(String(50), nullable=False)  # FailureType enum value
    failure_reason  = Column(Text, nullable=False)
    failure_class   = Column(String(30), nullable=True)   # Set by agent after diagnosis

    # AI outputs — AI MAY write these, deterministic system validates
    ai_diagnosis     = Column(Text, nullable=True)
    ai_recommendation = Column(String(50), nullable=True)
    ai_confidence    = Column(Float, nullable=True)
    expected_recovery_probability = Column(Float, nullable=True)
    
    # Next Best Action Matrix (serialized list of candidates)
    interventions_json = Column(JSON, nullable=True)

    # Deterministic financials computed from AI probability
    recovery_cost_paise = Column(Integer, nullable=False, default=0)
    expected_recovered_paise = Column(Integer, nullable=False, default=0)
    priority_score = Column(Float, nullable=True)
    
    is_subscription = Column(Boolean, nullable=False, default=False)
    
    # Basic customer snapshot
    customer_ltv_paise = Column(Integer, nullable=False, default=0)
    customer_successful_payments = Column(Integer, nullable=False, default=0)

    # Deterministic policy result
    policy_result   = Column(String(20), nullable=True)   # permitted/blocked/stopped
    policy_reason   = Column(Text, nullable=True)

    # Action tracking
    action_type     = Column(String(30), nullable=True)   # ActionType enum value
    action_status   = Column(String(30), nullable=True)
    recovery_attempts = Column(Integer, nullable=False, default=0)
    customer_contacts = Column(Integer, nullable=False, default=0)

    # Razorpay integration
    payment_link_id  = Column(String(100), nullable=True)
    payment_link_url = Column(Text, nullable=True)
    razorpay_order_id = Column(String(100), nullable=True)

    # Recovery outcome — DETERMINISTIC ONLY, never AI-set
    recovered_amount_paise = Column(Integer, nullable=False, default=0)
    is_simulated_recovery  = Column(Boolean, nullable=False, default=True)
    # True  = demo-mode simulated outcome (agent assumed success)
    # False = real Razorpay payment webhook confirmed

    # State flags
    escalated          = Column(Boolean, nullable=False, default=False)
    stopped_by_policy  = Column(Boolean, nullable=False, default=False)
    final_outcome      = Column(String(50), nullable=True)

    status  = Column(String(30), nullable=False, default="pending")  # CaseStatus
    run_id  = uuid_column(nullable=True)

    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())


class RecoveryRun(Base):
    """
    A batch recovery run. Stores aggregate metrics for fast dashboard reads.
    All financial totals are computable from RevenueRiskCase records (source of truth).
    """
    __tablename__ = "recovery_runs"

    id = uuid_column(primary_key=True, default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())

    status = Column(String(20), nullable=False, default="pending")  # pending/running/completed/failed

    started_at   = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    total_cases     = Column(Integer, nullable=False, default=0)
    processed_cases = Column(Integer, nullable=False, default=0)

    # Financial metrics — always from DB records, NEVER from AI
    total_at_risk_paise   = Column(Integer, nullable=False, default=0)
    recoverable_paise     = Column(Integer, nullable=False, default=0)
    recovered_paise       = Column(Integer, nullable=False, default=0)
    agent_recovered_paise = Column(Integer, nullable=False, default=0)
    razorpay_verified_paise = Column(Integer, nullable=False, default=0)

    success_count   = Column(Integer, nullable=False, default=0)
    escalated_count = Column(Integer, nullable=False, default=0)
    stopped_count   = Column(Integer, nullable=False, default=0)
    failed_count    = Column(Integer, nullable=False, default=0)
    duplicate_count = Column(Integer, nullable=False, default=0)

    # Serialized event log for live stream
    events_json = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RecoveryAction(Base):
    """
    Immutable log of every action attempted for a recovery case.
    Supports idempotency: if an action exists for (case_id, run_id), skip.
    """
    __tablename__ = "recovery_actions"

    id = uuid_column(primary_key=True, default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())
    case_id = uuid_column(nullable=False, index=True)
    run_id  = uuid_column(nullable=False, index=True)

    action_type    = Column(String(30), nullable=False)
    attempted_at   = Column(DateTime(timezone=True), server_default=func.now())
    idempotency_key = Column(String(100), unique=True, nullable=False)

    policy_approved = Column(Boolean, nullable=False)
    razorpay_ref    = Column(String(100), nullable=True)

    outcome        = Column(String(30), nullable=True)
    outcome_reason = Column(Text, nullable=True)
    is_simulated   = Column(Boolean, nullable=False, default=True)

class RecoveryCommunication(Base):
    """
    Log of communications with the customer (SMS, Email, WhatsApp, Voice).
    Used for the Customer Communication Center timeline.
    """
    __tablename__ = "recovery_communications"

    id = uuid_column(primary_key=True, default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())
    case_id = uuid_column(nullable=False, index=True)
    
    channel = Column(String(30), nullable=False)  # sms, email, whatsapp, voice
    direction = Column(String(10), nullable=False, default="outbound")
    message = Column(Text, nullable=True)
    
    status = Column(String(30), nullable=False)   # sent, delivered, opened, answered, failed
    is_simulated = Column(Boolean, nullable=False, default=True)
    
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    
class PromiseToPay(Base):
    """
    Structured outcome generated when the AI Voice Agent or Chat captures a commitment.
    """
    __tablename__ = "promises_to_pay"

    id = uuid_column(primary_key=True, default=lambda: str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4())
    case_id = uuid_column(nullable=False, index=True)
    
    amount_paise = Column(Integer, nullable=False)
    promised_date = Column(String(20), nullable=False) # e.g. "2026-09-07"
    promised_time = Column(String(20), nullable=True)  # e.g. "18:00"
    
    channel = Column(String(30), nullable=False)       # e.g. voice, whatsapp
    
    status = Column(String(30), nullable=False, default="pending") # pending, kept, broken
    
    captured_at = Column(DateTime(timezone=True), server_default=func.now())
