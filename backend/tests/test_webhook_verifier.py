from app.core.webhook_verifier import WebhookVerifier
import hmac
import hashlib

def test_valid_signature_passes():
    payload = b'{"event": "payment.captured"}'
    secret = "my_secret_key"
    
    # Generate valid signature
    valid_sig = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    assert WebhookVerifier.verify(payload, valid_sig, secret) is True

def test_invalid_signature_rejected():
    payload = b'{"event": "payment.captured"}'
    secret = "my_secret_key"
    invalid_sig = "a" * 64
    
    assert WebhookVerifier.verify(payload, invalid_sig, secret) is False

def test_missing_signature_rejected():
    payload = b'{"event": "payment.captured"}'
    secret = "my_secret_key"
    
    assert WebhookVerifier.verify(payload, "", secret) is False
    assert WebhookVerifier.verify(payload, None, secret) is False
