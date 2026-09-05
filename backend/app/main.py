"""
RevenueMind — Track 3: AI Revenue Recovery
FastAPI application entry point.
"""

import os
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.logger import StructuredLogger
from app.api.endpoints import router as api_router
from app.api.demo import router as demo_router
from app.api.recovery_endpoints import router as recovery_router
from app.db.session import engine, Base, DEMO_MODE, AsyncSessionLocal

logger = StructuredLogger("main")

MERCHANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


# ── 80-case synthetic seed dataset ───────────────────────────────────────────

def _build_cases():
    """
    Build 80 realistic revenue-risk cases.
    Amounts are in paise. Distribution designed to produce visually meaningful KPIs.
    
    Distribution:
    - TRANSIENT (30):       UPI timeout, network, bank unavailable
    - RECOVERABLE (20):     Checkout abandoned, link expired, session expired
    - NON_RETRYABLE (20):   Hard card decline, insufficient funds, repeated failure
    - HIGH_RISK (10):       Fraud suspected
    
    Expected after a full run (deterministic demo):
      At risk:     ~₹7.5L
      Recoverable: ~₹1.6L
      Recovered:   ~₹1.2L (75% of recoverable)
      Recovery Rate: ~75%
    """
    cases = []
    mid = MERCHANT_ID

    # ── TRANSIENT: UPI Timeout (20 cases) ─────────────────────────────────
    upi_data = [
        ("Aarav Sharma",   50000,  "UPI collect request timed out after 30s"),
        ("Diya Patel",     75000,  "UPI payment timeout — gateway did not respond"),
        ("Rohan Mehta",   100000,  "UPI collect expired before customer could authorize"),
        ("Ananya Singh",  125000,  "UPI timeout — bank response delayed"),
        ("Vikram Joshi",  150000,  "UPI collect request failed with T001 timeout"),
        ("Priya Gupta",   175000,  "Payment gateway timeout during UPI processing"),
        ("Arjun Nair",    200000,  "UPI session timed out — customer did not respond"),
        ("Kavya Reddy",    60000,  "UPI collect expired — 30s window passed"),
        ("Siddharth Kumar",90000,  "Bank UPI service returned timeout error"),
        ("Ishaan Verma",  120000,  "UPI payment abandoned at authorization step"),
        ("Shreya Agarwal",145000,  "UPI collect timeout — network congestion suspected"),
        ("Karan Malhotra",170000,  "UPI session expiry during customer authentication"),
        ("Pooja Iyer",    195000,  "UPI payment request timed out at NPCI gateway"),
        ("Rahul Bansal",   55000,  "UPI collect expired — customer auth step abandoned"),
        ("Tanvi Chopra",   85000,  "UPI timeout during bank 2FA verification"),
        ("Amit Trivedi",  115000,  "UPI session ended — transaction window expired"),
        ("Riya Saxena",   140000,  "UPI gateway timeout — no bank response received"),
        ("Dev Kapoor",    165000,  "UPI collect request failed with timeout error code"),
        ("Neha Dubey",    190000,  "UPI payment stalled — network interruption suspected"),
        ("Aryan Pillai",   65000,  "UPI collect timed out before bank confirmation"),
    ]
    for i, (name, amount, reason) in enumerate(upi_data, start=1):
        ref = str(uuid.uuid4())[:8]
        cases.append({
            "id": uuid.uuid4(),
            "case_ref": f"DEMO-{i:03d}",
            "merchant_id": mid,
            "customer_ref": f"CUST-{ref}",
            "customer_name": name,
            "amount_paise": amount,
            "failure_type": "upi_timeout",
            "failure_reason": reason,
            "recovery_attempts": 0,
            "customer_contacts": 0,
            "recovered_amount_paise": 0,
            "is_simulated_recovery": True,
            "escalated": False,
            "stopped_by_policy": False,
            "status": "pending",
            "customer_ltv_paise": 1033912,
            "customer_successful_payments": 0,
            "is_subscription": False,
        })

    # ── TRANSIENT: Network Timeout (7 cases) ──────────────────────────────
    net_data = [
        ("Vivek Menon",   80000, "Network connection lost during payment processing"),
        ("Aditi Rao",    110000, "HTTP gateway timeout — payment processor unreachable"),
        ("Suresh Nambiar",160000,"Network timeout during bank authorization"),
        ("Lakshmi Rajan", 220000,"Payment gateway connection timed out"),
        ("Harish Pandey",  45000,"Network error interrupted payment session"),
        ("Meena Krishnan",130000,"Connection reset during payment confirmation"),
        ("Rajesh Tiwari",  95000,"Network timeout — retryable infrastructure error"),
    ]
    for i, (name, amount, reason) in enumerate(net_data, start=21):
        ref = str(uuid.uuid4())[:8]
        cases.append({
            "id": uuid.uuid4(),
            "case_ref": f"DEMO-{i:03d}",
            "merchant_id": mid,
            "customer_ref": f"CUST-{ref}",
            "customer_name": name,
            "amount_paise": amount,
            "failure_type": "network_timeout",
            "failure_reason": reason,
            "recovery_attempts": 0,
            "customer_contacts": 0,
            "recovered_amount_paise": 0,
            "is_simulated_recovery": True,
            "escalated": False,
            "stopped_by_policy": False,
            "status": "pending",
            "customer_ltv_paise": 2154301,
            "customer_successful_payments": 7,
            "is_subscription": True,
        })

    # ── TRANSIENT: Bank Temporarily Unavailable (3 cases) ─────────────────
    bank_data = [
        ("Deepak Sharma",  200000, "HDFC bank gateway temporarily unavailable — retry in 15 min"),
        ("Sunita Patel",   300000, "SBI UPI service under maintenance — transient outage"),
        ("Anil Desai",     400000, "ICICI bank gateway timeout — known intermittent issue"),
    ]
    for i, (name, amount, reason) in enumerate(bank_data, start=28):
        ref = str(uuid.uuid4())[:8]
        cases.append({
            "id": uuid.uuid4(),
            "case_ref": f"DEMO-{i:03d}",
            "merchant_id": mid,
            "customer_ref": f"CUST-{ref}",
            "customer_name": name,
            "amount_paise": amount,
            "failure_type": "bank_unavailable",
            "failure_reason": reason,
            "recovery_attempts": 0,
            "customer_contacts": 0,
            "recovered_amount_paise": 0,
            "is_simulated_recovery": True,
            "escalated": False,
            "stopped_by_policy": False,
            "status": "pending",
            "customer_ltv_paise": 959791,
            "customer_successful_payments": 2,
            "is_subscription": False,
        })

    # ── RECOVERABLE: Checkout Abandoned (10 cases) ────────────────────────
    abandoned_data = [
        ("Preethi Suresh",  150000, "Customer reached checkout but did not complete payment"),
        ("Kartik Jain",     250000, "Payment initiated — customer exited before completing"),
        ("Ruchika Bose",    350000, "Cart checkout started — abandoned at payment step"),
        ("Manish Choudhary",500000, "Order created — payment window closed without action"),
        ("Divya Pillai",    750000, "Checkout session started but payment never submitted"),
        ("Suman Ghosh",    1000000, "Customer abandoned checkout page after 5 minutes"),
        ("Yogesh Pande",    180000, "Payment link opened but customer navigated away"),
        ("Anita Krishnamurthy",280000,"Order initiated — checkout abandoned at payment page"),
        ("Farhan Ansari",   420000, "Customer showed purchase intent — payment not completed"),
        ("Swati Acharya",   650000, "Add-to-cart and checkout started — not completed"),
    ]
    for i, (name, amount, reason) in enumerate(abandoned_data, start=31):
        ref = str(uuid.uuid4())[:8]
        cases.append({
            "id": uuid.uuid4(),
            "case_ref": f"DEMO-{i:03d}",
            "merchant_id": mid,
            "customer_ref": f"CUST-{ref}",
            "customer_name": name,
            "amount_paise": amount,
            "failure_type": "checkout_abandoned",
            "failure_reason": reason,
            "recovery_attempts": 0,
            "customer_contacts": 0,
            "recovered_amount_paise": 0,
            "is_simulated_recovery": True,
            "escalated": False,
            "stopped_by_policy": False,
            "status": "pending",
            "customer_ltv_paise": 366612,
            "customer_successful_payments": 0,
            "is_subscription": True,
        })

    # ── RECOVERABLE: Payment Link Expired (6 cases) ────────────────────────
    expired_data = [
        ("Nilesh Kumar",   300000, "Razorpay payment link expired after 15-minute window"),
        ("Preeti Agrawal", 450000, "Payment link sent to customer — expired before use"),
        ("Sameer Pawar",   600000, "Recovery payment link expired — customer did not use in time"),
        ("Tanisha Roy",    800000, "Payment link validity window elapsed"),
        ("Govind Sharma",  950000, "Payment link generated but customer used it after expiry"),
        ("Pallavi Nair",  1200000, "Payment session link expired — customer had link but could not pay"),
    ]
    # Starts at 31 + 10 (abandoned) = 41. We want to skip 42!
    for i, (name, amount, reason) in enumerate(expired_data, start=43): # start at 43 to leave 41, 42 free
        ref = str(uuid.uuid4())[:8]
        cases.append({
            "id": uuid.uuid4(),
            "case_ref": f"DEMO-{i:03d}",
            "merchant_id": mid,
            "customer_ref": f"CUST-{ref}",
            "customer_name": name,
            "amount_paise": amount,
            "failure_type": "payment_link_expired",
            "failure_reason": reason,
            "recovery_attempts": 0,
            "customer_contacts": 0,
            "recovered_amount_paise": 0,
            "is_simulated_recovery": True,
            "escalated": False,
            "stopped_by_policy": False,
            "status": "pending",
            "customer_ltv_paise": 2051701,
            "customer_successful_payments": 0,
            "is_subscription": False,
        })

    # ── RECOVERABLE: Session Expired (4 cases) ────────────────────────────
    session_data = [
        ("Mohini Das",      90000, "Payment session timed out — customer reconnected but session invalid"),
        ("Bharat Patel",   140000, "Session token expired during payment processing"),
        ("Urmila Singh",   220000, "Auth session timed out before payment could complete"),
        ("Deepa Shenoy",   320000, "Payment session expired — customer needs fresh session"),
    ]
    for i, (name, amount, reason) in enumerate(session_data, start=49):
        ref = str(uuid.uuid4())[:8]
        cases.append({
            "id": uuid.uuid4(),
            "case_ref": f"DEMO-{i:03d}",
            "merchant_id": mid,
            "customer_ref": f"CUST-{ref}",
            "customer_name": name,
            "amount_paise": amount,
            "failure_type": "session_expired",
            "failure_reason": reason,
            "recovery_attempts": 0,
            "customer_contacts": 0,
            "recovered_amount_paise": 0,
            "is_simulated_recovery": True,
            "escalated": False,
            "stopped_by_policy": False,
            "status": "pending",
            "customer_ltv_paise": 4671300,
            "customer_successful_payments": 13,
            "is_subscription": False,
        })

    # ── NON_RETRYABLE: Hard Card Decline (10 cases) ──────────────────────
    hard_decline_data = [
        ("Rashmi Jain",     500000, "Card permanently declined by issuing bank — do not retry"),
        ("Sudhir Kapoor",   800000, "Hard decline: card blocked by bank security policy"),
        ("Meera Nambiar",  1200000, "Card issuer hard-declined — account flagged"),
        ("Vivek Tharakan", 2000000, "Card declined: issuer returned decline code 05 (Do Not Honor)"),
        ("Anand Srinivasan",3000000,"Hard decline — bank reported card as restricted"),
        ("Sudha Pillai",    600000, "Card declined with error code 41 — card reported lost"),
        ("Ravi Karthik",    900000, "Issuing bank permanently declined — retry not permitted"),
        ("Jaya Krishnan",  1500000, "Card hard decline: insufficient authorization level"),
        ("Bhaskar Menon",  2500000, "Bank hard-declined transaction — account standing issue"),
        ("Geetha Nair",    3500000, "Card permanently blocked — bank hard decline code 62"),
    ]
    for i, (name, amount, reason) in enumerate(hard_decline_data, start=53):
        ref = str(uuid.uuid4())[:8]
        cases.append({
            "id": uuid.uuid4(),
            "case_ref": f"DEMO-{i:03d}",
            "merchant_id": mid,
            "customer_ref": f"CUST-{ref}",
            "customer_name": name,
            "amount_paise": amount,
            "failure_type": "hard_card_decline",
            "failure_reason": reason,
            "recovery_attempts": 0,
            "customer_contacts": 0,
            "recovered_amount_paise": 0,
            "is_simulated_recovery": True,
            "escalated": False,
            "stopped_by_policy": False,
            "status": "pending",
            "customer_ltv_paise": 2433632,
            "customer_successful_payments": 0,
            "is_subscription": False,
        })

    # ── DEMO-042: The deliberate policy-block demo ─────────────────────────
    # This case already has 2 prior recovery attempts.
    # AI recommends retry. Policy blocks it. This is the "second wow" moment.
    cases.append({
        "id": uuid.uuid4(),
        "case_ref": "DEMO-042",
        "merchant_id": mid,
        "customer_ref": "CUST-042demo",
        "customer_name": "Vikram Oberoi",
        "amount_paise": 599900,
        "failure_type": "hard_card_decline",
        "failure_reason": "Card hard-declined by issuing bank (error 05 — Do Not Honor). Two prior recovery attempts exhausted.",
        "recovery_attempts": 2,
        "customer_contacts": 1,
        "recovered_amount_paise": 0,
        "is_simulated_recovery": True,
        "escalated": False,
        "stopped_by_policy": False,
        "status": "pending",
            "customer_ltv_paise": 1439319,
            "customer_successful_payments": 13,
            "is_subscription": False,
    })

    # ── NON_RETRYABLE: Insufficient Funds (5 cases) ───────────────────────
    insuff_data = [
        ("Hemant Tiwari",   800000, "Bank confirmed insufficient balance — payment declined"),
        ("Mala Srivastava", 1200000,"Card declined: insufficient funds (bank code NSF)"),
        ("Prashant Bhatt",  2000000,"Account balance too low — bank returned NSF error"),
        ("Sunita Kumari",   3500000,"Insufficient funds in account — hard decline"),
        ("Vijay Khatri",    5000000,"Bank confirmed balance insufficient — auto-stop"),
    ]
    for i, (name, amount, reason) in enumerate(insuff_data, start=63):
        ref = str(uuid.uuid4())[:8]
        cases.append({
            "id": uuid.uuid4(),
            "case_ref": f"DEMO-{i:03d}",
            "merchant_id": mid,
            "customer_ref": f"CUST-{ref}",
            "customer_name": name,
            "amount_paise": amount,
            "failure_type": "insufficient_funds",
            "failure_reason": reason,
            "recovery_attempts": 0,
            "customer_contacts": 0,
            "recovered_amount_paise": 0,
            "is_simulated_recovery": True,
            "escalated": False,
            "stopped_by_policy": False,
            "status": "pending",
            "customer_ltv_paise": 1404256,
            "customer_successful_payments": 6,
            "is_subscription": False,
        })

    # ── NON_RETRYABLE: Repeated Failure (5 cases) ─────────────────────────
    repeated_data = [
        ("Nisha Agarwal",   350000, "Third payment attempt — previous 2 failed with different methods"),
        ("Suresh Pillai",   700000, "Repeated failures across multiple payment instruments"),
        ("Kamini Joshi",   1050000, "Customer attempted 3 times — systematic payment failure"),
        ("Bipin Mehta",    1400000, "Repeated failure pattern — human review required"),
        ("Shobha Menon",   1750000, "Multiple consecutive payment failures — escalation required"),
    ]
    for i, (name, amount, reason) in enumerate(repeated_data, start=68):
        ref = str(uuid.uuid4())[:8]
        cases.append({
            "id": uuid.uuid4(),
            "case_ref": f"DEMO-{i:03d}",
            "merchant_id": mid,
            "customer_ref": f"CUST-{ref}",
            "customer_name": name,
            "amount_paise": amount,
            "failure_type": "repeated_failure",
            "failure_reason": reason,
            "recovery_attempts": 3,
            "customer_contacts": 2,
            "recovered_amount_paise": 0,
            "is_simulated_recovery": True,
            "escalated": False,
            "stopped_by_policy": False,
            "status": "pending",
            "customer_ltv_paise": 2923559,
            "customer_successful_payments": 3,
            "is_subscription": True,
        })

    # ── HIGH_RISK: Fraud Suspected (10 cases) ─────────────────────────────
    fraud_data = [
        ("Unknown Buyer-A",  500000, "Velocity pattern flagged — multiple accounts same IP"),
        ("Unknown Buyer-B",  900000, "Card BIN mismatch with billing address — fraud signal"),
        ("Unknown Buyer-C", 1500000,"Device fingerprint matches known fraudulent actor"),
        ("Unknown Buyer-D", 2500000,"Unusual transaction pattern — risk engine flagged"),
        ("Unknown Buyer-E", 4000000,"Card used in multiple declined transactions — compromised"),
        ("Unknown Buyer-F",  700000, "Shipping address mismatch + velocity flag"),
        ("Unknown Buyer-G", 1200000,"Proxy/VPN detected + card BIN inconsistency"),
        ("Unknown Buyer-H", 2000000,"Risk score exceeded threshold — manual review required"),
        ("Unknown Buyer-I", 3500000,"Card pattern matches synthetic identity fraud"),
        ("Unknown Buyer-J", 6000000,"Transaction amount inconsistent with account history"),
    ]
    for i, (name, amount, reason) in enumerate(fraud_data, start=73):
        ref = str(uuid.uuid4())[:8]
        cases.append({
            "id": uuid.uuid4(),
            "case_ref": f"DEMO-{i:03d}",
            "merchant_id": mid,
            "customer_ref": f"CUST-{ref}",
            "customer_name": name,
            "amount_paise": amount,
            "failure_type": "fraud_suspected",
            "failure_reason": reason,
            "recovery_attempts": 0,
            "customer_contacts": 0,
            "recovered_amount_paise": 0,
            "is_simulated_recovery": True,
            "escalated": False,
            "stopped_by_policy": False,
            "status": "pending",
            "customer_ltv_paise": 911315,
            "customer_successful_payments": 11,
            "is_subscription": False,
        })

    return cases


