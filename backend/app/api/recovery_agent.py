"""
RevenueRecoveryAgent — The core AI Revenue Recovery agent.

Workflow per case:
  DETECT → DIAGNOSE → PREDICT → DECIDE → RECOVER → VERIFY → LEARN

Key invariant: AI recommends. Deterministic policy decides.
"""

import uuid
import hashlib
import asyncio
import json
from datetime import datetime, timezone
from typing import List, Optional, Any

from app.schemas.recovery_schemas import (
    FailureType, FailureClass, ActionType, CaseStatus,
    FailureDiagnosis, CandidateActionSchema, RecoveryPolicyResult,
)
from app.core.recovery_policy_engine import RecoveryPolicyEngine, DEFAULT_POLICY, FAILURE_CLASS_MAP
from app.core.logger import StructuredLogger

logger = StructuredLogger("revenue_recovery_agent")

def _rule_based_diagnosis(failure_type: str) -> FailureDiagnosis:
    """Deterministic diagnosis for DEMO_MODE. Generates Next Best Action matrix."""
    failure_class = FAILURE_CLASS_MAP.get(failure_type, FailureClass.NON_RETRYABLE)
    
    candidates = []
    
    if failure_class == FailureClass.TRANSIENT:
        candidates = [
            {"action_type": ActionType.PAYMENT_LINK, "probability": 0.87, "reasoning": "Highest probability for transient timeouts."},
            {"action_type": ActionType.WHATSAPP, "probability": 0.72, "reasoning": "Good fallback if link fails."},
            {"action_type": ActionType.RETRY, "probability": 0.65, "reasoning": "Risk of duplicate transaction."},
        ]
    elif failure_class == FailureClass.RECOVERABLE:
        candidates = [
            {"action_type": ActionType.PAYMENT_LINK, "probability": 0.73, "reasoning": "Standard recovery path for abandoned checkouts."},
            {"action_type": ActionType.WHATSAPP, "probability": 0.68, "reasoning": "High open rate for abandoned sessions."},
            {"action_type": ActionType.EMAIL, "probability": 0.45, "reasoning": "Low cost, moderate conversion."},
            {"action_type": ActionType.VOICE, "probability": 0.81, "reasoning": "High conversion but high cost. Best for high LTV."},
        ]
    elif failure_class == FailureClass.NON_RETRYABLE:
        candidates = [
            {"action_type": ActionType.RETRY, "probability": 0.12, "reasoning": "AI thinks retry might work (will be blocked)."},
            {"action_type": ActionType.ESCALATE, "probability": 0.95, "reasoning": "Safest action for hard declines."},
        ]
    elif failure_class == FailureClass.HIGH_RISK:
        candidates = [
            {"action_type": ActionType.STOP, "probability": 0.99, "reasoning": "Fraud suspected. Stop immediately."},
        ]
    else:
        candidates = [
            {"action_type": ActionType.ESCALATE, "probability": 0.99, "reasoning": "Unknown failure type."},
        ]

    c_schemas = [CandidateActionSchema(**c) for c in candidates]
    best_action = max(c_schemas, key=lambda c: c.probability).action_type

    return FailureDiagnosis(
        failure_class=failure_class,
        recoverability_score=max(c.probability for c in c_schemas),
        confidence=0.92,
        reasoning=f"Analyzed {failure_type}. Evaluated {len(candidates)} candidate interventions.",
        recommended_action=best_action,
        candidate_actions=c_schemas,
    )

def _make_idempotency_key(case_id: str, run_id: str, action: str) -> str:
    raw = f"recovery:{case_id}:{run_id}:{action}"
    return hashlib.sha256(raw.encode()).hexdigest()

