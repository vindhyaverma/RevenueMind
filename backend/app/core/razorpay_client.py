import os
import razorpay
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.logger import StructuredLogger

logger = StructuredLogger("razorpay_client")

class RazorpayClient:
    def __init__(self):
        self.key_id = os.getenv("RAZORPAY_KEY_ID")
        self.key_secret = os.getenv("RAZORPAY_KEY_SECRET")
        if self.key_id and self.key_secret:
            self.client = razorpay.Client(auth=(self.key_id, self.key_secret))
        else:
            self.client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True
    )
    def create_order(self, amount_paise: int, notes: dict) -> dict:
        if not self.client:
            logger.warning("razorpay.simulated_order_creation", notes=notes)
            import uuid
            return {"id": f"order_{uuid.uuid4().hex[:14]}", "amount": amount_paise, "status": "created"}
            
        return self.client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "notes": notes
        })
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True
    )
    def create_payment_link(self, amount_paise: int, description: str, notes: dict, expire_by: int) -> dict:
        if not self.client:
            logger.warning("razorpay.simulated_payment_link_creation", notes=notes)
            import uuid
            return {"id": f"plink_{uuid.uuid4().hex[:14]}", "short_url": "https://rzp.io/i/simulated"}
            
        return self.client.payment_link.create({
            "amount": amount_paise,
            "currency": "INR",
            "description": description,
            "notes": notes,
            "expire_by": expire_by
        })
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True
    )
    def fetch_order(self, order_id: str) -> dict:
        if not self.client:
            return {"id": order_id, "status": "paid", "amount": 0}
        return self.client.order.fetch(order_id)
