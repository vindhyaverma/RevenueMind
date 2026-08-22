import hmac
import hashlib

class WebhookVerifier:
    @staticmethod
    def verify(payload_body: bytes, razorpay_signature: str, secret: str) -> bool:
        """
        Verifies the Razorpay webhook signature.
        """
        if not razorpay_signature or not secret:
            return False
            
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload_body,
            hashlib.sha256
        ).hexdigest()
        
        # Use hmac.compare_digest to prevent timing attacks
        return hmac.compare_digest(expected_signature, razorpay_signature)