class RevenueRecoveryAgent:
    def __init__(self, db, razorpay_client, demo_mode: bool = False, ai_provider=None):
        self.db = db
        self.rzp = razorpay_client
        self.demo_mode = demo_mode
        self.ai = ai_provider

    async def process_batch(self, run_id: str) -> dict:
        cases = await self.db.get_pending_recovery_cases()
        await self.db.update_recovery_run(run_id, status="running", total_cases=len(cases))
        logger.info("recovery_agent.batch_started", run_id=run_id, cases=len(cases))

        results = []
        for case in cases:
            res = await self.process_case(case, run_id)
            results.append(res)

        # Aggregate outcomes
        success = sum(1 for r in results if r["outcome"] in ("recovered", "awaiting_payment", "promise_to_pay"))
        escalated = sum(1 for r in results if r["outcome"] == "escalated")
        stopped = sum(1 for r in results if r["outcome"] == "stopped")
        failed = sum(1 for r in results if r["outcome"] == "failed")
        dupes = sum(1 for r in results if r["outcome"] == "duplicate")

        recovered_paise = sum(r.get("recovered_paise", 0) for r in results)

        await self.db.update_recovery_run(
            run_id=run_id,
            status="completed",
            completed_at=datetime.now(timezone.utc),
            processed_cases=len(cases),
            success_count=success,
            escalated_count=escalated,
            stopped_count=stopped,
            failed_count=failed,
            duplicate_count=dupes,
            agent_recovered_paise=recovered_paise,
            events_json=[r["event"] for r in results if r.get("event")]
        )
        logger.info("recovery_agent.batch_completed", run_id=run_id, success=success)
        return {"run_id": run_id, "processed": len(cases), "success": success}

    async def process_case(self, case, run_id: str) -> dict:
        case_id = str(case.id)
        await self.db.update_case_status(case_id, CaseStatus.IN_PROGRESS, run_id)

        try:
            diagnosis = _rule_based_diagnosis(case.failure_type)
        except Exception as e:
            logger.error("recovery_agent.diagnosis_failed", case_id=case_id, error=str(e))
            return {"outcome": "failed"}

        # Store interventions JSON for the Next Best Action matrix
        interventions_dump = [c.model_dump() for c in diagnosis.candidate_actions]
        
        # Calculate Expected Value for the highest probability action
        # In a full system we'd calculate EV for ALL and pick the max EV, but this is a solid approximation
        best_cand = max(diagnosis.candidate_actions, key=lambda c: c.probability)
        expected_probability = best_cand.probability
        cost = RecoveryPolicyEngine.get_cost(best_cand.action_type)
        expected_recovered = int((expected_probability * case.amount_paise) - cost)
        
        # Priority score logic (Amount * Probability)
        priority_score = float(case.amount_paise) * expected_probability

        # Update case diagnosis with new EV fields
        await self.db.update_case_diagnosis_ev(
            case_id, diagnosis, interventions_dump, expected_probability, cost, expected_recovered, priority_score
        )

        # ── POLICY CHECK ──────────────────────────────────────────────────────
        policy_result = RecoveryPolicyEngine.validate(
            failure_type=case.failure_type,
            recovery_attempts=case.recovery_attempts,
            customer_contacts=case.customer_contacts,
            ai_recommended_action=diagnosis.recommended_action,
        )

        await self.db.update_case_policy(case_id, policy_result)

        # ── IDEMPOTENCY CHECK ─────────────────────────────────────────────────
        idem_key = _make_idempotency_key(case_id, run_id, policy_result.action)
        existing = await self.db.get_recovery_action_by_idempotency(idem_key)
        if existing:
            return {"event": self._make_event(case, diagnosis, policy_result, "duplicate", False), "outcome": "duplicate"}

        # ── EXECUTE or STOP ───────────────────────────────────────────────────
        if policy_result.stop and not policy_result.escalate:
            await self.db.mark_case_stopped(case_id, policy_result.reason)
            return {"event": self._make_event(case, diagnosis, policy_result, "stopped", True), "outcome": "stopped"}

        if policy_result.escalate and not policy_result.permitted:
            await self.db.mark_case_escalated(case_id, policy_result.reason)
            return {"event": self._make_event(case, diagnosis, policy_result, "escalated", True), "outcome": "escalated"}

        # ── RECOVERY EXECUTION ───────────────────────────────────────────────
        is_simulated = True
        payment_link_url = None
        razorpay_ref = None
        is_demo_001 = getattr(case, 'case_ref', '') == 'DEMO-001'

        if self.rzp.client and policy_result.action == ActionType.PAYMENT_LINK:
            try:
                import time
                expire_by = int(time.time()) + (20 * 60)
                plink = self.rzp.create_payment_link(
                    case.amount_paise, f"Recovery: {case.customer_name}",
                    {"case_id": case_id, "case_ref": case.case_ref, "run_id": run_id, "recovery": "true"}, expire_by
                )
                payment_link_url = plink.get("short_url") or plink.get("id")
                razorpay_ref = plink.get("id")
                is_simulated = False
                await self.db.update_case_payment_link(case_id, razorpay_ref, payment_link_url)
            except Exception as e:
                logger.error("recovery_agent.razorpay_link_failed", case_id=case_id, error=str(e))
                is_simulated = True

        if is_simulated:
            payment_link_url = f"https://rzp.io/i/simulated_{case.case_ref.lower()}"

        final_status = CaseStatus.AWAITING_PAYMENT
        outcome_str = "awaiting_payment"
        
        # Handle communications and Promise to pay
        if policy_result.action in [ActionType.WHATSAPP, ActionType.EMAIL, ActionType.SMS]:
            await self.db.log_communication(case_id, policy_result.action, "sent", "Here is your secure payment link: " + payment_link_url)
            final_status = CaseStatus.AWAITING_PAYMENT
            
        elif policy_result.action == ActionType.VOICE:
            # Voice agent simulation -> Promise to Pay
            await self.db.log_communication(case_id, policy_result.action, "answered", "Voice agent negotiated a promise to pay.")
            await self.db.create_promise_to_pay(case_id, case.amount_paise, "2026-09-07", policy_result.action)
            final_status = CaseStatus.PROMISE_TO_PAY
            outcome_str = "promise_to_pay"
            payment_link_url = None # Not a direct payment link case

        # Always mark case as recovered (simulated agent success) or awaiting/ptp
        await self.db.mark_case_recovered(
            case_id=case_id,
            recovered_amount_paise=case.amount_paise if (is_simulated and final_status == CaseStatus.AWAITING_PAYMENT) else 0,
            payment_link_url=payment_link_url,
            is_simulated=is_simulated,
            override_status=final_status
        )

        return {
            "event": self._make_event(case, diagnosis, policy_result, outcome_str, is_simulated),
            "outcome": outcome_str,
            "recovered_paise": case.amount_paise if is_simulated else 0,
            "is_simulated": is_simulated,
        }

    def _make_event(self, case, diagnosis, policy_result, outcome: str, is_simulated: bool) -> dict:
        return {
            "case_ref": getattr(case, 'case_ref', str(case.id)),
            "amount_paise": case.amount_paise,
            "failure_type": case.failure_type,
            "failure_reason": case.failure_reason,
            "ai_diagnosis": diagnosis.failure_class if diagnosis else None,
            "ai_confidence": diagnosis.confidence if diagnosis else None,
            "ai_recommendation": diagnosis.recommended_action if diagnosis else None,
            "policy_permitted": policy_result.permitted if policy_result else None,
            "policy_reason": policy_result.reason if policy_result else None,
            "action_type": policy_result.action if policy_result else None,
            "outcome": outcome,
            "is_simulated": is_simulated,
        }
