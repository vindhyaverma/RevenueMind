"""
Tests for RecoveryPolicyEngine — deterministic policy enforcement.
"""

import pytest
from app.core.recovery_policy_engine import RecoveryPolicyEngine, RecoveryPolicyConfig
from app.schemas.recovery_schemas import FailureType, FailureClass, ActionType


class TestFailureClassification:
    def test_upi_timeout_is_transient(self):
        fc = RecoveryPolicyEngine.classify_failure(FailureType.TRANSIENT_UPI_TIMEOUT)
        assert fc == FailureClass.TRANSIENT

    def test_network_timeout_is_transient(self):
        fc = RecoveryPolicyEngine.classify_failure(FailureType.TRANSIENT_NETWORK)
        assert fc == FailureClass.TRANSIENT

    def test_bank_unavailable_is_transient(self):
        fc = RecoveryPolicyEngine.classify_failure(FailureType.TRANSIENT_BANK_UNAVAIL)
        assert fc == FailureClass.TRANSIENT

    def test_checkout_abandoned_is_recoverable(self):
        fc = RecoveryPolicyEngine.classify_failure(FailureType.RECOVERABLE_ABANDONED)
        assert fc == FailureClass.RECOVERABLE

    def test_link_expired_is_recoverable(self):
        fc = RecoveryPolicyEngine.classify_failure(FailureType.RECOVERABLE_LINK_EXPIRED)
        assert fc == FailureClass.RECOVERABLE

    def test_hard_card_decline_is_non_retryable(self):
        fc = RecoveryPolicyEngine.classify_failure(FailureType.HARD_CARD_DECLINE)
        assert fc == FailureClass.NON_RETRYABLE

    def test_insufficient_funds_is_non_retryable(self):
        fc = RecoveryPolicyEngine.classify_failure(FailureType.HARD_INSUFFICIENT_FUNDS)
        assert fc == FailureClass.NON_RETRYABLE

    def test_fraud_is_high_risk(self):
        fc = RecoveryPolicyEngine.classify_failure(FailureType.HIGH_RISK_FRAUD)
        assert fc == FailureClass.HIGH_RISK

    def test_unknown_type_defaults_to_non_retryable(self):
        fc = RecoveryPolicyEngine.classify_failure("completely_unknown_type")
        assert fc == FailureClass.NON_RETRYABLE


class TestPolicyValidation:

    def test_fraud_always_stops_immediately(self):
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.HIGH_RISK_FRAUD,
            recovery_attempts=0,
            customer_contacts=0,
        )
        assert result.permitted is False
        assert result.stop is True
        assert result.escalate is False  # No customer contact for fraud
        assert result.action == ActionType.STOP

    def test_hard_card_decline_escalates(self):
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.HARD_CARD_DECLINE,
            recovery_attempts=0,
            customer_contacts=0,
        )
        assert result.permitted is False
        assert result.escalate is True
        assert result.action == ActionType.ESCALATE

    def test_insufficient_funds_escalates(self):
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.HARD_INSUFFICIENT_FUNDS,
            recovery_attempts=0,
            customer_contacts=0,
        )
        assert result.permitted is False
        assert result.escalate is True

    def test_upi_timeout_first_attempt_permitted(self):
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.TRANSIENT_UPI_TIMEOUT,
            recovery_attempts=0,
            customer_contacts=0,
        )
        assert result.permitted is True
        assert result.action == ActionType.PAYMENT_LINK

    def test_abandoned_first_attempt_permitted(self):
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.RECOVERABLE_ABANDONED,
            recovery_attempts=0,
            customer_contacts=0,
        )
        assert result.permitted is True
        assert result.action == ActionType.PAYMENT_LINK

    def test_max_attempts_blocks_regardless_of_failure_type(self):
        """Even transient failures are blocked when max attempts is reached."""
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.TRANSIENT_UPI_TIMEOUT,
            recovery_attempts=2,  # at limit
            customer_contacts=0,
        )
        assert result.permitted is False
        assert result.stop is True
        assert result.escalate is True  # escalate after max attempts

    def test_demo_042_policy_block(self):
        """
        DEMO-042: Hard card decline with 2 prior attempts.
        AI would recommend retry. Policy must block it.
        This is the 'second wow' moment.
        """
        result = RecoveryPolicyEngine.validate_demo_042(recovery_attempts=2)
        assert result.permitted is False
        assert result.stop is True or result.escalate is True
        assert "retry" not in result.reason.lower() or "blocked" in result.reason.lower() or "maximum" in result.reason.lower() or "non-retryable" in result.reason.lower()

    def test_customer_contact_limit_enforced(self):
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.RECOVERABLE_ABANDONED,
            recovery_attempts=0,
            customer_contacts=2,  # at limit
        )
        assert result.permitted is False
        assert result.stop is True

    def test_repeated_failure_escalates(self):
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.HARD_REPEATED_FAILURE,
            recovery_attempts=0,
            customer_contacts=0,
        )
        assert result.permitted is False
        assert result.escalate is True

    def test_policy_result_has_all_fields(self):
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.TRANSIENT_UPI_TIMEOUT,
            recovery_attempts=0,
            customer_contacts=0,
        )
        assert hasattr(result, "permitted")
        assert hasattr(result, "action")
        assert hasattr(result, "reason")
        assert hasattr(result, "escalate")
        assert hasattr(result, "stop")
        assert isinstance(result.reason, str)
        assert len(result.reason) > 0

    def test_ai_recommendation_does_not_override_policy(self):
        """Critical: AI recommending 'retry' for a hard decline must not change the decision."""
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.HARD_CARD_DECLINE,
            recovery_attempts=0,
            customer_contacts=0,
            ai_recommended_action=ActionType.RETRY,  # AI wrongly suggests retry
        )
        # Policy must still block it
        assert result.permitted is False
        assert result.escalate is True

    def test_custom_policy_lower_max_attempts(self):
        custom = RecoveryPolicyConfig(max_recovery_attempts=1)
        result = RecoveryPolicyEngine.validate(
            failure_type=FailureType.TRANSIENT_UPI_TIMEOUT,
            recovery_attempts=1,  # at limit with custom policy
            customer_contacts=0,
            policy=custom,
        )
        assert result.permitted is False

    def test_fail_closed_on_unknown_type(self):
        """Unknown failure type should block (fail-closed), never permit."""
        result = RecoveryPolicyEngine.validate(
            failure_type="unknown_future_failure_type",
            recovery_attempts=0,
            customer_contacts=0,
        )
        assert result.permitted is False
