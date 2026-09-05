from fastapi import APIRouter, Depends, HTTPException, Request, Header
from typing import Optional
from pydantic import BaseModel, Field
import uuid
import os

from app.db.session import AsyncSessionLocal
from app.db.repository import DBRepository
from app.db.recovery_repository import RecoveryRepository
from app.ai.gemini_provider import GeminiProvider
from app.core.razorpay_client import RazorpayClient
from app.api.agent import AgentOrchestrator
from app.core.webhook_verifier import WebhookVerifier
from app.core.logger import StructuredLogger

logger = StructuredLogger("endpoints")
router = APIRouter(prefix="/api/v1")

async def get_db():
    async with AsyncSessionLocal() as session:
        yield DBRepository(session)

async def get_recovery_db():
    async with AsyncSessionLocal() as session:
        yield RecoveryRepository(session)

def get_ai_provider():
    return GeminiProvider()

def get_rzp_client():
    return RazorpayClient()


class ShopRequest(BaseModel):
    user_intent: str = Field(min_length=1, max_length=500)
    mandate_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None


@router.post("/agent/shop")
async def shop(
    req: ShopRequest,
    db: DBRepository = Depends(get_db),
    ai: GeminiProvider = Depends(get_ai_provider),
    rzp: RazorpayClient = Depends(get_rzp_client)
):
    session_id = req.session_id or uuid.uuid4()
    agent = AgentOrchestrator(ai, rzp, db)
    try:
        await db.log_audit(session_id, "session_started", {"intent": req.user_intent})
        result = await agent.process_intent(session_id, req.mandate_id, req.user_intent)
        return result
    except Exception as e:
        logger.error("api.agent.shop_failed", error=str(e), session_id=str(session_id))
        if hasattr(db, "session"):
            await db.session.rollback()
        try:
            await db.log_audit(session_id, "agent_failed", {"error": str(e)})
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
    db: DBRepository = Depends(get_db),
    recovery_db: RecoveryRepository = Depends(get_recovery_db)
):
    """
    Handle Razorpay webhook events:
    - payment_link.paid  → recovery case verified by Razorpay (Track 3)
    - payment.captured   → original agent order paid
    - payment.failed     → release inventory
    """
    payload = await request.body()
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")

    if not WebhookVerifier.verify(payload, x_razorpay_signature, secret):
        logger.error("webhook.verification_failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = await request.json()
    event_type = data.get("event")
    payload_obj = data.get("payload", {})

    # ── payment_link.paid → Track 3 recovery verified ─────────────────────────
    if event_type == "payment_link.paid":
        pl_entity = payload_obj.get("payment_link", {}).get("entity", {})
        link_id = pl_entity.get("id")
        payment_entity = payload_obj.get("payment", {}).get("entity", {})
        payment_id = payment_entity.get("id")

        if link_id:
            try:
                case = await recovery_db.get_case_by_payment_link_id(link_id)
                if case:
                    await recovery_db.mark_case_verified_recovered(str(case.id))
                    await recovery_db.log_audit_for_case(str(case.id), "webhook_verified_recovered", {
                        "payment_link_id": link_id,
                        "payment_id": payment_id,
                        "amount_paise": payment_entity.get("amount"),
                        "razorpay_verified": True,
                    })
                    logger.info("webhook.recovery_verified", link_id=link_id, case_id=str(case.id))
            except Exception as e:
                logger.error("webhook.recovery_link_update_failed", error=str(e), link_id=link_id)

    # ── payment.captured → original agent order ───────────────────────────────
    elif event_type == "payment.captured":
        payment = payload_obj.get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})
        session_id = notes.get("session_id")
        if session_id:
            try:
                sess_uuid = uuid.UUID(session_id)
                order_id = payment.get("order_id")
                if order_id:
                    await db.update_order_status_by_razorpay_id(order_id, "paid")
                await db.log_audit(sess_uuid, "payment_confirmed", {
                    "payment_id": payment.get("id"),
                    "order_id": order_id,
                    "amount_paise": payment.get("amount"),
                })
            except ValueError:
                pass

    # ── payment.failed → release inventory ────────────────────────────────────
    elif event_type == "payment.failed":
        payment = payload_obj.get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})
        session_id = notes.get("session_id")
        if session_id:
            try:
                sess_uuid = uuid.UUID(session_id)
                order_id = payment.get("order_id")
                if order_id:
                    await db.release_inventory_by_order(order_id)
                    await db.update_order_status_by_razorpay_id(order_id, "failed")
                await db.log_audit(sess_uuid, "payment_failed", {
                    "reason": payment.get("error_description", "Unknown"),
                    "payment_id": payment.get("id"),
                    "order_id": order_id,
                })
            except ValueError:
                pass
    else:
        logger.info("webhook.unhandled_event", event=event_type)

    logger.info("webhook.processed", event=event_type)
    return {"status": "ok"}


@router.get("/audit/{session_id}")
async def get_audit(session_id: uuid.UUID, db: DBRepository = Depends(get_db)):
    events = await db.get_audit_trail(session_id)
    return {
        "session_id": session_id,
        "events": [{"type": e.event_type, "payload": e.payload, "timestamp": e.timestamp} for e in events]
    }
