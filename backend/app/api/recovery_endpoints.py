"""
Recovery API endpoints for RevenueMind Track 3.

POST /api/v1/recovery/run              — Start batch recovery run
GET  /api/v1/recovery/run/{run_id}     — Run status + live events
GET  /api/v1/recovery/cases            — List cases (filterable)
GET  /api/v1/recovery/cases/{case_id} — Case detail + audit trail
GET  /api/v1/recovery/audit/{case_id} — Case audit trail
GET  /api/v1/recovery/metrics          — Dashboard KPIs (from DB)
POST /api/v1/recovery/reset            — Reset cases for re-run (demo only)
"""

import os
import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import Optional
from pydantic import BaseModel

from app.db.session import AsyncSessionLocal
from app.db.recovery_repository import RecoveryRepository
from app.core.razorpay_client import RazorpayClient
from app.core.logger import StructuredLogger
from app.api.recovery_agent import RevenueRecoveryAgent
from app.schemas.recovery_schemas import CaseSchema, RecoveryRunSchema, MetricsSchema

logger = StructuredLogger("recovery_endpoints")
router = APIRouter(prefix="/api/v1/recovery")

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# ── Dependency injection ─────────────────────────────────────────────────────

async def get_recovery_db():
    async with AsyncSessionLocal() as session:
        yield RecoveryRepository(session)

def get_rzp():
    return RazorpayClient()


# ── Background task helpers ──────────────────────────────────────────────────

async def _run_batch_background(run_id: str):
    """Runs the full batch recovery in background. Creates its own DB session."""
    async with AsyncSessionLocal() as session:
        db = RecoveryRepository(session)
        rzp = RazorpayClient()
        agent = RevenueRecoveryAgent(db=db, razorpay_client=rzp, demo_mode=DEMO_MODE)

        case_ids = await db.get_all_pending_case_ids()
        if not case_ids:
            await db.update_run_status(run_id, "completed")
            return

        await agent.process_batch(run_id)


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/run")
async def start_recovery_run(
    background_tasks: BackgroundTasks,
    db: RecoveryRepository = Depends(get_recovery_db),
):
    """
    Start a batch recovery run for all pending cases.
    Returns immediately with run_id. Frontend polls GET /run/{run_id}.
    """
    # Check if a run is already active
    latest = await db.get_latest_run()
    if latest and latest.status == "running":
        return {"run_id": str(latest.id), "status": "already_running", "message": "Recovery run already in progress."}

    # Compute totals for the run header
    metrics = await db.get_metrics()
    case_ids = await db.get_all_pending_case_ids()
    if not case_ids:
        raise HTTPException(status_code=400, detail="No pending cases to recover. Use /reset to re-run.")

    run = await db.create_recovery_run(
        total_cases=len(case_ids),
        total_at_risk_paise=metrics.total_at_risk_paise,
        recoverable_paise=metrics.recoverable_paise,
    )

    background_tasks.add_task(_run_batch_background, str(run.id))

    logger.info("recovery.run.started", run_id=str(run.id), total_cases=len(case_ids))
    return {"run_id": str(run.id), "status": "started", "total_cases": len(case_ids)}


@router.get("/run/latest")
async def get_latest_run(db: RecoveryRepository = Depends(get_recovery_db)):
    """Get the most recent run."""
    run = await db.get_latest_run()
    if not run:
        return {"status": "no_runs"}
    return _serialize_run(run)


@router.get("/run/{run_id}")
async def get_recovery_run(run_id: str, db: RecoveryRepository = Depends(get_recovery_db)):
    """Get run status and live events. Frontend polls this every 800ms."""
    run = await db.get_recovery_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_run(run)


def _serialize_run(run) -> dict:
    return {
        "id": str(run.id),
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "total_cases": run.total_cases,
        "processed_cases": run.processed_cases,
        "total_at_risk_paise": run.total_at_risk_paise,
        "recoverable_paise": run.recoverable_paise,
        "recovered_paise": run.recovered_paise,
        "agent_recovered_paise": run.agent_recovered_paise,
        "razorpay_verified_paise": run.razorpay_verified_paise,
        "success_count": run.success_count,
        "escalated_count": run.escalated_count,
        "stopped_count": run.stopped_count,
        "failed_count": run.failed_count,
        "duplicate_count": run.duplicate_count,
        "events": run.events_json or [],
    }


