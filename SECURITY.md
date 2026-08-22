# MerchantMind Security Model

## Core Principle

> **AI recommends. Deterministic code decides.**

No AI output is ever trusted for financial decisions. The AI provides natural-language understanding, product ranking, and recovery reasoning. All financial authority flows through deterministic, auditable code.

## Trust Boundaries

```
┌────────────────────────────────────────────────────────┐
│                    UNTRUSTED ZONE                       │
│                                                        │
│  User Input    AI Output    MCP Requests    Frontend   │
│                                                        │
└──────────────────────┬─────────────────────────────────┘
                       │ Validated by Pydantic schemas
                       ▼
┌────────────────────────────────────────────────────────┐
│                ORCHESTRATOR BOUNDARY                    │
│                                                        │
│  AgentOrchestrator validates all inputs, routes         │
│  through deterministic checks, never trusts AI         │
│  for amounts, inventory, or authorization.             │
│                                                        │
└──────────────────────┬─────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────┐
│              DETERMINISTIC SAFETY LAYER                 │
│                                                        │
│  PolicyEngine      - spending limits, categories       │
│  PreflightGuard    - inventory, price, idempotency     │
│  AuthorizationGate - auto-approve vs human approval    │
│  WebhookVerifier   - HMAC-SHA256 signature validation  │
│                                                        │
└──────────────────────┬─────────────────────────────────┘
                       │ Only after ALL checks pass
                       ▼
┌────────────────────────────────────────────────────────┐
│                 RAZORPAY (EXTERNAL)                     │
│                                                        │
│  Order creation and payment link generation only       │
│  occur after deterministic validation succeeds.        │
│                                                        │
└────────────────────────────────────────────────────────┘
```

## Threat Model

### T1: AI Hallucinated Price
**Threat:** AI reports a product costs ₹10 when it actually costs ₹1,000.
**Mitigation:** The orchestrator always fetches `price_paise` from the database (line 34 of agent.py), never from AI output. The payment amount on line 93 is `product.price_paise` from the DB, not from any AI-generated value.

### T2: AI Category Bypass
**Threat:** AI claims a prohibited item is in an allowed category.
**Mitigation:** Product category comes from the database record, not from AI output. PolicyEngine.validate() checks `product.category` from DB against `mandate.allowed_categories`.

### T3: AI Spending Limit Override
**Threat:** AI attempts to purchase above the mandate's transaction limit.
**Mitigation:** PolicyEngine checks `product.price_paise` (from DB) against `mandate.transaction_limit_paise`. This is a hard deterministic check with no AI input.

### T4: Duplicate Payment
**Threat:** Two identical requests create two Razorpay orders.
**Mitigation:** PreflightGuard generates SHA-256 idempotency keys from `(session_id, product_id, mandate_id)`. The `agent_orders.idempotency_key` column has a `UNIQUE` constraint. Application-level `has_order` check precedes DB insert.

### T5: Inventory Race Condition
**Threat:** Two requests both see inventory=1 and both try to purchase.
**Mitigation:** Application-level inventory check in PreflightGuard. Production hardening would add `SELECT ... FOR UPDATE` row-level locking. The idempotency key provides a secondary defense.

### T6: Webhook Forgery
**Threat:** Attacker sends a fake webhook to mark a payment as captured.
**Mitigation:** `WebhookVerifier` uses `hmac.compare_digest()` with the Razorpay webhook secret for constant-time comparison, preventing both forgery and timing attacks.

### T7: MCP Bypass
**Threat:** An MCP client attempts to create a payment without going through the orchestrator.
**Mitigation:** MCP tools route all purchase operations through `AgentOrchestrator.process_intent()`, which enforces PolicyEngine + PreflightGuard. MCP has no direct access to `RazorpayClient`.

### T8: Frontend Financial Manipulation
**Threat:** The frontend sends a modified payment amount.
**Mitigation:** The frontend is display-only. It sends `user_intent` (natural language) and `mandate_id` to the backend. The backend independently determines the amount from the database. The frontend never sends a payment amount.

### T9: Secret Exposure
**Threat:** API keys or secrets are logged, committed to git, or exposed in responses.
**Mitigation:**
- `.env` is in `.gitignore`
- Logger never logs API keys, secrets, or full payment details
- Error responses use structured error codes, not raw exception details
- Razorpay client reads keys from environment variables only

## Credential Handling

| Credential | Source | Storage | Exposure |
|---|---|---|---|
| GEMINI_API_KEY | Environment | .env (not committed) | Never logged |
| RAZORPAY_KEY_ID | Environment | .env (not committed) | Never logged |
| RAZORPAY_KEY_SECRET | Environment | .env (not committed) | Never logged |
| RAZORPAY_WEBHOOK_SECRET | Environment | .env (not committed) | Never logged |

## Audit Trail

Every financial decision is recorded in the `audit_events` table with:
- `session_id`: Links all events in a shopping session
- `event_type`: Categorized event (e.g., `policy_blocked`, `preflight_failed`, `autonomous_order_created`)
- `payload`: Structured JSON with decision context
- `timestamp`: Server-generated, immutable

The audit trail is append-only. There is no API to delete or modify audit events.
