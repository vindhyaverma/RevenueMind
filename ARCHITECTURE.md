# Architecture

## The AI vs. Deterministic Boundary

The core differentiator of MerchantMind is the strict separation between AI reasoning and deterministic financial execution.

### AI (Probabilistic)
AI is used *only* where natural language or semantic reasoning is required:
- **Intent Parsing:** "I need a birthday gift under ₹500" -> structured JSON constraints
- **Product Semantic Ranking:** Matching "birthday gift" to "Red Velvet Cake"
- **Recovery Reasoning:** Deciding the next best alternative when the first choice fails

### Deterministic (Rule-based)
Financial decisions are *never* left to the LLM.
- **Spending Limit Check:** Arithmetic check (`amount <= limit`)
- **Daily Spend Accumulation:** SQL query (`SUM(amount) WHERE date = today`)
- **Category Check:** Set membership
- **Inventory Check:** SQL query (`inventory > 0`)
- **Stale Price Check:** `current_db_price == quoted_price`
- **Idempotency:** SHA256 hash of (session_id + product_id + mandate_id)
- **Webhook Verification:** HMAC-SHA256 signature check
- **Authorization Gate:** Amount threshold comparison for human-in-the-loop

## Request Flow
1. User provides Natural Language Intent
2. **Intent Parser (AI)** extracts structured constraints
3. **Product Ranker (AI)** selects the best product
4. **Mandate Validator (Deterministic)** checks limits
5. **Pre-Payment Guard (Deterministic)** checks inventory, price, idempotency
6. **Authorization Gate (Deterministic)** decides if human approval is needed
7. Razorpay Order Created
8. Payment Executed
9. Webhook Verified
10. Audit Record Committed

If any deterministic guard fails, the process is blocked *before* any money moves, and the AI is asked to reason about an alternative.