@router.get("/metrics")
async def get_metrics(db: RecoveryRepository = Depends(get_recovery_db)):
    """
    Dashboard KPIs — all calculated from DB records.
    Financial metrics are NEVER from AI output.
    """
    metrics = await db.get_metrics()
    return metrics.model_dump()


@router.get("/cases")
async def list_cases(
    status: Optional[str] = None,
    failure_class: Optional[str] = None,
    page: int = 1,
    size: int = 50,
    db: RecoveryRepository = Depends(get_recovery_db),
):
    """List recovery cases with optional filtering."""
    size = min(size, 200)  # cap
    cases, total = await db.list_cases(status=status, failure_class=failure_class, page=page, size=size)
    return {
        "cases": [_serialize_case(c) for c in cases],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/cases/{case_id}")
async def get_case_detail(case_id: str, db: RecoveryRepository = Depends(get_recovery_db)):
    """
    Get a single case with its full audit trail.
    Supports lookup by case UUID or by case_ref (e.g. DEMO-001).
    """
    # Try by ref first (more user-friendly)
    case = await db.get_case_by_ref(case_id)
    if not case:
        case = await db.get_recovery_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    audit = await db.get_case_audit_trail(str(case.id))
    result = _serialize_case(case)
    result["audit_trail"] = [
        {
            "event_type": e.event_type,
            "payload": e.payload,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        }
        for e in audit
    ]
    return result


@router.get("/audit/{case_id}")
async def get_case_audit(case_id: str, db: RecoveryRepository = Depends(get_recovery_db)):
    """Get the structured audit trail for a case."""
    case = await db.get_case_by_ref(case_id)
    if not case:
        case = await db.get_recovery_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    audit = await db.get_case_audit_trail(str(case.id))
    return {
        "case_id": str(case.id),
        "case_ref": case.case_ref,
        "amount_paise": case.amount_paise,
        "status": case.status,
        "audit_trail": [
            {
                "event_type": e.event_type,
                "payload": e.payload,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            }
            for e in audit
        ],
    }


@router.post("/reset")
async def reset_cases(db: RecoveryRepository = Depends(get_recovery_db)):
    """Demo only: reset all cases to pending for a fresh recovery run."""
    if not DEMO_MODE:
        raise HTTPException(status_code=403, detail="Reset only available in DEMO_MODE.")
    await db.reset_pending_cases()
    logger.info("recovery.cases_reset")
    return {"status": "reset", "message": "All cases reset to pending. Ready for new run."}



def _serialize_case(case) -> dict:
    return {
        "id": str(case.id),
        "case_ref": case.case_ref,
        "merchant_id": str(case.merchant_id),
        "customer_ref": case.customer_ref,
        "customer_name": case.customer_name,
        "amount_paise": case.amount_paise,
        "failure_type": case.failure_type,
        "failure_reason": case.failure_reason,
        "failure_class": case.failure_class,
        "ai_diagnosis": case.ai_diagnosis,
        "ai_recommendation": case.ai_recommendation,
        "ai_confidence": case.ai_confidence,
        "expected_recovery_probability": case.expected_recovery_probability,
        "interventions_json": case.interventions_json,
        "is_subscription": case.is_subscription,
        "customer_ltv_paise": case.customer_ltv_paise,
        "customer_successful_payments": case.customer_successful_payments,
        "recovery_cost_paise": case.recovery_cost_paise,
        "expected_recovered_paise": case.expected_recovered_paise,
        "priority_score": case.priority_score,
        "policy_result": case.policy_result,
        "policy_reason": case.policy_reason,
        "action_type": case.action_type,
        "action_status": case.action_status,
        "recovery_attempts": case.recovery_attempts,
        "customer_contacts": case.customer_contacts,
        "payment_link_url": case.payment_link_url,
        "recovered_amount_paise": case.recovered_amount_paise,
        "is_simulated_recovery": case.is_simulated_recovery,
        "escalated": case.escalated,
        "stopped_by_policy": case.stopped_by_policy,
        "final_outcome": case.final_outcome,
        "status": case.status,
        "run_id": str(case.run_id) if case.run_id else None,
        "detected_at": case.detected_at.isoformat() if case.detected_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }
