from pydantic import BaseModel, Field, model_validator
from typing import List, Optional
from datetime import datetime
import uuid

class SpendingMandateSchema(BaseModel):
    allowed_categories: List[str]
    transaction_limit_paise: int = Field(gt=0, le=50000000)
    daily_limit_paise: int = Field(gt=0, le=100000000)
    auto_approve_limit_paise: int = Field(gt=0)
    merchant_whitelist: Optional[List[uuid.UUID]] = None
    expires_at: Optional[datetime] = None
    
    @model_validator(mode='after')
    def validate_limits(self):
        if self.auto_approve_limit_paise > self.transaction_limit_paise:
            raise ValueError("auto_approve cannot exceed transaction_limit")
        if self.transaction_limit_paise > self.daily_limit_paise:
            raise ValueError("transaction_limit cannot exceed daily_limit")
        return self

class ProductSchema(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    name: str
    description: str
    category: str
    price_paise: int
    inventory: int

class ParsedIntentSchema(BaseModel):
    action: str = Field(description="The primary action the user wants to take, e.g., 'purchase', 'find'")
    query: str = Field(description="The main search query or product description")
    category: str = Field(description="The general category of the product, e.g., 'food', 'electronics'")
    max_price_paise: int = Field(description="The maximum price in paise (₹1 = 100 paise). Infer from request if possible, else use a high default like 10000000.")
    occasion: Optional[str] = Field(default=None, description="The occasion or context for the purchase, e.g., 'birthday', 'anniversary'")
    quantity: int = Field(default=1, description="The requested quantity")
    preferences: List[str] = Field(default_factory=list, description="Any specific preferences or constraints mentioned by the user")

class ProductAlternativeSchema(BaseModel):
    product_id: uuid.UUID
    reason: str

class ProductRankingSchema(BaseModel):
    selected_product_id: uuid.UUID
    reason: str
    alternatives: List[ProductAlternativeSchema]
