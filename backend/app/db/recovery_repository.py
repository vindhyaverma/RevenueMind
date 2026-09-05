"""
RecoveryRepository — All DB operations for RevenueMind revenue recovery.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.future import select
from sqlalchemy import update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recovery_models import RevenueRiskCase, RecoveryRun, RecoveryAction
from app.models.all_models import AuditEvent
from app.schemas.recovery_schemas import (
    CaseStatus, FailureClass, ActionType,
    FailureDiagnosis, RecoveryPolicyResult, MetricsSchema
)
from app.core.recovery_policy_engine import FAILURE_CLASS_MAP, RecoveryPolicyEngine


class RecoveryRepository:

    async def create_case(self, **kwargs) -> None:
        case = RevenueRiskCase(**kwargs)
        self.session.add(case)
        await self.session.commit()

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Case operations ─────────────────────────────────────────────────────

    async def get_recovery_case(self, case_id: str) -> Optional[RevenueRiskCase]:
        result = await self.session.execute(
            select(RevenueRiskCase).where(RevenueRiskCase.id == case_id)
        )
        return result.scalar_one_or_none()

    async def get_case_by_ref(self, case_ref: str) -> Optional[RevenueRiskCase]:
        result = await self.session.execute(
            select(RevenueRiskCase).where(RevenueRiskCase.case_ref == case_ref)
        )
        return result.scalar_one_or_none()

    async def list_cases(
        self,
        status: Optional[str] = None,
        failure_class: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[List[RevenueRiskCase], int]:
        q = select(RevenueRiskCase)
        if status:
            q = q.where(RevenueRiskCase.status == status)
        if failure_class:
            q = q.where(RevenueRiskCase.failure_class == failure_class)
        count_q = select(func.count()).select_from(q.subquery())
        total_r = await self.session.execute(count_q)
        total = total_r.scalar() or 0
        q = q.order_by(RevenueRiskCase.detected_at.desc())
        q = q.offset((page - 1) * size).limit(size)
        result = await self.session.execute(q)
        return result.scalars().all(), total

    async def get_all_pending_case_ids(self) -> List[str]:
        result = await self.session.execute(
            select(RevenueRiskCase.id).where(
                RevenueRiskCase.status.in_(["pending", "failed"])
            ).order_by(RevenueRiskCase.detected_at.asc())
        )
        return [str(r) for r in result.scalars().all()]

    async def update_case_field(self, case_id: str, field: str, value) -> None:
        await self.session.execute(
            update(RevenueRiskCase)
            .where(RevenueRiskCase.id == case_id)
            .values(**{field: value})
        )
        await self.session.commit()


    async def update_case_diagnosis_ev(self, case_id: str, diagnosis, interventions: list, probability: float, cost: int, expected: int, priority: float) -> None:
        await self.session.execute(
            update(RevenueRiskCase)
            .where(RevenueRiskCase.id == case_id)
            .values(
                failure_class=diagnosis.failure_class,
                ai_diagnosis=diagnosis.reasoning,
                ai_recommendation=diagnosis.recommended_action,
                ai_confidence=diagnosis.confidence,
                expected_recovery_probability=probability,
                recovery_cost_paise=cost,
                expected_recovered_paise=expected,
                priority_score=priority,
                interventions_json=interventions
            )
        )
        await self.session.commit()

    async def log_communication(self, case_id: str, channel: str, status: str, message: str) -> None:
        from app.models.recovery_models import RecoveryCommunication
        import uuid
        from app.db.session import DEMO_MODE
        c = RecoveryCommunication(
            id=str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4(),
            case_id=uuid.UUID(case_id) if not DEMO_MODE else case_id, # Actually UUID handling is done by GUID
            channel=channel,
            direction="outbound",
            message=message,
            status=status,
            is_simulated=True
        )
        self.session.add(c)
        await self.session.commit()

    async def create_promise_to_pay(self, case_id: str, amount: int, date_str: str, channel: str) -> None:
        from app.models.recovery_models import PromiseToPay
        import uuid
        from app.db.session import DEMO_MODE
        p = PromiseToPay(
            id=str(uuid.uuid4()) if DEMO_MODE else uuid.uuid4(),
            case_id=uuid.UUID(case_id) if not DEMO_MODE else case_id,
            amount_paise=amount,
            promised_date=date_str,
            channel=channel,
            status="pending"
        )
        self.session.add(p)
        await self.session.commit()

    async def get_pending_recovery_cases(self):
        result = await self.session.execute(
            select(RevenueRiskCase).where(
                RevenueRiskCase.status.in_(["pending", "failed"])
            ).order_by(RevenueRiskCase.detected_at.asc())
        )
        return result.scalars().all()

    async def update_case_diagnosis(self, case_id: str, diagnosis: FailureDiagnosis) -> None:
        await self.session.execute(
            update(RevenueRiskCase)
            .where(RevenueRiskCase.id == case_id)
            .values(
                failure_class=diagnosis.failure_class,
                ai_diagnosis=diagnosis.reasoning,
                ai_recommendation=diagnosis.recommended_action,
                ai_confidence=diagnosis.confidence,
            )
        )
        await self.session.commit()

    async def update_case_policy(self, case_id: str, policy_result: RecoveryPolicyResult) -> None:
        await self.session.execute(
            update(RevenueRiskCase)
            .where(RevenueRiskCase.id == case_id)
            .values(
                policy_result="permitted" if policy_result.permitted else "blocked",
                policy_reason=policy_result.reason,
                action_type=policy_result.action,
            )
        )
        await self.session.commit()

    async def update_case_payment_link(self, case_id: str, link_id: str, link_url: str) -> None:
        await self.session.execute(
            update(RevenueRiskCase)
            .where(RevenueRiskCase.id == case_id)
            .values(payment_link_id=link_id, payment_link_url=link_url)
        )
        await self.session.commit()

    async def mark_case_recovered(
        self,
        case_id: str,
        recovered_amount_paise: int,
        payment_link_url: Optional[str] = None,
        is_simulated: bool = True,
        override_status: str = CaseStatus.RECOVERED
    ) -> None:
        """
        Mark case as recovered. recovered_amount_paise is the deterministic amount
        from the case record — AI never sets this value.
        """
        updates = {
            "status": override_status,
            "recovered_amount_paise": recovered_amount_paise,
            "is_simulated_recovery": is_simulated,
            "final_outcome": "recovered",
            "action_status": "completed",
        }
        if payment_link_url:
            updates["payment_link_url"] = payment_link_url
        await self.session.execute(
            update(RevenueRiskCase).where(RevenueRiskCase.id == case_id).values(**updates)
        )
        await self.session.commit()

    async def mark_case_verified_recovered(self, case_id: str) -> None:
        """Called by webhook — upgrades RECOVERED to VERIFIED_RECOVERED."""
        await self.session.execute(
            update(RevenueRiskCase)
            .where(RevenueRiskCase.id == case_id)
            .values(
                status=CaseStatus.VERIFIED_RECOVERED,
                is_simulated_recovery=False,  # Razorpay webhook confirmed
                final_outcome="razorpay_verified",
            )
        )
        await self.session.commit()

    async def mark_case_escalated(self, case_id: str, reason: str) -> None:
        await self.session.execute(
            update(RevenueRiskCase)
            .where(RevenueRiskCase.id == case_id)
            .values(
                status=CaseStatus.ESCALATED,
                escalated=True,
                final_outcome="escalated",
                policy_reason=reason,
                action_status="escalated",
            )
        )
        await self.session.commit()

    async def mark_case_stopped(self, case_id: str, reason: str) -> None:
        await self.session.execute(
            update(RevenueRiskCase)
            .where(RevenueRiskCase.id == case_id)
            .values(
                status=CaseStatus.STOPPED,
                stopped_by_policy=True,
                final_outcome="stopped",
                policy_reason=reason,
                action_status="stopped",
            )
        )
        await self.session.commit()

    async def get_case_by_payment_link_id(self, link_id: str) -> Optional[RevenueRiskCase]:
        result = await self.session.execute(
            select(RevenueRiskCase).where(RevenueRiskCase.payment_link_id == link_id)
        )
        return result.scalar_one_or_none()

    # ── Action / idempotency ─────────────────────────────────────────────────

    async def get_recovery_action_by_idempotency(self, idempotency_key: str) -> Optional[RecoveryAction]:
        result = await self.session.execute(
            select(RecoveryAction).where(RecoveryAction.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def save_recovery_action(
        self,
        case_id: str,
        run_id: str,
        action_type: str,
        idempotency_key: str,
        policy_approved: bool,
        razorpay_ref: Optional[str],
        outcome: str,
        outcome_reason: str,
        is_simulated: bool = True,
    ) -> None:
        action = RecoveryAction(
            id=str(uuid.uuid4()),
            case_id=case_id,
            run_id=run_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
            policy_approved=policy_approved,
            razorpay_ref=razorpay_ref,
            outcome=outcome,
            outcome_reason=outcome_reason,
            is_simulated=is_simulated,
        )
        self.session.add(action)
        await self.session.commit()

    # ── Run operations ───────────────────────────────────────────────────────

    async def create_recovery_run(self, total_cases: int, total_at_risk_paise: int, recoverable_paise: int) -> RecoveryRun:
        run = RecoveryRun(
            id=str(uuid.uuid4()),
            status="pending",
            total_cases=total_cases,
            total_at_risk_paise=total_at_risk_paise,
            recoverable_paise=recoverable_paise,
            events_json=[],
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def update_run_status(self, run_id: str, status: str) -> None:
        updates = {"status": status}
        if status == "running":
            updates["started_at"] = datetime.now(timezone.utc)
        await self.session.execute(
            update(RecoveryRun).where(RecoveryRun.id == run_id).values(**updates)
        )
        await self.session.commit()

    async def update_run_progress(
        self, run_id: str, events: list,
        success_count: int, escalated_count: int, stopped_count: int,
        failed_count: int, duplicate_count: int,
        recovered_paise: int, agent_recovered_paise: int, razorpay_verified_paise: int
    ) -> None:
        processed = success_count + escalated_count + stopped_count + failed_count + duplicate_count
        await self.session.execute(
            update(RecoveryRun).where(RecoveryRun.id == run_id).values(
                processed_cases=processed,
                events_json=events,
                success_count=success_count,
                escalated_count=escalated_count,
                stopped_count=stopped_count,
                failed_count=failed_count,
                duplicate_count=duplicate_count,
                recovered_paise=recovered_paise,
                agent_recovered_paise=agent_recovered_paise,
                razorpay_verified_paise=razorpay_verified_paise,
            )
        )
        await self.session.commit()

    async def complete_run(
        self, run_id: str, events: list,
        success_count: int, escalated_count: int, stopped_count: int,
        failed_count: int, duplicate_count: int,
        recovered_paise: int, agent_recovered_paise: int, razorpay_verified_paise: int
    ) -> None:
        processed = success_count + escalated_count + stopped_count + failed_count + duplicate_count
        await self.session.execute(
            update(RecoveryRun).where(RecoveryRun.id == run_id).values(
                status="completed",
                completed_at=datetime.now(timezone.utc),
                processed_cases=processed,
                events_json=events,
                success_count=success_count,
                escalated_count=escalated_count,
                stopped_count=stopped_count,
                failed_count=failed_count,
                duplicate_count=duplicate_count,
                recovered_paise=recovered_paise,
                agent_recovered_paise=agent_recovered_paise,
                razorpay_verified_paise=razorpay_verified_paise,
            )
        )
        await self.session.commit()

    async def get_recovery_run(self, run_id: str) -> Optional[RecoveryRun]:
        result = await self.session.execute(
            select(RecoveryRun).where(RecoveryRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_run(self) -> Optional[RecoveryRun]:
        result = await self.session.execute(
            select(RecoveryRun).order_by(RecoveryRun.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def reset_pending_cases(self) -> None:
        """Reset all cases back to pending for a fresh run."""
        await self.session.execute(
            update(RevenueRiskCase)
            .where(RevenueRiskCase.status.in_([
                CaseStatus.RECOVERED, CaseStatus.ESCALATED, CaseStatus.STOPPED, CaseStatus.FAILED
            ]))
            .values(
                status=CaseStatus.PENDING,
                ai_diagnosis=None, ai_recommendation=None, ai_confidence=None,
                policy_result=None, policy_reason=None,
                action_type=None, action_status=None,
                recovered_amount_paise=0, is_simulated_recovery=True,
                escalated=False, stopped_by_policy=False,
                final_outcome=None, run_id=None,
                payment_link_id=None, payment_link_url=None,
                recovery_attempts=0, customer_contacts=0,
                failure_class=None,
            )
        )
        await self.session.commit()

    # ── Audit ────────────────────────────────────────────────────────────────

    async def log_audit_for_case(self, case_id: str, event_type: str, payload: dict) -> None:
        event = AuditEvent(
            session_id=case_id,  # reuse session_id column for case_id
            event_type=f"recovery.{event_type}",
            payload=payload,
        )
        self.session.add(event)
        await self.session.commit()

    async def get_case_audit_trail(self, case_id: str) -> list:
        result = await self.session.execute(
            select(AuditEvent)
            .where(AuditEvent.session_id == case_id)
            .order_by(AuditEvent.timestamp.asc())
        )
        return result.scalars().all()

    # ── Metrics (calculated from DB records, not from AI) ────────────────────

    async def get_metrics(self) -> MetricsSchema:
        """
        Calculate dashboard KPIs from DB records.
        Financial metrics are NEVER from AI output.
        """
        # Total at risk = sum of all case amounts
        total_q = await self.session.execute(
            select(func.sum(RevenueRiskCase.amount_paise))
        )
        total_at_risk = total_q.scalar() or 0

        # Recoverable = sum of TRANSIENT + RECOVERABLE class amounts
        recoverable_q = await self.session.execute(
            select(func.sum(RevenueRiskCase.amount_paise))
            .where(RevenueRiskCase.failure_class.in_([FailureClass.TRANSIENT, FailureClass.RECOVERABLE]))
        )
        recoverable = recoverable_q.scalar() or 0

        # Recovered = sum of recovered_amount_paise from recovered cases
        recovered_q = await self.session.execute(
            select(func.sum(RevenueRiskCase.recovered_amount_paise))
            .where(RevenueRiskCase.status.in_([CaseStatus.RECOVERED, CaseStatus.VERIFIED_RECOVERED]))
        )
        recovered = recovered_q.scalar() or 0

        # Agent-simulated vs Razorpay-verified
        agent_q = await self.session.execute(
            select(func.sum(RevenueRiskCase.recovered_amount_paise))
            .where(RevenueRiskCase.is_simulated_recovery == True)
            .where(RevenueRiskCase.status.in_([CaseStatus.RECOVERED, CaseStatus.VERIFIED_RECOVERED]))
        )
        agent_recovered = agent_q.scalar() or 0

        rzp_q = await self.session.execute(
            select(func.sum(RevenueRiskCase.recovered_amount_paise))
            .where(RevenueRiskCase.is_simulated_recovery == False)
            .where(RevenueRiskCase.status == CaseStatus.VERIFIED_RECOVERED)
        )
        razorpay_verified = rzp_q.scalar() or 0

        # Count by status
        def count_q(status_val):
            return select(func.count()).where(RevenueRiskCase.status == status_val)

        total_c = (await self.session.execute(select(func.count(RevenueRiskCase.id)))).scalar() or 0
        success_c = (await self.session.execute(
            select(func.count()).where(RevenueRiskCase.status.in_([CaseStatus.RECOVERED, CaseStatus.VERIFIED_RECOVERED]))
        )).scalar() or 0
        escalated_c = (await self.session.execute(count_q(CaseStatus.ESCALATED))).scalar() or 0
        stopped_c = (await self.session.execute(count_q(CaseStatus.STOPPED))).scalar() or 0
        pending_c = (await self.session.execute(count_q(CaseStatus.PENDING))).scalar() or 0
        failed_c = (await self.session.execute(count_q(CaseStatus.FAILED))).scalar() or 0

        # Recovery rate = recovered / recoverable * 100
        # Use pre-classified recoverable amount; if no cases classified yet, estimate from failure types
        if recoverable == 0:
            recoverable_estimate_q = await self.session.execute(
                select(func.sum(RevenueRiskCase.amount_paise))
                .where(RevenueRiskCase.failure_type.in_([
                    "upi_timeout", "network_timeout", "bank_unavailable",
                    "checkout_abandoned", "payment_link_expired", "session_expired"
                ]))
            )
            recoverable = recoverable_estimate_q.scalar() or 1

        recovery_rate = round((recovered / recoverable * 100), 1) if recoverable > 0 else 0.0

        # Latest run info
        latest_run = await self.get_latest_run()

        return MetricsSchema(
            total_at_risk_paise=total_at_risk,
            recoverable_paise=recoverable,
            recovered_paise=recovered,
            agent_recovered_paise=agent_recovered,
            razorpay_verified_paise=razorpay_verified,
            recovery_rate=recovery_rate,
            total_cases=total_c,
            success_count=success_c,
            escalated_count=escalated_c,
            stopped_count=stopped_c,
            pending_count=pending_c,
            failed_count=failed_c,
            last_run_id=str(latest_run.id) if latest_run else None,
            last_run_status=latest_run.status if latest_run else None,
        )

    async def update_recovery_run(self, run_id: str, **kwargs) -> None:
        await self.session.execute(
            update(RecoveryRun)
            .where(RecoveryRun.id == run_id)
            .values(**kwargs)
        )
        await self.session.commit()

    async def update_case_status(self, case_id: str, status: str, run_id: str) -> None:
        await self.session.execute(
            update(RevenueRiskCase)
            .where(RevenueRiskCase.id == case_id)
            .values(status=status, run_id=run_id, updated_at=func.now())
        )
        await self.session.commit()
