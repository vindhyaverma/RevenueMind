from abc import ABC, abstractmethod
from typing import List, Optional
from app.schemas.schemas import ParsedIntentSchema, ProductRankingSchema, ProductSchema

class LLMProvider(ABC):
    @abstractmethod
    async def parse_intent(self, user_request: str) -> ParsedIntentSchema:
        pass
        
    @abstractmethod
    async def rank_products(
        self, 
        intent: ParsedIntentSchema, 
        products: List[ProductSchema]
    ) -> ProductRankingSchema:
        pass
        
    @abstractmethod
    async def reason_recovery(
        self, 
        intent: ParsedIntentSchema, 
        failed_product: ProductSchema,
        failure_reason: str,
        available_products: List[ProductSchema]
    ) -> ProductRankingSchema:
        pass
