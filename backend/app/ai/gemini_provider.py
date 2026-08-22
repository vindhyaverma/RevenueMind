import os
import json
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from google import genai
from google.genai import types

from app.ai.provider import LLMProvider
from app.schemas.schemas import ParsedIntentSchema, ProductRankingSchema, ProductSchema
from app.core.logger import StructuredLogger

logger = StructuredLogger("gemini_provider")

class GeminiProviderError(Exception):
    pass

class GeminiProvider(LLMProvider):
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("gemini.api_key_missing", note="Running without real Gemini API Key. Will fail on real requests.")
            api_key = "dummy_key_for_testing"
            
        self.client = genai.Client(api_key=api_key)
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def _call_gemini(self, prompt: str, schema) -> str:
        try:
            logger.info("gemini.request_started", model=self.model_name)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.0
                )
            )
            logger.info("gemini.request_completed", model=self.model_name)
            return response.text
        except Exception as e:
            logger.error("gemini.request_failed", error=str(e))
            raise GeminiProviderError(f"Gemini API failure: {str(e)}") from e

    async def parse_intent(self, user_request: str) -> ParsedIntentSchema:
        prompt = f"""
        Analyze the following user shopping request and extract the key constraints.
        Convert any currency mentioned to paise (e.g., ₹1 = 100 paise).
        User request: "{user_request}"
        """
        response_text = await self._call_gemini(prompt, ParsedIntentSchema)
        try:
            data = json.loads(response_text)
            return ParsedIntentSchema(**data)
        except Exception as e:
            logger.error("gemini.parse_intent_failed", error=str(e), response=response_text)
            raise GeminiProviderError(f"Failed to parse schema from Gemini: {e}")

    async def rank_products(self, intent: ParsedIntentSchema, products: List[ProductSchema]) -> ProductRankingSchema:
        products_json = json.dumps([p.model_dump(mode="json") for p in products], indent=2)
        intent_json = json.dumps(intent.model_dump(mode="json"), indent=2)
        
        prompt = f"""
        Rank the provided candidate products based on the user's intent.
        
        User Intent:
        {intent_json}
        
        Candidate Products:
        {products_json}
        
        Select the best matching product, provide a reason, and list any alternatives.
        """
        response_text = await self._call_gemini(prompt, ProductRankingSchema)
        try:
            data = json.loads(response_text)
            return ProductRankingSchema(**data)
        except Exception as e:
            logger.error("gemini.rank_products_failed", error=str(e), response=response_text)
            raise GeminiProviderError(f"Failed to parse ranking schema from Gemini: {e}")

    async def reason_recovery(
        self, 
        intent: ParsedIntentSchema, 
        failed_product: ProductSchema,
        failure_reason: str,
        available_products: List[ProductSchema]
    ) -> ProductRankingSchema:
        
        products_json = json.dumps([p.model_dump(mode="json") for p in available_products], indent=2)
        intent_json = json.dumps(intent.model_dump(mode="json"), indent=2)
        failed_json = json.dumps(failed_product.model_dump(mode="json"), indent=2)
        
        prompt = f"""
        The user's previous selection failed deterministic checks and cannot be purchased.
        Select the next best alternative from the available products.
        
        User Intent:
        {intent_json}
        
        Failed Product:
        {failed_json}
        
        Failure Reason:
        {failure_reason}
        
        Candidate Products (Do NOT select the failed product again!):
        {products_json}
        """
        
        response_text = await self._call_gemini(prompt, ProductRankingSchema)
        try:
            data = json.loads(response_text)
            ranking = ProductRankingSchema(**data)
            
            # Simple failsafe: if Gemini stubbornly picked the failed product again, throw an error to trigger retry loop at higher level
            if ranking.selected_product_id == failed_product.id:
                logger.error("gemini.recovery_failed.selected_same_product", product_id=str(failed_product.id))
                raise GeminiProviderError("AI incorrectly selected the failed product again during recovery.")
                
            return ranking
        except Exception as e:
            logger.error("gemini.reason_recovery_failed", error=str(e), response=response_text)
            raise GeminiProviderError(f"Failed to parse recovery schema from Gemini: {e}")
