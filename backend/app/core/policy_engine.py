from typing import List
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import uuid

class MandateValidationResult(BaseModel):
    approved: bool
    reason: str = ""

class PolicyEngine:
    @staticmethod
    def validate(
        amount_paise: int,
        daily_spent_paise: int,
        mandate, # Using dict or object with properties
        product_category: str,
        merchant_id: uuid.UUID
    ) -> MandateValidationResult:
        
        # 1. Expiry Check
        if mandate.expires_at and mandate.expires_at < datetime.now(timezone.utc):
            return MandateValidationResult(approved=False, reason="Mandate expired")
            
        # 2. Transaction Limit
        if amount_paise > mandate.transaction_limit_paise:
            return MandateValidationResult(approved=False, reason=f"Amount {amount_paise} exceeds transaction limit {mandate.transaction_limit_paise}")
            
        # 3. Daily Limit
        if daily_spent_paise + amount_paise > mandate.daily_limit_paise:
            return MandateValidationResult(approved=False, reason="Daily limit exceeded")
            
        # 4. Category Check
        if product_category not in mandate.allowed_categories:
            return MandateValidationResult(approved=False, reason=f"Category {product_category} not allowed")
            
        # 5. Merchant Check
        if mandate.merchant_whitelist and merchant_id not in mandate.merchant_whitelist:
            return MandateValidationResult(approved=False, reason="Merchant not in whitelist")
            
        return MandateValidationResult(approved=True, reason="All checks passed")
