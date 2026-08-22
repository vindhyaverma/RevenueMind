import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import List, Optional

from hypothesis import given, strategies as st
from app.core.policy_engine import PolicyEngine

@dataclass
class MockMandate:
    transaction_limit_paise: int
    daily_limit_paise: int
    auto_approve_limit_paise: int
    allowed_categories: List[str]
    merchant_whitelist: Optional[List[uuid.UUID]] = None
    expires_at: Optional[datetime] = None

def test_transaction_within_limit():
    mandate = MockMandate(1000, 5000, 1000, ["food"])
    res = PolicyEngine.validate(500, 0, mandate, "food", uuid.uuid4())
    assert res.approved is True

def test_transaction_exceeds_limit():
    mandate = MockMandate(1000, 5000, 1000, ["food"])
    res = PolicyEngine.validate(1500, 0, mandate, "food", uuid.uuid4())
    assert res.approved is False
    assert "exceeds transaction limit" in res.reason

def test_daily_limit_exceeded():
    mandate = MockMandate(1000, 5000, 1000, ["food"])
    res = PolicyEngine.validate(1000, 4500, mandate, "food", uuid.uuid4())
    assert res.approved is False
    assert "Daily limit" in res.reason

def test_category_not_allowed():
    mandate = MockMandate(1000, 5000, 1000, ["food"])
    res = PolicyEngine.validate(500, 0, mandate, "electronics", uuid.uuid4())
    assert res.approved is False
    assert "not allowed" in res.reason

def test_merchant_not_allowed():
    allowed_merchant = uuid.uuid4()
    other_merchant = uuid.uuid4()
    mandate = MockMandate(1000, 5000, 1000, ["food"], merchant_whitelist=[allowed_merchant])
    res = PolicyEngine.validate(500, 0, mandate, "food", other_merchant)
    assert res.approved is False
    assert "whitelist" in res.reason

def test_expired_mandate():
    mandate = MockMandate(1000, 5000, 1000, ["food"], expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    res = PolicyEngine.validate(500, 0, mandate, "food", uuid.uuid4())
    assert res.approved is False
    assert "expired" in res.reason

@given(
    amount=st.integers(min_value=1, max_value=1_000_000),
    limit=st.integers(min_value=1, max_value=1_000_000),
    daily_spent=st.integers(min_value=0, max_value=1_000_000),
    daily_limit=st.integers(min_value=1, max_value=1_000_000)
)
def test_policy_engine_never_allows_spend_above_limits(amount, limit, daily_spent, daily_limit):
    mandate = MockMandate(limit, daily_limit, limit, ["food"])
    res = PolicyEngine.validate(amount, daily_spent, mandate, "food", uuid.uuid4())
    if amount > limit or (daily_spent + amount) > daily_limit:
        assert res.approved is False
    else:
        assert res.approved is True
