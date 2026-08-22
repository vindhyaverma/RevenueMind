from fastapi import APIRouter, Depends, HTTPException
import uuid
from app.db.session import AsyncSessionLocal
from app.db.repository import DBRepository
from app.core.logger import StructuredLogger

logger = StructuredLogger("demo_api")
router = APIRouter(prefix="/api/v1/demo")

async def get_db():
    async with AsyncSessionLocal() as session:
        yield DBRepository(session)

@router.post("/trigger-inventory-failure")
async def trigger_inventory_failure(product_id: uuid.UUID, db: DBRepository = Depends(get_db)):
    """
    Simulates a race condition by setting a product's inventory to 0 
    during a demo right before the agent attempts to purchase it.
    """
    try:
        # We would execute an update query here. Since we use a MockDB in tests,
        # we'll write the expected repository call.
        await db.set_inventory(product_id, 0)
        logger.warning("demo.inventory_race_condition_triggered", product_id=str(product_id))
        return {"status": "success", "message": f"Inventory for {product_id} set to 0"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
