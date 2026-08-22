# MerchantMind — 5-Minute Demo Script

## Prerequisites

```bash
# Terminal 1: Backend
cd backend
source .venv/bin/activate
DEMO_MODE=true PYTHONPATH=. uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev
# Open http://localhost:3000
```

## Demo Flow (5 minutes)

### Minute 0–1: Context Setting

Open the app at `http://localhost:3000`.

**Say:**
> "MerchantMind is not a chatbot with a payment link. It's the financial safety layer that makes AI commerce possible. The core rule is: AI can choose what to buy, but deterministic code decides whether it's allowed to spend money."

### Minute 1–2: Show the Safety Rules (Policy Tab)

Click **Policy**.

Point out:
- Transaction limit: ₹1,000
- Daily limit: ₹2,000
- Auto-approve: ₹1,000
- Allowed categories: food, groceries
- These are hard rules. The AI cannot override them.

**Say:**
> "These are the spending mandates. Think of them like a corporate credit card policy. The AI agent operates within these boundaries, and deterministic code enforces every boundary before any Razorpay API call."

### Minute 2–3: Happy Path Purchase (Shop Tab)

Click **Shop**.

Type: `Order a birthday cake under ₹500`

Click **Agent Checkout**.

Watch the audit log update in real-time:
```
SESSION_STARTED
INTENT_PARSED → {action: "purchase", category: "food", max_price: 50000}
PRODUCTS_EVALUATED
PRODUCT_SELECTED → "Birthday Cake ₹450"
POLICY_PASSED → "All checks passed"
PREFLIGHT_PASSED → "All preflight checks passed"
AUTONOMOUS_ORDER_CREATED → order_abc123
```

**Say:**
> "Notice the amount ₹450 comes from the database, not from the AI. The AI suggested the product, but the PolicyEngine verified the amount is within limits, the PreflightGuard verified inventory exists, and only then did we call Razorpay."

### Minute 3–4: The Critical Demo — Last-Unit Race Condition

**Say:**
> "Now I'll show you what happens when the real world breaks the AI's assumption."

Click **[Demo] Trigger Last-Unit Race Condition**.

This sets the product's inventory to 0, simulating another buyer taking the last unit.

Now type the same intent: `Order a birthday cake under ₹500`

Click **Agent Checkout**.

Watch the audit log:
```
SESSION_STARTED
INTENT_PARSED
PRODUCT_SELECTED → "Birthday Cake ₹450"
PREFLIGHT_FAILED → "Inventory unavailable for product ..."
   ↓ AI RECOVERY
PRODUCT_SELECTED → "Chocolate Cake ₹400"
POLICY_PASSED
PREFLIGHT_PASSED
AUTONOMOUS_ORDER_CREATED → order_def456
```

**Say:**
> "The AI selected a product that was no longer available. The PreflightGuard blocked the payment — zero rupees charged. Then the AI reasoned about an alternative, but the alternative had to pass every single deterministic check again. The AI cannot turn a failed guard into a successful payment."

### Minute 4–5: Audit Trail (Audit Tab)

Click **Audit**.

Paste the session ID from the failed-and-recovered flow.

Show the complete timeline with color-coded events:
- 🔴 Red: `PREFLIGHT_FAILED` — inventory unavailable
- 🔵 Blue: `RECOVERY_REASONING` — AI selecting alternative
- 🟢 Green: `AUTONOMOUS_ORDER_CREATED` — successful purchase

**Say:**
> "Every AI decision and every deterministic check is in the audit trail. A compliance officer can see exactly what happened: the AI chose, the guard blocked, the AI recovered, and the guard re-validated before any money moved. This is what makes AI commerce auditable."

## Key Demo Points

| Question a Judge Might Ask | Where to Show It |
|---|---|
| "How do you prevent overspending?" | Policy tab → transaction limit |
| "What if the AI hallucinates a price?" | Shop tab → amount comes from DB |
| "What about race conditions?" | Demo button → preflight blocks |
| "Is this really using Razorpay?" | Transaction tab → order IDs |
| "Where's the audit trail?" | Audit tab → full event chain |
| "What if Gemini is down?" | Backend gracefully fails, no money moves |

## What Is Real vs Simulated

| Component | Real | Simulated in Demo |
|---|---|---|
| AI Intent Parsing | ✅ (Gemini) | Requires GEMINI_API_KEY |
| PolicyEngine | ✅ Always real | — |
| PreflightGuard | ✅ Always real | — |
| Idempotency | ✅ Always real | — |
| Audit Trail | ✅ Always real | — |
| Razorpay Orders | ✅ with test keys | Simulated if no keys |
| Database | SQLite in demo | PostgreSQL in production |
| Webhook Verification | ✅ HMAC-SHA256 | — |
