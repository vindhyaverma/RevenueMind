# Razorpay Buildathon — Track 3 Demo Script

**Target Time:** 5 Minutes
**Objective:** Prove that RevenueMind is a fully bounded, revenue-generating autonomous agent.

## Preparation
1. Ensure `.env` has valid Razorpay keys.
2. Start the backend: `DEMO_MODE=true PYTHONPATH=. uvicorn app.main:app --reload --port 8000`
3. Start the frontend: `npm run dev`
4. Open `http://localhost:3000`

---

## 0:00–0:30 (The Setup)
**Action:** Open Control Tower view (homepage).
**Script:** 
> "This merchant has roughly ₹7.5 Lakh in revenue leaking out of the payment funnel from failed payments, abandoned checkouts, and timeouts. RevenueMind finds it, decides what can be recovered, and acts within strict recovery policies. Let's run the recovery agent."

## 0:30–1:30 (The Batch Execution)
**Action:** Click **"Run Recovery Agent"**.
**Visual:** The UI will poll the backend. The live log will stream in showing AI Diagnosis -> Policy check -> Action.
**Script:** 
> "The agent is evaluating 80 distinct failure cases. It diagnoses the root cause, but more importantly, it filters its recommendation through a deterministic policy engine before taking action."

## 1:30–2:30 (The Happy Path)
**Action:** Navigate to **Queue** or **Audit**, open `DEMO-031` (or another recoverable case).
**Visual:** Show the timeline.
**Script:** 
> "Here, a customer abandoned checkout. The AI recognized this as highly recoverable and recommended a payment link. The policy approved it, and the action was taken."

## 2:30–3:30 (The "Second Wow" — Policy Block)
**Action:** Search for `DEMO-042` in the Audit view.
**Visual:** The timeline shows the AI recommended a retry, but Policy shows an explicit `✕ BLOCKED`.
**Script:**
> "This is the most important part of the architecture. DEMO-042 is a hard card decline, and it already had two prior recovery attempts. The AI recommended a retry. But the AI cannot grant itself permission. Our deterministic policy engine caught the maximum retry limit and blocked the AI, escalating it for human review instead."

## 3:30–4:15 (The Razorpay Verification)
**Action:** Show `DEMO-001`. It should have generated a real Razorpay Payment Link (check the URL).
**Visual:** Copy the Razorpay link, open in new tab, and pay it using Razorpay test credentials.
**Script:**
> "For DEMO-001, the agent created a real Razorpay Payment Link. I'm going to pay it right now. [Pay]. The Razorpay `payment_link.paid` webhook hits our backend, verifies the HMAC signature, and securely marks the case as Razorpay Verified."

## 4:15–5:00 (The Impact)
**Action:** Open the **Impact** tab.
**Visual:** Show the split between "Simulated" and "Razorpay Verified" recovered revenue.
**Script:**
> "We didn't build an AI that tells merchants where revenue is being lost. We built an agent that finds the leakage, acts on the recoverable cases, stops when policy says no, and proves what money actually came back. Thank you."
