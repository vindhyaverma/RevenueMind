import pytest
import uuid
from unittest.mock import patch, AsyncMock
from app.mcp.storefront import search_catalog, get_product, create_purchase_intent, get_order_status
from app.schemas.schemas import ProductSchema

# Mock the database repository for MCP tests
@pytest.fixture
def mock_orchestrator():
    class MockSession:
        async def close(self): pass
        
    class MockDB:
        async def search_products(self, category, max_price):
            p1 = ProductSchema(id=uuid.uuid4(), merchant_id=uuid.uuid4(), name="Cake", description="", category="food", price_paise=500, inventory=1)
            return [p1]
            
        async def get_product(self, product_id):
            return ProductSchema(id=product_id, merchant_id=uuid.uuid4(), name="Cake", description="", category="food", price_paise=500, inventory=1)
            
        async def log_audit(self, session_id, event, payload):
            pass
            
        async def get_audit_trail(self, session_id):
            return []

    class MockOrchestrator:
        async def process_intent(self, session_id, mandate_id, user_intent):
            if "fail" in user_intent:
                raise Exception("Preflight check failed")
            return {"status": "autonomous_order_created", "order_id": "order_123"}
            
    with patch("app.mcp.storefront.get_orchestrator", new_callable=AsyncMock) as mock:
        mock.return_value = (MockOrchestrator(), MockDB(), MockSession())
        yield mock

@pytest.mark.asyncio
async def test_mcp_search_catalog(mock_orchestrator):
    results = await search_catalog("food", 1000)
    assert len(results) == 1
    assert results[0]["name"] == "Cake"

@pytest.mark.asyncio
async def test_mcp_get_product(mock_orchestrator):
    pid = str(uuid.uuid4())
    result = await get_product(pid)
    assert result["id"] == pid

@pytest.mark.asyncio
async def test_mcp_create_purchase_intent_success(mock_orchestrator):
    sid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    result = await create_purchase_intent(sid, mid, "I want a cake")
    assert result["status"] == "autonomous_order_created"
    
@pytest.mark.asyncio
async def test_mcp_create_purchase_intent_fail(mock_orchestrator):
    sid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    result = await create_purchase_intent(sid, mid, "I want to fail")
    assert result["status"] == "failed"
    assert "Preflight check failed" in result["error"]
