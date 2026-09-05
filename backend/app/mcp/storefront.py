"""
RevenueMind MCP Server — Recovery tools for AI agents.

Every tool routes through the deterministic RecoveryPolicyEngine.
MCP is NOT an alternate payment path. It enforces the same policy rules.
"""

from mcp.server.fastmcp import FastMCP
from typing import Optional
import uuid

mcp = FastMCP("RevenueMind Recovery")

from app.db.session import AsyncSessionLocal
from app.db.recovery_repository import RecoveryRepository
from app.core.recovery_policy_engine import RecoveryPolicyEngine, DEFAULT_POLICY


async def get_recovery_repo():
    session = AsyncSessionLocal()
    return RecoveryRepository(session), session


@mcp.tool()
async def get_revenue_at_risk() -> dict:
    """Get current revenue-at-risk metrics for the merchant."""
    db, session = await get_recovery_repo()
    try:
        metrics = await db.get_metrics()
        return metrics.model_dump()
    finally:
        await session.close()


@mcp.tool()
async def list_recovery_cases(status: Optional[str] = None, failure_class: Optional[str] = None) -> list:
    """List revenue recovery cases, optionally filtered by status or failure class."""
    db, session = await get_recovery_repo()
    try:
        cases, total = await db.list_cases(status=status, failure_class=failure_class, size=50)
        return [
            {
                "case_ref": c.case_ref,
                "customer_name": c.customer_name,
                "amount_paise": c.amount_paise,
                "failure_type": c.failure_type,
                "status": c.status,
                "recovered_amount_paise": c.recovered_amount_paise,
            }
            for c in cases
        ]
    finally:
        await session.close()


@mcp.tool()
async def get_recovery_case(case_ref: str) -> dict:
    """Get full details for a specific recovery case including AI diagnosis and policy decision."""
    db, session = await get_recovery_repo()
    try:
        case = await db.get_case_by_ref(case_ref)
        if not case:
            return {"error": f"Case {case_ref} not found"}
        return {
            "case_ref": case.case_ref,
            "customer_name": case.customer_name,
            "amount_paise": case.amount_paise,
            "failure_type": case.failure_type,
            "failure_reason": case.failure_reason,
            "failure_class": case.failure_class,
            "ai_diagnosis": case.ai_diagnosis,
            "ai_recommendation": case.ai_recommendation,
            "ai_confidence": case.ai_confidence,
            "policy_result": case.policy_result,
            "policy_reason": case.policy_reason,
            "status": case.status,
            "recovered_amount_paise": case.recovered_amount_paise,
            "is_simulated_recovery": case.is_simulated_recovery,
            "escalated": case.escalated,
            "stopped_by_policy": case.stopped_by_policy,
        }
    finally:
        await session.close()


@mcp.tool()
async def recommend_recovery(case_ref: str) -> dict:
    """
    Get the deterministic policy recommendation for a case.
    This is what the RecoveryPolicyEngine would decide — AI cannot override this.
    """
    db, session = await get_recovery_repo()
    try:
        case = await db.get_case_by_ref(case_ref)
        if not case:
            return {"error": f"Case {case_ref} not found"}

        policy_result = RecoveryPolicyEngine.validate(
            failure_type=case.failure_type,
            recovery_attempts=case.recovery_attempts,
            customer_contacts=case.customer_contacts,
        )

        return {
            "case_ref": case_ref,
            "amount_paise": case.amount_paise,
            "failure_type": case.failure_type,
            "policy_permitted": policy_result.permitted,
            "recommended_action": policy_result.action,
            "reason": policy_result.reason,
            "escalate": policy_result.escalate,
            "stop": policy_result.stop,
            "note": "This decision is deterministic. AI cannot override it.",
        }
    finally:
        await session.close()


@mcp.tool()
async def get_recovery_status(case_ref: str) -> dict:
    """Get the current recovery status and outcome for a case."""
    db, session = await get_recovery_repo()
    try:
        case = await db.get_case_by_ref(case_ref)
        if not case:
            return {"error": f"Case {case_ref} not found"}
        audit = await db.get_case_audit_trail(str(case.id))
        return {
            "case_ref": case_ref,
            "status": case.status,
            "final_outcome": case.final_outcome,
            "recovered_amount_paise": case.recovered_amount_paise,
            "is_simulated_recovery": case.is_simulated_recovery,
            "payment_link_url": case.payment_link_url,
            "audit_events": len(audit),
        }
    finally:
        await session.close()


if __name__ == "__main__":
    mcp.run()
