# MerchantMind — The AI-Native Commerce Layer for Razorpay Merchants

> **AI recommends. Deterministic code decides.**

An AI buyer can now shop a Razorpay merchant's storefront and check out on its own — MerchantMind is the layer that makes that safe. It picks products, checks a strict spending policy, and completes a payment end to end, with every step logged and every irreversible action gated behind a deterministic check.

By exposing a merchant's catalog in a machine-readable format with built-in financial guardrails, MerchantMind opens an entirely new revenue channel: autonomous AI shoppers.

## What This Is

MerchantMind is **not** a chatbot with a payment link. It is the safety and transaction layer that makes AI-powered commerce possible **without giving the AI unrestricted control over money**.

### What AI Does
- Natural-language intent understanding ("Order a birthday cake under ₹500")
- Semantic product matching and ranking
- Recovery reasoning when a product becomes unavailable

### What AI Cannot Do
- Control money
- Bypass the PolicyEngine
- Determine the payment amount (comes from DB, never from AI)
- Authorize transactions
- Modify inventory truth
- Bypass PreflightGuard
- Bypass idempotency checks
- Generate webhook signatures
- Call Razorpay APIs directly

## Architecture

```
User/Agent Intent
       ↓
AI Intent Parser (Gemini)
       ↓
Catalog Search (DB)
       ↓
AI Product Ranking (Gemini)
       ↓
PolicyEngine (DETERMINISTIC)
       ↓
PreflightGuard (DETERMINISTIC)
       ↓
Authorization Gate (DETERMINISTIC)
       ↓
Razorpay Order/Payment
       ↓
Webhook Verification (HMAC-SHA256)
       ↓
Audit Trail
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.
See [SECURITY.md](SECURITY.md) for the trust boundary model.
See [DEMO.md](DEMO.md) for the 5-minute demo script.

## Quick Start

### Prerequisites
- Python 3.9+
- Node.js 18+
- Razorpay Test Account (for live payments)
- Gemini API Key (for AI features)

### Backend

```bash
cd backend
cp ../.env.example ../.env
# Edit .env with your API keys

source .venv/bin/activate
# or: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Run in demo mode (no external DB or API keys required):
DEMO_MODE=true PYTHONPATH=. uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

### Run Tests

```bash
cd backend
PYTHONPATH=. .venv/bin/pytest tests/ -v
```

## Demo Mode

Set `DEMO_MODE=true` to run with:
- In-memory SQLite database (no PostgreSQL required)
- Pre-seeded products, mandates, and inventory
- Simulated Razorpay order/payment creation (deterministic, no real charges)
- Real AI provider (requires `GEMINI_API_KEY`) or mock fallback
- All deterministic safety checks remain fully active

**Demo mode never fakes payment success.** The deterministic guards, policy engine, preflight checks, and audit trail all execute identically to production mode.

## Project Structure

```
merchantmind/
├── backend/
│   ├── app/
│   │   ├── ai/               # AI Provider layer (Gemini)
│   │   │   ├── provider.py   # Abstract interface
│   │   │   └── gemini_provider.py
│   │   ├── api/              # REST endpoints + Orchestrator
│   │   │   ├── agent.py      # AgentOrchestrator
│   │   │   ├── endpoints.py  # FastAPI routes
│   │   │   └── demo.py       # Demo-specific endpoints
│   │   ├── core/             # Deterministic financial core
│   │   │   ├── policy_engine.py
│   │   │   ├── preflight_guard.py
│   │   │   ├── webhook_verifier.py
│   │   │   ├── razorpay_client.py
│   │   │   ├── errors.py
│   │   │   └── logger.py
│   │   ├── db/               # Database layer
│   │   │   ├── session.py
│   │   │   └── repository.py
│   │   ├── mcp/              # MCP Storefront
│   │   │   └── storefront.py
│   │   ├── models/           # SQLAlchemy ORM
│   │   │   └── all_models.py
│   │   ├── schemas/          # Pydantic schemas
│   │   │   └── schemas.py
│   │   └── main.py           # FastAPI entrypoint
│   └── tests/
├── frontend/                 # Next.js UI
└── docs/
```

## Prototype Limitations

This is a hackathon MVP. Known limitations:

1. **Test-mode payments only.** Razorpay keys must be test keys (`rzp_test_*`). No real money is processed.
2. **Single-merchant MVP.** The current implementation supports one merchant storefront.
3. **In-memory demo database.** Demo mode uses SQLite in-memory. Production would use PostgreSQL with proper migrations.
4. **Simulated mandate identity.** In production, mandates would be cryptographically signed and verified against a principal (user) identity. The MVP uses UUID-based lookup.
5. **Concurrency.** The `PreflightGuard` inventory check is application-level. Production would use `SELECT ... FOR UPDATE` row-level locking or atomic `UPDATE ... WHERE inventory > 0 RETURNING *` for true ACID guarantees.
6. **Single AI provider.** Currently supports Gemini only. The `LLMProvider` abstract base class allows swapping providers.
7. **No persistent sessions.** Shopping sessions are ephemeral per request.

## Environment Variables

See [.env.example](.env.example) for all required variables.

## License

Built for the Razorpay AI Builder Internship 2026.
