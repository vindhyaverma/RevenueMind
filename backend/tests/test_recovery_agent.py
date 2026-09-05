"""
Tests for RevenueRecoveryAgent — bounded recovery behavior.

All tests verify that:
- AI recommendations are advisory
- Policy engine always has final say
- Recovered amounts come from DB, not AI
- Idempotency prevents duplicate actions
- Stopping rules are enforced
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional

from app.api.recovery_agent import RevenueRecoveryAgent, _rule_based_diagnosis, _make_idempotency_key
from app.core.recovery_policy_engine import RecoveryPolicyEngine
from app.schemas.recovery_schemas import (
    FailureType, FailureClass, ActionType, CaseStatus, FailureDiagnosis, RecoveryPolicyResult
)


# ── Mock case builder ─────────────────────────────────────────────────────────

def make_mock_case(
    failure_type: str = FailureType.TRANSIENT_UPI_TIMEOUT,
    amount_paise: int = 100000,
    recovery_attempts: int = 0,
    customer_contacts: int = 0,
    case_ref: str = "DEMO-TEST",
    case_id: str = "test-case-uuid",
    status: str = "pending",
):
    case = MagicMock()
    case.id = case_id
    case.case_ref = case_ref
    case.failure_type = failure_type
    case.amount_paise = amount_paise
    case.recovery_attempts = recovery_attempts
    case.customer_contacts = customer_contacts
    case.failure_reason = "Test failure reason"
    case.status = status
    return case


def make_mock_db(case):
    db = AsyncMock()
    db.get_recovery_case = AsyncMock(return_value=case)
    db.update_case_field = AsyncMock()
    db.update_case_diagnosis = AsyncMock()
    db.update_case_policy = AsyncMock()
    db.get_recovery_action_by_idempotency = AsyncMock(return_value=None)  # no duplicate
    db.mark_case_recovered = AsyncMock()
    db.mark_case_escalated = AsyncMock()
    db.mark_case_stopped = AsyncMock()
    db.save_recovery_action = AsyncMock()
    db.log_audit_for_case = AsyncMock()
    db.update_case_payment_link = AsyncMock()
    return db


def make_mock_rzp(has_client: bool = False):
    rzp = MagicMock()
    rzp.client = MagicMock() if has_client else None
    rzp.create_payment_link = MagicMock(return_value={
        "id": "plink_test123",
        "short_url": "https://rzp.io/i/test"
    })
    return rzp


# ── Rule-based diagnosis tests ───────────────────────────────────────────────

class TestRuleBasedDiagnosis:

    def test_upi_timeout_diagnosis(self):
        d = _rule_based_diagnosis(FailureType.TRANSIENT_UPI_TIMEOUT)
        assert d.failure_class == FailureClass.TRANSIENT
        assert d.recoverability_score > 0.7
        assert d.confidence > 0.8
        assert len(d.reasoning) > 10

    def test_hard_decline_diagnosis(self):
        d = _rule_based_diagnosis(FailureType.HARD_CARD_DECLINE)
        assert d.failure_class == FailureClass.NON_RETRYABLE
        assert d.recoverability_score < 0.3

    def test_fraud_diagnosis_recommends_stop(self):
        d = _rule_based_diagnosis(FailureType.HIGH_RISK_FRAUD)
        assert d.failure_class == FailureClass.HIGH_RISK
        assert d.recoverability_score < 0.05

    def test_abandoned_diagnosis_is_recoverable(self):
        d = _rule_based_diagnosis(FailureType.RECOVERABLE_ABANDONED)
        assert d.failure_class == FailureClass.RECOVERABLE
        assert d.recoverability_score > 0.5

    def test_diagnosis_never_sets_recovered_amount(self):
        """AI diagnosis MUST NOT include a recovered_amount field."""
        d = _rule_based_diagnosis(FailureType.TRANSIENT_UPI_TIMEOUT)
        assert not hasattr(d, "recovered_amount_paise")
        assert not hasattr(d, "recovered_amount")


class TestIdempotencyKey:

    def test_same_inputs_produce_same_key(self):
        k1 = _make_idempotency_key("case-1", "run-1", "payment_link")
        k2 = _make_idempotency_key("case-1", "run-1", "payment_link")
        assert k1 == k2

    def test_different_cases_produce_different_keys(self):
        k1 = _make_idempotency_key("case-1", "run-1", "payment_link")
        k2 = _make_idempotency_key("case-2", "run-1", "payment_link")
        assert k1 != k2

    def test_key_is_sha256_hex(self):
        k = _make_idempotency_key("case-1", "run-1", "payment_link")
        assert len(k) == 64
        assert all(c in "0123456789abcdef" for c in k)


class TestRecoveryAgentBehavior:

    @pytest.mark.asyncio
    async def test_transient_case_is_recovered(self):
        """Happy path: UPI timeout → diagnosis → policy permits → recovered."""
        case = make_mock_case(failure_type=FailureType.TRANSIENT_UPI_TIMEOUT, amount_paise=100000)
        db = make_mock_db(case)
        rzp = make_mock_rzp(has_client=False)

        agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=True)
        result = await agent._process_single_case("test-case-uuid", "run-1", is_demo=True)

        assert result["outcome"] == "recovered"
        assert result["recovered_paise"] == 100000
        db.mark_case_recovered.assert_called_once()

    @pytest.mark.asyncio
    async def test_hard_decline_is_escalated(self):
        """Hard card decline → policy escalates. AI recommendation irrelevant."""
        case = make_mock_case(failure_type=FailureType.HARD_CARD_DECLINE, amount_paise=500000)
        db = make_mock_db(case)
        rzp = make_mock_rzp()

        agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=True)
        result = await agent._process_single_case("test-case-uuid", "run-1", is_demo=True)

        assert result["outcome"] == "escalated"
        db.mark_case_escalated.assert_called_once()
        # Recovered amount must remain 0
        db.mark_case_recovered.assert_not_called()

    @pytest.mark.asyncio
    async def test_fraud_case_is_stopped_not_escalated(self):
        """Fraud → immediate stop, no customer contact (not just escalate)."""
        case = make_mock_case(failure_type=FailureType.HIGH_RISK_FRAUD, amount_paise=999900)
        db = make_mock_db(case)
        rzp = make_mock_rzp()

        agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=True)
        result = await agent._process_single_case("test-case-uuid", "run-1", is_demo=True)

        assert result["outcome"] == "stopped"
        db.mark_case_stopped.assert_called_once()
        db.mark_case_recovered.assert_not_called()
        db.mark_case_escalated.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_attempts_blocks_transient(self):
        """Even a soft UPI timeout is blocked when max attempts (2) is reached."""
        case = make_mock_case(
            failure_type=FailureType.TRANSIENT_UPI_TIMEOUT,
            recovery_attempts=2,  # at limit
        )
        db = make_mock_db(case)
        rzp = make_mock_rzp()

        agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=True)
        result = await agent._process_single_case("test-case-uuid", "run-1", is_demo=True)

        assert result["outcome"] in ("stopped", "escalated")
        db.mark_case_recovered.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_action_is_blocked(self):
        """If an action already exists for (case, run), it must be blocked."""
        case = make_mock_case(failure_type=FailureType.TRANSIENT_UPI_TIMEOUT)
        db = make_mock_db(case)
        db.get_recovery_action_by_idempotency = AsyncMock(return_value=MagicMock())  # duplicate!
        rzp = make_mock_rzp()

        agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=True)
        result = await agent._process_single_case("test-case-uuid", "run-1", is_demo=True)

        assert result["outcome"] == "duplicate"
        db.mark_case_recovered.assert_not_called()

    @pytest.mark.asyncio
    async def test_ai_cannot_set_recovered_amount(self):
        """
        Recovered amount must ALWAYS come from the case's amount_paise (DB record),
        never from AI diagnosis output.
        """
        case = make_mock_case(
            failure_type=FailureType.TRANSIENT_UPI_TIMEOUT,
            amount_paise=200000,  # DB amount
        )
        db = make_mock_db(case)
        rzp = make_mock_rzp()

        agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=True)
        result = await agent._process_single_case("test-case-uuid", "run-1", is_demo=True)

        if result["outcome"] == "recovered":
            # Recovered amount must equal the DB case amount
            assert result["recovered_paise"] == 200000
            # Check that mark_case_recovered was called with the DB amount
            call_kwargs = db.mark_case_recovered.call_args
            assert call_kwargs[1]["recovered_amount_paise"] == 200000

    @pytest.mark.asyncio
    async def test_policy_overrides_ai_recommendation(self):
        """
        DEMO-042 scenario: AI recommends retry for hard card decline.
        Policy must block it regardless of AI recommendation.
        """
        case = make_mock_case(
            failure_type=FailureType.HARD_CARD_DECLINE,
            recovery_attempts=2,
            case_ref="DEMO-042",
        )
        db = make_mock_db(case)
        rzp = make_mock_rzp()

        agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=True)
        result = await agent._process_single_case("test-case-uuid", "run-1", is_demo=True)

        # Must be blocked — never recovered
        assert result["outcome"] in ("stopped", "escalated")
        db.mark_case_recovered.assert_not_called()

    @pytest.mark.asyncio
    async def test_audit_logged_for_every_case(self):
        """Every case processing must produce at least 2 audit events."""
        case = make_mock_case(failure_type=FailureType.RECOVERABLE_ABANDONED)
        db = make_mock_db(case)
        rzp = make_mock_rzp()

        agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=True)
        await agent._process_single_case("test-case-uuid", "run-1", is_demo=True)

        # Should have at least: case_diagnosed + policy_evaluated + case_recovered/stopped/escalated
        assert db.log_audit_for_case.call_count >= 2


class TestBatchRunMetrics:
    """
    Test that batch run metrics are accurate.
    These are computed from actual case outcomes, never from AI.
    """

    @pytest.mark.asyncio
    async def test_batch_counts_are_accurate(self):
        """Simulate a small batch and verify that counts match outcomes."""
        cases_data = [
            ("case-1", FailureType.TRANSIENT_UPI_TIMEOUT, 100000),
            ("case-2", FailureType.RECOVERABLE_ABANDONED, 200000),
            ("case-3", FailureType.HARD_CARD_DECLINE, 300000),
            ("case-4", FailureType.HIGH_RISK_FRAUD, 400000),
        ]

        results = []
        for case_id, ft, amount in cases_data:
            case = make_mock_case(failure_type=ft, amount_paise=amount, case_id=case_id)
            db = make_mock_db(case)
            rzp = make_mock_rzp()
            agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=True)
            result = await agent._process_single_case(case_id, "run-batch-test", is_demo=True)
            results.append(result["outcome"])

        # Transient + Recoverable should succeed
        assert results[0] == "recovered"
        assert results[1] == "recovered"
        # Hard decline → escalated
        assert results[2] == "escalated"
        # Fraud → stopped
        assert results[3] == "stopped"

    @pytest.mark.asyncio
    async def test_recovered_amount_sums_correctly(self):
        """Total recovered must be sum of individual recovered amounts from DB."""
        amounts = [50000, 150000, 250000]
        total_expected = sum(amounts)

        total_recovered = 0
        for i, amount in enumerate(amounts):
            case = make_mock_case(
                failure_type=FailureType.TRANSIENT_UPI_TIMEOUT,
                amount_paise=amount,
                case_id=f"case-{i}",
            )
            db = make_mock_db(case)
            rzp = make_mock_rzp()
            agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=True)
            result = await agent._process_single_case(f"case-{i}", "run-sum-test", is_demo=True)
            if result["outcome"] == "recovered":
                total_recovered += result.get("recovered_paise", 0)

        assert total_recovered == total_expected
