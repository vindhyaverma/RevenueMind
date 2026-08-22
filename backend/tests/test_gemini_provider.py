import pytest
import uuid
import json
from unittest.mock import patch, AsyncMock
from app.ai.gemini_provider import GeminiProvider, GeminiProviderError
from app.schemas.schemas import ParsedIntentSchema, ProductSchema, ProductRankingSchema

@pytest.fixture
def mock_gemini():
    with patch("app.ai.gemini_provider.GeminiProvider._call_gemini", new_callable=AsyncMock) as mock:
        yield mock

@pytest.mark.asyncio
async def test_parse_intent(mock_gemini):
    mock_gemini.return_value = json.dumps({
        "action": "purchase",
        "query": "birthday cake",
        "category": "food",
        "max_price_paise": 50000,
        "occasion": "birthday",
        "quantity": 1,
        "preferences": ["chocolate"]
    })
    
    provider = GeminiProvider()
    result = await provider.parse_intent("I want a birthday cake under 500 Rs")
    
    assert result.action == "purchase"
    assert result.category == "food"
    assert result.max_price_paise == 50000

@pytest.mark.asyncio
async def test_rank_products(mock_gemini):
    prod_id = uuid.uuid4()
    mock_gemini.return_value = json.dumps({
        "selected_product_id": str(prod_id),
        "reason": "It is a cake",
        "alternatives": []
    })
    
    provider = GeminiProvider()
    intent = ParsedIntentSchema(action="purchase", query="cake", category="food", max_price_paise=1000, quantity=1)
    
    result = await provider.rank_products(intent, [])
    assert result.selected_product_id == prod_id
    assert result.reason == "It is a cake"

@pytest.mark.asyncio
async def test_reason_recovery_prevents_selecting_same_product(mock_gemini):
    prod_id = uuid.uuid4()
    mock_gemini.return_value = json.dumps({
        "selected_product_id": str(prod_id),
        "reason": "I still want this one",
        "alternatives": []
    })
    
    provider = GeminiProvider()
    intent = ParsedIntentSchema(action="purchase", query="cake", category="food", max_price_paise=1000, quantity=1)
    failed_product = ProductSchema(id=prod_id, merchant_id=uuid.uuid4(), name="Cake", description="", category="food", price_paise=100, inventory=0)
    
    with pytest.raises(GeminiProviderError) as exc_info:
        await provider.reason_recovery(intent, failed_product, "Out of stock", [])
        
    assert "incorrectly selected the failed product again" in str(exc_info.value)

@pytest.mark.asyncio
async def test_invalid_json_raises_error(mock_gemini):
    mock_gemini.return_value = "This is not JSON"
    provider = GeminiProvider()
    with pytest.raises(GeminiProviderError):
        await provider.parse_intent("hello")
