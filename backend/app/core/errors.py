class MerchantMindError(Exception):
    error_code = "INTERNAL_ERROR"
    http_status = 500
    
    def __init__(self, message: str, **context):
        super().__init__(message)
        self.message = message
        self.context = context

class MandateExpiredError(MerchantMindError):
    error_code = "MANDATE_EXPIRED"
    http_status = 403

class PreflightInventoryError(MerchantMindError):
    error_code = "PREFLIGHT_INVENTORY_UNAVAILABLE"
    http_status = 409

class PreflightPriceChangedError(MerchantMindError):
    error_code = "PREFLIGHT_PRICE_MISMATCH"
    http_status = 409
    
class DailyLimitExceededError(MerchantMindError):
    error_code = "DAILY_LIMIT_EXCEEDED"
    http_status = 402

class TransactionLimitExceededError(MerchantMindError):
    error_code = "TRANSACTION_LIMIT_EXCEEDED"
    http_status = 402

class IdempotencyConflictError(MerchantMindError):
    error_code = "IDEMPOTENCY_CONFLICT"
    http_status = 409

class AgentNotAuthorizedError(MerchantMindError):
    error_code = "AGENT_NOT_AUTHORIZED"
    http_status = 403
