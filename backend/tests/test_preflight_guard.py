import uuid
from app.core.preflight_guard import PreflightGuard

def test_guard_passes_all_checks():
    prod_id = uuid.uuid4()
    sess_id = uuid.uuid4()
    mand_id = uuid.uuid4()
    
    res = PreflightGuard.validate(
        product_id=prod_id,
        session_id=sess_id,
        mandate_id=mand_id,
        quoted_price_paise=500,
        current_price_paise=500,
        inventory_count=1,
        has_existing_order=False
    )
    
    assert res.passed is True
    assert res.idempotency_key is not None
    assert len(res.idempotency_key) == 64 # SHA256 hash length

def test_guard_blocks_stale_price():
    res = PreflightGuard.validate(
        product_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        mandate_id=uuid.uuid4(),
        quoted_price_paise=500,
        current_price_paise=450,
        inventory_count=10,
        has_existing_order=False
    )
    assert res.passed is False
    assert "Price changed" in res.reason

def test_guard_blocks_zero_inventory():
    res = PreflightGuard.validate(
        product_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        mandate_id=uuid.uuid4(),
        quoted_price_paise=500,
        current_price_paise=500,
        inventory_count=0,
        has_existing_order=False
    )
    assert res.passed is False
    assert "Inventory unavailable" in res.reason

def test_guard_blocks_duplicate_order():
    res = PreflightGuard.validate(
        product_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        mandate_id=uuid.uuid4(),
        quoted_price_paise=500,
        current_price_paise=500,
        inventory_count=1,
        has_existing_order=True
    )
    assert res.passed is False
    assert "Duplicate order" in res.reason
