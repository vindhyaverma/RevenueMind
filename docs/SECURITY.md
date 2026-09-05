# Security & Safety Architecture

RevenueMind uses a **bounded execution pattern**. AI agents are inherently non-deterministic. To use them safely in fintech, the core philosophy is:

> **The AI recommends. Deterministic code decides.**

## Bounded Interventions
When the `RevenueRecoveryAgent` processes a case, the Gemini model outputs a structured JSON diagnosis (`FailureDiagnosis`). This includes a `recommended_action` (e.g., `payment_link`, `retry`, `escalate`, `stop`). 

This recommendation is passed into the `RecoveryPolicyEngine`, which is a pure Python, deterministic rule evaluator. 
- If the AI recommends a retry for a `hard_card_decline`, the Policy Engine overrides it to `escalate`.
- If the AI recommends a retry for a transient failure, but the user has already reached `max_recovery_attempts`, the Policy Engine overrides it to `stop`.

## Idempotency
To prevent double-billing or spamming users with payment links, all recovery actions go through an idempotency check.
The system generates a SHA-256 idempotency key from `case_id + run_id + action_type`. Before acting, it attempts to insert this key into the `recovery_actions` table (with a unique constraint).

## Financial Integrity
LLMs hallucinate numbers. A core invariant in RevenueMind is that the AI **never** computes or sets `recovered_amount_paise`. 
- The AI can only return a float `recoverability_score`.
- If an action succeeds, the backend assigns the original `amount_paise` from the database to `recovered_amount_paise`.
- Real Razorpay webhooks map the confirmed amount from the webhook payload directly to the case, completely bypassing the AI.

## Webhook Verification
All Razorpay webhooks (`payment.failed`, `payment_link.paid`) are processed through constant-time HMAC signature verification (`WebhookVerifier`) using `x-razorpay-signature` and the locally stored webhook secret.
