"""
Recovery Schemas — Pydantic models for RevenueMind Track 3 AI Revenue Recovery.

Strict separation:
  - AI outputs: diagnosis, recommendation, confidence, reasoning
  - Deterministic outputs: policy decision, recovered_amount, action execution
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
import uuid


# ── Taxonomy ────────────────────────────────────────────────────────────────

class FailureType(str, Enum):
    # Transient — temporary, retry-eligible
    TRANSIENT_UPI_TIMEOUT    = "upi_timeout"
    TRANSIENT_NETWORK        = "network_timeout"
    TRANSIENT_BANK_UNAVAIL   = "bank_unavailable"

    # Recoverable — new payment link eligible
    RECOVERABLE_ABANDONED    = "checkout_abandoned"
    RECOVERABLE_LINK_EXPIRED = "payment_link_expired"
    RECOVERABLE_SESSION_EXPIRED = "session_expired"

    # Non-retryable — stop, escalate to merchant
    HARD_CARD_DECLINE        = "hard_card_decline"
    HARD_INSUFFICIENT_FUNDS  = "insufficient_funds"
    HARD_REPEATED_FAILURE    = "repeated_failure"

    # High-risk — stop immediately, no customer contact
    HIGH_RISK_FRAUD          = "fraud_suspected"


class FailureClass(str, Enum):
    TRANSIENT      = "transient"       # Soft — retry once
    RECOVERABLE    = "recoverable"     # New payment link
    NON_RETRYABLE  = "non_retryable"  # Stop, escalate
    HIGH_RISK      = "high_risk"       # Stop, no contact


class ActionType(str, Enum):
    RETRY          = "retry"
    PAYMENT_LINK   = "payment_link"
    SMS            = "sms"
    EMAIL          = "email"
    WHATSAPP       = "whatsapp"
    VOICE          = "voice"
    ESCALATE       = "escalate"
    STOP           = "stop"


class CaseStatus(str, Enum):
    PENDING            = "pending"
    IN_PROGRESS        = "in_progress"
    AWAITING_PAYMENT   = "awaiting_payment"
    PROMISE_TO_PAY     = "promise_to_pay"
    RECOVERED          = "recovered"            # Agent-simulated recovery
    VERIFIED_RECOVERED = "verified_recovered"   # Razorpay webhook confirmed
    ESCALATED          = "escalated"
    STOPPED            = "stopped"
    FAILED             = "failed"


# ── AI outputs (AI may produce, deterministic system validates) ────────────

class FailureDiagnosis(BaseModel):
    """AI output. The recovered_amount_paise is NEVER set here."""
    failure_class: FailureClass
    recoverability_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    recommended_action: ActionType
    candidate_actions: Optional[list] = None


# ── Deterministic output ─────────────────────────────────────────────────────

class RecoveryPolicyResult(BaseModel):
    """Deterministic policy decision. AI cannot override this."""
    permitted: bool
    action: ActionType
    reason: str
    escalate: bool = False
    stop: bool = False
    cost_paise: int = 0


# ── Case schemas ─────────────────────────────────────────────────────────────

class CaseSchema(BaseModel):
    id: str
    case_ref: str
    merchant_id: str
    customer_ref: str
    customer_name: str
    amount_paise: int
    failure_type: str
    failure_reason: str
    failure_class: Optional[str] = None

    # AI outputs
    ai_diagnosis: Optional[str] = None
    ai_recommendation: Optional[str] = None
    ai_confidence: Optional[float] = None
    expected_recovery_probability: Optional[float] = None
    interventions_json: Optional[list] = None
    
    is_subscription: bool = False
    customer_ltv_paise: int = 0
    customer_successful_payments: int = 0
    
    # Financial metrics
    recovery_cost_paise: int = 0
    expected_recovered_paise: int = 0
    priority_score: Optional[float] = None

    # Deterministic policy
    policy_result: Optional[str] = None
    policy_reason: Optional[str] = None

    # Action
    action_type: Optional[str] = None
    action_status: Optional[str] = None
    recovery_attempts: int = 0
    customer_contacts: int = 0

    # Razorpay
    payment_link_id: Optional[str] = None
    payment_link_url: Optional[str] = None

    # Outcome — always from DB/payment event, NEVER from AI
    recovered_amount_paise: int = 0
    is_simulated_recovery: bool = True   # False = Razorpay webhook confirmed

    escalated: bool = False
    stopped_by_policy: bool = False
    final_outcome: Optional[str] = None
    run_id: Optional[str] = None

    detected_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RecoveryRunSchema(BaseModel):
    id: str
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    total_cases: int = 0
    processed_cases: int = 0

    # All financial metrics from DB — NEVER from AI
    total_at_risk_paise: int = 0
    recoverable_paise: int = 0
    recovered_paise: int = 0
    agent_recovered_paise: int = 0
    razorpay_verified_paise: int = 0

    success_count: int = 0
    escalated_count: int = 0
    stopped_count: int = 0
    failed_count: int = 0
    duplicate_count: int = 0

    events: list = []

    class Config:
        from_attributes = True


class MetricsSchema(BaseModel):
    """Dashboard KPIs — calculated from DB records, not from AI output."""
    total_at_risk_paise: int
    recoverable_paise: int
    recovered_paise: int
    agent_recovered_paise: int
    razorpay_verified_paise: int
    recovery_rate: float          # recovered / recoverable * 100
    
    # New metrics
    recovery_cost_paise: int = 0
    expected_recovered_paise: int = 0
    net_recovered_paise: int = 0

    total_cases: int
    success_count: int
    escalated_count: int
    stopped_count: int
    pending_count: int
    failed_count: int

    last_run_id: Optional[str]
    last_run_status: Optional[str]


# ── Gemini AI schemas (structured output) ────────────────────────────────────

class CandidateActionSchema(BaseModel):
    action_type: str
    probability: float
    reasoning: str

class GeminiDiagnosisSchema(BaseModel):
    """Schema returned by Gemini for failure diagnosis."""
    failure_class: str
    confidence: float
    reasoning: str
    candidate_actions: List[CandidateActionSchema]


class GeminiRecommendationSchema(BaseModel):
    """Schema returned by Gemini for intervention recommendation."""
    action_type: str
    reasoning: str
    urgency: str    # low, medium, high
    recovery_message: Optional[str] = None

