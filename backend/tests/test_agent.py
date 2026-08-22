import pytest
import uuid
from datetime import datetime, timezone
from app.api.agent import AgentOrchestrator
from app.schemas.schemas import ParsedIntentSchema, ProductRankingSchema, ProductAlternativeSchema, ProductSchema
from app.core.errors import AgentNotAuthorizedError

class MockAIProvider:
    async def parse_intent(self, user_request: str):
        return ParsedIntentSchema(action="purchase", query="cake", category="food", max_price_paise=1000, quantity=1)
        
    async def rank_products(self, intent, products):
        return ProductRankingSchema(
            selected_product_id=products[0].id,
            reason="Best match",
            alternatives=[]
        )
        
    async def reason_recovery(self, intent, failed_product, reason, available_products):
        return ProductRankingSchema(
            selected_product_id=available_products[1].id, # Pick second product
            reason="Recovering from failure",
            alternatives=[]
        )

class MockDB:
    def __init__(self, products, mandate):
        self._products = {p.id: p for p in products}
        self._mandate = mandate
        self._inventory = {p.id: p.inventory for p in products}
        self.orders = []
        
    async def search_products(self, category, max_price):
        return [p for p in self._products.values() if self._inventory[p.id] > 0]
        
    async def get_product(self, product_id):
        p = self._products[product_id]
        from app.schemas.schemas import ProductSchema
        return ProductSchema(
            id=p.id, merchant_id=p.merchant_id, name=p.name,
            description=p.description, category=p.category,
            price_paise=p.price_paise, inventory=self._inventory[p.id]
        )
        
    async def get_mandate(self, mandate_id):
        return self._mandate
        
    async def get_daily_spend(self, mandate_id):
        return 0
        
    async def has_order(self, session_id, product_id):
        return False

    async def reserve_inventory_atomic(self, product_id):
        if self._inventory[product_id] > 0:
            self._inventory[product_id] -= 1
            return True
        return False

    async def release_inventory(self, product_id):
        self._inventory[product_id] += 1
        
    async def save_order(self, session_id, mandate_id, product_id, order_id, amount, idempotency_key):
        self.orders.append(order_id)
        
    async def log_audit(self, session_id, event_type, payload):
        pass

class MockRazorpay:
    def create_order(self, amount, notes):
        return {"id": "order_mock", "amount": amount, "status": "created"}
        
    def create_payment_link(self, amount, desc, notes, expire):
        return {"id": "plink_mock", "short_url": "https://rzp.io/mock"}

@pytest.mark.asyncio
async def test_agent_orchestrator_happy_path():
    merchant_id = uuid.uuid4()
    p1 = ProductSchema(id=uuid.uuid4(), merchant_id=merchant_id, name="Cake 1", description="", category="food", price_paise=500, inventory=1)
    p2 = ProductSchema(id=uuid.uuid4(), merchant_id=merchant_id, name="Cake 2", description="", category="food", price_paise=600, inventory=1)
    
    class MockMandate:
        id = uuid.uuid4()
        transaction_limit_paise = 1000
        daily_limit_paise = 2000
        auto_approve_limit_paise = 1000
        allowed_categories = ["food"]
        merchant_whitelist = None
        expires_at = None
        
    db = MockDB([p1, p2], MockMandate())
    agent = AgentOrchestrator(MockAIProvider(), MockRazorpay(), db)
    
    res = await agent.process_intent(uuid.uuid4(), MockMandate().id, "I want a cake")
    assert res["status"] == "autonomous_order_created"
    assert len(db.orders) == 1

@pytest.mark.asyncio
async def test_agent_orchestrator_recovery():
    # First product has 0 inventory
    merchant_id = uuid.uuid4()
    p1 = ProductSchema(id=uuid.uuid4(), merchant_id=merchant_id, name="Cake 1", description="", category="food", price_paise=500, inventory=0)
    p2 = ProductSchema(id=uuid.uuid4(), merchant_id=merchant_id, name="Cake 2", description="", category="food", price_paise=600, inventory=1)
    
    class MockMandate:
        id = uuid.uuid4()
        transaction_limit_paise = 1000
        daily_limit_paise = 2000
        auto_approve_limit_paise = 1000
        allowed_categories = ["food"]
        merchant_whitelist = None
        expires_at = None
        
    db = MockDB([p1, p2], MockMandate())
    agent = AgentOrchestrator(MockAIProvider(), MockRazorpay(), db)
    
    # The AI provider is mocked to pick p1 first, fail preflight, and then recover by picking p2.
    res = await agent.process_intent(uuid.uuid4(), MockMandate().id, "I want a cake")
    assert res["status"] == "autonomous_order_created"
    assert len(db.orders) == 1

@pytest.mark.asyncio
async def test_agent_orchestrator_human_approval():
    merchant_id = uuid.uuid4()
    p1 = ProductSchema(id=uuid.uuid4(), merchant_id=merchant_id, name="Cake 1", description="", category="food", price_paise=800, inventory=1)
    
    class MockMandate:
        id = uuid.uuid4()
        transaction_limit_paise = 1000
        daily_limit_paise = 2000
        auto_approve_limit_paise = 500 # Set lower than price
        allowed_categories = ["food"]
        merchant_whitelist = None
        expires_at = None
        
    db = MockDB([p1], MockMandate())
    agent = AgentOrchestrator(MockAIProvider(), MockRazorpay(), db)
    
    res = await agent.process_intent(uuid.uuid4(), MockMandate().id, "I want a cake")
    assert res["status"] == "human_approval_required"
    assert "payment_link" in res
