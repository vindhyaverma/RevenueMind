from pydantic import BaseModel
from typing import Optional
import uuid

class PreflightGuardResult(BaseModel):
    passed: bool
    reason: str = ""
    idempotency_key: Optional[str] = None

class PreflightGuard:
    @staticmethod
    def validate(
        product_id: uuid.UUID,
        session_id: uuid.UUID,
        mandate_id: uuid.UUID,
        quoted_price_paise: int,
        current_price_paise: int,
        inventory_count: int,
        has_existing_order: bool,
    ) -> PreflightGuardResult:
        
        # 1. Price Staleness Check
        if quoted_price_paise != current_price_paise:
            return PreflightGuardResult(
                passed=False, 
                reason=f"Price changed from {quoted_price_paise} to {current_price_paise}"
            )
            
        # 2. Inventory Check
        if inventory_count <= 0:
            return PreflightGuardResult(
                passed=False, 
                reason=f"Inventory unavailable for product {product_id}"
            )
            
        # 3. Idempotency Check (Race condition prevention on order creation)
        import hashlib
        key_str = f"{session_id}_{product_id}_{mandate_id}"
        idempotency_key = hashlib.sha256(key_str.encode()).hexdigest()
        
        if has_existing_order:
            return PreflightGuardResult(
                passed=False, 
                reason=f"Duplicate order detected for session {session_id}",
                idempotency_key=idempotency_key
            )
            
        return PreflightGuardResult(
            passed=True, 
            reason="All preflight checks passed",
            idempotency_key=idempotency_key
        )
