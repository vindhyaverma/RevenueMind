"""
RecoveryPolicyEngine — Deterministic recovery policy enforcement.

The AI recommends. This engine decides.

Key principles:
- No AI involvement in this module
- All decisions are rule-based and configurable
- Fail-closed: if uncertain, block and escalate
- Expected value costs are assigned deterministically here.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from app.schemas.recovery_schemas import (
    FailureType, FailureClass, ActionType, RecoveryPolicyResult
)

FAILURE_CLASS_MAP: dict[str, str] = {
    FailureType.TRANSIENT_UPI_TIMEOUT:       FailureClass.TRANSIENT,
    FailureType.TRANSIENT_NETWORK:           FailureClass.TRANSIENT,
    FailureType.TRANSIENT_BANK_UNAVAIL:      FailureClass.TRANSIENT,
    FailureType.RECOVERABLE_ABANDONED:       FailureClass.RECOVERABLE,
    FailureType.RECOVERABLE_LINK_EXPIRED:    FailureClass.RECOVERABLE,
    FailureType.RECOVERABLE_SESSION_EXPIRED: FailureClass.RECOVERABLE,
    FailureType.HARD_CARD_DECLINE:           FailureClass.NON_RETRYABLE,
    FailureType.HARD_INSUFFICIENT_FUNDS:     FailureClass.NON_RETRYABLE,
    FailureType.HARD_REPEATED_FAILURE:       FailureClass.NON_RETRYABLE,
    FailureType.HIGH_RISK_FRAUD:             FailureClass.HIGH_RISK,
}

NON_RETRYABLE_CLASSES = {FailureClass.NON_RETRYABLE, FailureClass.HIGH_RISK}

# Deterministic costs in paise (1 INR = 100 paise)
ACTION_COSTS: dict[str, int] = {
    ActionType.RETRY: 0,
    ActionType.PAYMENT_LINK: 0,
    ActionType.SMS: 100,        # ₹1
    ActionType.EMAIL: 10,       # ₹0.10
    ActionType.WHATSAPP: 500,   # ₹5
    ActionType.VOICE: 1800,     # ₹18
    ActionType.ESCALATE: 7000,  # ₹70
    ActionType.STOP: 0
}

@dataclass
class RecoveryPolicyConfig:
    max_recovery_attempts: int = 2
    max_recovery_window_hours: int = 24
    max_customer_contacts: int = 2
    payment_link_expiry_minutes: int = 20
    fraud_auto_stop: bool = True
    require_human_after_n_failures: int = 2
    voice_allowed: bool = True
    non_retryable_types: List[str] = field(default_factory=lambda: [
        FailureType.HARD_CARD_DECLINE,
        FailureType.HARD_INSUFFICIENT_FUNDS,
        FailureType.HARD_REPEATED_FAILURE,
        FailureType.HIGH_RISK_FRAUD,
    ])

DEFAULT_POLICY = RecoveryPolicyConfig()

class RecoveryPolicyEngine:
    @staticmethod
    def classify_failure(failure_type: str) -> str:
        return FAILURE_CLASS_MAP.get(failure_type, FailureClass.NON_RETRYABLE)

    @staticmethod
    def get_cost(action: str) -> int:
        return ACTION_COSTS.get(action, 0)

    @staticmethod
    def validate(
        failure_type: str,
        recovery_attempts: int,
        customer_contacts: int,
        ai_recommended_action: Optional[str] = None,
        policy: RecoveryPolicyConfig = DEFAULT_POLICY,
    ) -> RecoveryPolicyResult:
        """
        Validates whether the requested action is permitted.
        If ai_recommended_action is None, evaluates the default safe action.
        """
        failure_class = RecoveryPolicyEngine.classify_failure(failure_type)
        action_to_evaluate = ai_recommended_action or ActionType.PAYMENT_LINK
        
        # Determine base cost
        cost = RecoveryPolicyEngine.get_cost(action_to_evaluate)

        # Rule 1: Fraud → immediate stop
        if failure_type == FailureType.HIGH_RISK_FRAUD:
            return RecoveryPolicyResult(
                permitted=False, action=ActionType.STOP,
                reason="Suspected fraud — automated recovery stopped.",
                escalate=False, stop=True, cost_paise=0
            )

        # Rule 2: Non-retryable
        if failure_type in policy.non_retryable_types:
            return RecoveryPolicyResult(
                permitted=False, action=ActionType.ESCALATE,
                reason=f"Failure '{failure_type}' is non-retryable. Merchant review required.",
                escalate=True, stop=False, cost_paise=RecoveryPolicyEngine.get_cost(ActionType.ESCALATE)
            )

        # Rule 3: Max attempts
        if recovery_attempts >= policy.max_recovery_attempts:
            return RecoveryPolicyResult(
                permitted=False, action=ActionType.STOP,
                reason=f"Max recovery attempts reached ({recovery_attempts}/{policy.max_recovery_attempts}).",
                escalate=True, stop=True, cost_paise=0
            )

        # Rule 4: Max customer contact limit
        is_contact_action = action_to_evaluate in [ActionType.SMS, ActionType.EMAIL, ActionType.WHATSAPP, ActionType.VOICE]
        if is_contact_action and customer_contacts >= policy.max_customer_contacts:
            return RecoveryPolicyResult(
                permitted=False, action=ActionType.STOP,
                reason=f"Customer contact limit reached ({customer_contacts}/{policy.max_customer_contacts}).",
                escalate=True, stop=True, cost_paise=0
            )
            
        # Rule 5: Voice allowed?
        if action_to_evaluate == ActionType.VOICE and not policy.voice_allowed:
            return RecoveryPolicyResult(
                permitted=False, action=action_to_evaluate,
                reason="Voice outreach is disabled by merchant policy.",
                escalate=False, stop=False, cost_paise=cost
            )

        # Allow valid actions
        return RecoveryPolicyResult(
            permitted=True,
            action=action_to_evaluate,
            reason=f"{action_to_evaluate.capitalize()} is allowed. Attempt {recovery_attempts + 1}/{policy.max_recovery_attempts}.",
            escalate=False, stop=False, cost_paise=cost
        )

    @staticmethod
    def validate_demo_042(recovery_attempts: int = 2) -> RecoveryPolicyResult:
        return RecoveryPolicyEngine.validate(
            failure_type=FailureType.HARD_CARD_DECLINE,
            recovery_attempts=recovery_attempts,
            customer_contacts=1,
            ai_recommended_action=ActionType.RETRY
        )
