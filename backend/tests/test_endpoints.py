import pytest
import uuid
import json
import hmac
import hashlib
from fastapi.testclient import TestClient
from app.main import app
from app.api.endpoints import get_db, get_ai_provider, get_rzp_client
from app.schemas.schemas import ParsedIntentSchema, ProductRankingSchema, ProductSchema
from app.models.all_models import AuditEvent

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
            selected_product_id=available_products[1].id,
            reason="Recovering from failure",
            alternatives=[]
        )

class MockDB:
    def __init__(self):
        self.events = []
        p1 = ProductSchema(id=uuid.uuid4(), merchant_id=uuid.uuid4(), name="Cake 1", description="", category="food", price_paise=500, inventory=1)
        self._products = {p1.id: p1}
        
        class MockMandate:
            id = uuid.uuid4()
            transaction_limit_paise = 1000
            daily_limit_paise = 2000
            auto_approve_limit_paise = 1000
            allowed_categories = ["food"]
            merchant_whitelist = None
            expires_at = None
            
        self._mandate = MockMandate()
        
    async def search_products(self, category, max_price):
        return list(self._products.values())
        
    async def get_product(self, product_id):
        return self._products[product_id]
        
    async def get_mandate(self, mandate_id):
        return self._mandate
        
    async def get_daily_spend(self, mandate_id):
        return 0
        
    async def has_order(self, session_id, product_id):
        return False
        
    async def save_order(self, session_id, mandate_id, product_id, order_id, amount, idempotency_key):
        pass
        
    async def log_audit(self, session_id, event_type, payload):
        event = AuditEvent(session_id=session_id, event_type=event_type, payload=payload)
        self.events.append(event)
        
    async def get_audit_trail(self, session_id):
        return [e for e in self.events if e.session_id == session_id]

class MockRazorpay:
    def create_order(self, amount, notes):
        return {"id": "order_mock", "amount": amount, "status": "created"}

db_instance = MockDB()

def override_get_db():
    return db_instance
    
def override_get_ai():
    return MockAIProvider()

def override_get_rzp():
    return MockRazorpay()

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_ai_provider] = override_get_ai
app.dependency_overrides[get_rzp_client] = override_get_rzp

client = TestClient(app)

def test_shop_endpoint():
    mandate_id = str(uuid.uuid4())
    req_body = {
        "user_intent": "I want a cake",
        "mandate_id": mandate_id
    }
    
    response = client.post("/api/v1/agent/shop", json=req_body)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "autonomous_order_created"
    assert "order_id" in data

def test_audit_endpoint():
    session_id = uuid.uuid4()
    
    # Generate some mock events
    import asyncio
    asyncio.run(db_instance.log_audit(session_id, "test_event", {"foo": "bar"}))
    
    response = client.get(f"/api/v1/audit/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == str(session_id)
    assert len(data["events"]) > 0
    assert data["events"][0]["type"] == "test_event"

def test_webhook_endpoint(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test_secret")
    payload = b'{"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_123", "notes": {"session_id": "8dfa1336-633d-4282-8b7b-cbbfb83600ee"}}}}}'
    signature = hmac.new(b"test_secret", payload, hashlib.sha256).hexdigest()
    
    response = client.post(
        "/api/v1/webhooks/razorpay", 
        content=payload,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"}
    )
    
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_webhook_endpoint_invalid_signature(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test_secret")
    payload = b'{"event": "payment.captured"}'
    
    response = client.post(
        "/api/v1/webhooks/razorpay", 
        content=payload,
        headers={"X-Razorpay-Signature": "invalid_sig"}
    )
    
    assert response.status_code == 400
