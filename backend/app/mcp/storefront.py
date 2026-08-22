from mcp.server.fastmcp import FastMCP
from typing import Optional, List
import uuid

# In a real environment, we would inject the database and orchestrator 
# dynamically or via context, but for MCP server simplicity we will define
# tools that interact with the MerchantMind REST API or DB directly.

# To keep the AI bound, the MCP tools don't directly execute payments, 
# they use the Orchestrator or the REST endpoints.

mcp = FastMCP("MerchantMind Storefront")

# Mocking the dependency injection for MCP context
from app.db.session import AsyncSessionLocal
from app.db.repository import DBRepository
from app.ai.gemini_provider import GeminiProvider
from app.core.razorpay_client import RazorpayClient
from app.api.agent import AgentOrchestrator

async def get_orchestrator():
    session = AsyncSessionLocal()
    db = DBRepository(session)
    ai = GeminiProvider()
    rzp = RazorpayClient()
    return AgentOrchestrator(ai, rzp, db), db, session

@mcp.tool()
async def search_catalog(category: str, max_price_paise: int) -> list:
    """Search the merchant's catalog for products."""
    orchestrator, db, session = await get_orchestrator()
    try:
        products = await db.search_products(category, max_price_paise)
        return [p.model_dump(mode="json") for p in products]
    finally:
        await session.close()

@mcp.tool()
async def get_product(product_id: str) -> dict:
    """Get details for a specific product."""
    orchestrator, db, session = await get_orchestrator()
    try:
        product = await db.get_product(uuid.UUID(product_id))
        return product.model_dump(mode="json")
    finally:
        await session.close()

@mcp.tool()
async def create_purchase_intent(session_id: str, mandate_id: str, user_intent: str) -> dict:
    """
    Submits a purchase intent. The system will parse the intent, 
    check mandate, run preflight guards, and attempt purchase.
    """
    orchestrator, db, session = await get_orchestrator()
    try:
        sess_uuid = uuid.UUID(session_id)
        mand_uuid = uuid.UUID(mandate_id)
        await db.log_audit(sess_uuid, "mcp_intent_received", {"intent": user_intent})
        result = await orchestrator.process_intent(sess_uuid, mand_uuid, user_intent)
        return result
    except Exception as e:
        return {"error": str(e), "status": "failed"}
    finally:
        await session.close()

@mcp.tool()
async def get_order_status(session_id: str) -> dict:
    """Retrieve the audit and order status for a session."""
    orchestrator, db, session = await get_orchestrator()
    try:
        events = await db.get_audit_trail(uuid.UUID(session_id))
        return {"events": [{"type": e.event_type, "payload": e.payload} for e in events]}
    finally:
        await session.close()

if __name__ == "__main__":
    mcp.run()