async def seed_demo_data():
    """Seed the in-memory SQLite database with 80 revenue-risk cases."""
    from app.models.all_models import Product, Mandate
    from app.models.recovery_models import RevenueRiskCase
    import hashlib

    async with AsyncSessionLocal() as session:

        # ── Original products (keep for backward compatibility) ───────────────
        merchant_id = MERCHANT_ID
        products = [
            Product(
                id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                merchant_id=merchant_id,
                name="Butter Chicken (Full)",
                description="Classic North Indian butter chicken with naan",
                category="food",
                price_paise=45000,
                inventory=50,
            ),
            Product(
                id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                merchant_id=merchant_id,
                name="Paneer Tikka Masala",
                description="Chargrilled paneer in rich tomato-cream gravy",
                category="food",
                price_paise=40000,
                inventory=50,
            ),
            Product(
                id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
                merchant_id=merchant_id,
                name="Mango Lassi (Large)",
                description="Fresh alphonso mango blended lassi",
                category="food",
                price_paise=12900,
                inventory=100,
            ),
            Product(
                id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
                merchant_id=merchant_id,
                name="Dal Makhani + Rice",
                description="Slow-cooked black dal with steamed basmati rice",
                category="food",
                price_paise=29900,
                inventory=50,
            ),
        ]

        mandate = Mandate(
            id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            principal_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            allowed_categories=["food", "groceries"],
            merchant_whitelist=None,
            transaction_limit_paise=100000,
            daily_limit_paise=200000,
            auto_approve_limit_paise=100000,
            expires_at=None,
            hmac_signature=hashlib.sha256(b"demo_mandate").hexdigest(),
        )

        for p in products:
            session.add(p)
        session.add(mandate)

        # ── 80 revenue-risk cases ─────────────────────────────────────────────
        cases_data = _build_cases()
        for c in cases_data:
            case = RevenueRiskCase(
                id=c["id"],
                case_ref=c["case_ref"],
                merchant_id=c["merchant_id"],
                customer_ref=c["customer_ref"],
                customer_name=c["customer_name"],
                amount_paise=c["amount_paise"],
                failure_type=c["failure_type"],
                failure_reason=c["failure_reason"],
                recovery_attempts=c["recovery_attempts"],
                customer_contacts=c["customer_contacts"],
                recovered_amount_paise=c["recovered_amount_paise"],
                is_simulated_recovery=c["is_simulated_recovery"],
                escalated=c["escalated"],
                stopped_by_policy=c["stopped_by_policy"],
                status=c["status"],
                customer_ltv_paise=c.get("customer_ltv_paise", 0),
                customer_successful_payments=c.get("customer_successful_payments", 0),
                is_subscription=c.get("is_subscription", False),
            )
            session.add(case)

        await session.commit()

    total_cases = len(cases_data)
    total_at_risk = sum(c["amount_paise"] for c in cases_data)
    logger.info(
        "demo.recovery_data_seeded",
        cases=total_cases,
        total_at_risk_rupees=total_at_risk // 100,
        products=len(products),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app.startup", status="initializing", demo_mode=DEMO_MODE, product="RevenueMind")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if DEMO_MODE:
        await seed_demo_data()
        logger.info("app.startup.demo_mode", status="ready", product="RevenueMind")
    yield
    logger.info("app.shutdown", status="shutting_down")


app = FastAPI(title="RevenueMind API — Track 3: AI Revenue Recovery", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(demo_router)
app.include_router(recovery_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "demo_mode": DEMO_MODE, "product": "RevenueMind"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
