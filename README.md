# RevenueMind 🚀

**Every failed payment is revenue at risk. RevenueMind brings it back.**

RevenueMind is an autonomous revenue recovery control tower for merchants, built for the **Razorpay AI Buildathon (Track 03: AI Revenue Recovery)**. 

It acts as an intelligent recovery agent that detects dropped or failed payments via live webhooks, diagnoses the likely cause, mathematically computes the highest-value intervention (Expected Value), and deterministically executes the recovery policy to get your money back.

### The Problem
Traditional retries are rigid. Sending every abandoned checkout a generic email is annoying, and retrying a hard-declined card is a waste of time (and increases processing fees). Merchants are leaving millions on the table because they lack context-aware, targeted recovery pipelines.

### The RevenueMind Solution
RevenueMind introduces the **Next Best Action (NBA) Expected Value Matrix**:
`Expected Value = (Recovery Probability × Amount at Risk) - Intervention Cost`

Instead of blind retries, the AI dynamically evaluates intervention candidates (e.g., Simulated Voice Call vs. WhatsApp vs. Payment Link) and computes their Expected Value. The system is protected by a strict deterministic `RecoveryPolicyEngine` to enforce business rules—ensuring the AI can never override retry limits, customer contact limits, or fraud protections.

## Key Features

- **Next Best Action Matrix:** The core mathematical engine that evaluates probability vs. cost.
- **Deep Customer Snapshot:** Analyzes LTV, successful payment history, and subscription status to inform the AI's aggressiveness.
- **Deterministic Policy Engine:** An impenetrable wall between the AI and execution. The AI recommends (e.g., "Voice Call"), but the code decides if it's allowed (e.g., "BLOCKED: Max attempts reached").
- **Real Razorpay Integration:** Dynamically generates **real** Razorpay Payment Links (`plink_xxx`) and listens to live Razorpay Webhooks (`payment.failed`, `payment_link.paid`) for a 100% autonomous, closed-loop system.
- **Deep Dive UI:** A bespoke, dark-themed Next.js dashboard ("Control Tower") visualizing the AI's causal diagnosis and expected value decay curves.

---

## 🚀 The Ultimate Live Demo

You can run this project in two modes: **Demo Mode** (automatically seeds 81 simulated cases) or **Production Mode** (listens to live Razorpay webhooks).

### Option A: The "One-Click" Demo Mode
This starts the backend with an in-memory database and 81 synthetic cases to showcase the UI and Batch Recovery instantly.

**1. Start Backend**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
DEMO_MODE=true PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8000
```

**2. Start Frontend**
```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

Navigate to `http://localhost:3000`. Click **LAUNCH RECOVERY** to watch the AI process all 81 cases in the background! Click any case to see the Deep Dive Matrix.

### Option B: The Live Production Integration (Recommended for Judges)
*Want to see real magic?* Hook RevenueMind directly up to your Razorpay Test Account!

1. Create a `.env` in the `backend/` directory with your Razorpay Test Keys:
```
RAZORPAY_KEY_ID="rzp_test_xxxx"
RAZORPAY_KEY_SECRET="yyyyyy"
RAZORPAY_WEBHOOK_SECRET="zzzzzz"
```
2. Start the backend *without* DEMO_MODE:
```bash
PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8000
```
3. Expose your backend via Ngrok:
```bash
ngrok http 8000
```
4. In your Razorpay Dashboard, add a webhook to `https://<your-ngrok>.app/api/v1/webhooks/razorpay` subscribing to `payment.failed` and `payment_link.paid`.
5. **The Test:** Go fail a test payment on Razorpay. Watch it instantly appear in the RevenueMind Queue. Click "Run Recovery". The AI will hit the Razorpay API and generate a *real* payment link. Pay the link, and watch the case autonomously move to "Recovered"!

## Architecture

- **Frontend:** Next.js 16 (App Router), React, Tailwind CSS (Razorpay Dark Theme), Lucide Icons.
- **Backend:** FastAPI, Python 3.9, SQLAlchemy (Async), Pydantic v2.
- **AI Core:** Gemini 1.5 Flash (via `google-genai` SDK), Structural Parsing, Causal Diagnosis.
- **Payments:** Official `razorpay` Python SDK.

Built with 🖤 for the Razorpay AI Buildathon.
