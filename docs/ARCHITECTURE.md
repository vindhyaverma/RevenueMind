# Architecture

RevenueMind is a hybrid pipeline combining non-deterministic AI diagnosis with deterministic control flow.

## The Core Loop

1. **DETECT**: The system detects a failed payment (seeded in `DEMO_MODE`, or via `payment.failed` webhook).
2. **DIAGNOSE**: AI evaluates the failure reason and outputs a `FailureClass` (Transient, Recoverable, Non-Retryable, High-Risk).
3. **RECOMMEND**: AI recommends an action based on context.
4. **POLICY CHECK**: The deterministic `RecoveryPolicyEngine` evaluates the recommendation against hard rules (fraud stops immediately, max attempts enforced, etc.).
5. **EXECUTE**: If approved, the agent executes the action (generating a Razorpay payment link or simulating success).
6. **VERIFY**: The system awaits a `payment_link.paid` webhook to upgrade the case to `Razorpay Verified`.

## Data Model

- `RevenueRiskCase`: The central entity. Tracks the failure, the AI diagnosis, the policy result, and the status.
- `RecoveryRun`: Tracks batch job executions to group metrics.
- `RecoveryAction`: The immutable idempotency log for all actions.
- `AuditEvent`: The structured, chronological timeline of every event for a specific case, mapped via `session_id`.

## Hybrid Demo Architecture

To prevent a 5-minute demo from requiring 80 synchronous LLM calls (which would take ~1.5 minutes and risk API timeouts), we use a rule-based AI simulator for the bulk batch processing. 
The system processes 80 cases in under 5 seconds.
Real LLM calls and real Razorpay API calls are reserved for specific deep-dive cases (like `DEMO-001`) to prove the integration without sacrificing demo reliability.
