from fastapi import APIRouter, Depends, HTTPException, Request, Header
from typing import Optional
from pydantic import BaseModel
import uuid
import os

from app.db.session import AsyncSessionLocal
from app.db.repository import DBRepository
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
        
def get_ai_provider():
    return GeminiProvider()

def get_rzp_client():
    return RazorpayClient()

from pydantic import BaseModel, Field

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
        # Rollback the transaction in case it was left in a failed state
        await db.session.rollback()
        try:
            await db.log_audit(session_id, "agent_failed", {"error": str(e)})
        except Exception:
            pass # Failsafe so we don't crash the endpoint if audit logging fails
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
    db: DBRepository = Depends(get_db)
):
    payload = await request.body()
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    
    if not WebhookVerifier.verify(payload, x_razorpay_signature, secret):
        logger.error("webhook.verification_failed")
        raise HTTPException(status_code=400, detail="Invalid signature")
        
    data = await request.json()
    event_type = data.get("event")
    payload_obj = data.get("payload", {})
    
    payment = payload_obj.get("payment", {}).get("entity", {})
    notes = payment.get("notes", {})
    session_id = notes.get("session_id")
    
    if session_id:
        try:
            sess_uuid = uuid.UUID(session_id)
            await db.log_audit(sess_uuid, f"webhook_received:{event_type}", {"payment_id": payment.get("id")})
        except ValueError:
            pass
            
    logger.info("webhook.processed", event=event_type)
    return {"status": "ok"}

@router.get("/audit/{session_id}")
async def get_audit(session_id: uuid.UUID, db: DBRepository = Depends(get_db)):
    events = await db.get_audit_trail(session_id)
    return {"session_id": session_id, "events": [{"type": e.event_type, "payload": e.payload, "timestamp": e.timestamp} for e in events]}
