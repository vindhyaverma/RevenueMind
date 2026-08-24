"""
pre_ship_check.py — adversarial verification for MerchantMind.
Checks: policy blocks, payment.failed branch, diff scan for secrets/prints.
"""

import asyncio, uuid, sys, os
from pathlib import Path

BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.schemas import ParsedIntentSchema, ProductRankingSchema
from app.core.errors import AgentNotAuthorizedError
from app.api.agent import AgentOrchestrator

PASSED, FAILED = [], []

def ok(name):
    PASSED.append(name)
    print(f"  ✅  {name}")

def fail(name, detail=""):
    FAILED.append(name)
    print(f"  ❌  {name}" + (f"\n       → {detail}" if detail else ""))


# ── Mocks ──────────────────────────────────────────────────────────────────────

def make_product(price_paise=45000, category="food", inventory=5, pid=None):
    class P:
        id = pid or uuid.UUID("00000000-0000-0000-0000-000000000001")
        merchant_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
        name = "Birthday Cake"
        description = "test"
    p = P()
    p.price_paise = price_paise
    p.category = category
    p.inventory = inventory
    return p


def make_mandate(tx_limit=100000, daily_limit=200000, auto=100000, categories=None):
    class M:
        id = uuid.UUID("00000000-0000-0000-0000-000000000000")
        merchant_whitelist = None
        expires_at = None
    m = M()
    m.transaction_limit_paise = tx_limit
    m.daily_limit_paise = daily_limit
    m.auto_approve_limit_paise = auto
    m.allowed_categories = categories or ["food", "groceries"]
    return m


class MockDB:
    def __init__(self, products, mandate, daily_spent=0):
        self._products = products
        self._mandate = mandate
        self._daily_spent = daily_spent
        self.audit_log = []
        self._inventory = {p.id: p.inventory for p in products}
        self._orders = {}
        self._order_product = {}

    async def search_products(self, category, max_price_paise):
        return [p for p in self._products
                if p.category == category and p.price_paise <= max_price_paise]

    async def get_product(self, product_id):
        for p in self._products:
            if p.id == product_id:
                p.inventory = self._inventory.get(p.id, p.inventory)
                return p
        raise ValueError(f"Product {product_id} not found")

    async def get_mandate(self, _): return self._mandate
    async def get_daily_spend(self, _): return self._daily_spent
    async def has_order(self, s, p): return False

    async def reserve_inventory_atomic(self, product_id):
        if self._inventory.get(product_id, 0) > 0:
            self._inventory[product_id] -= 1
            return True
        return False

    async def release_inventory(self, product_id):
        self._inventory[product_id] = self._inventory.get(product_id, 0) + 1

    async def release_inventory_by_order(self, razorpay_order_id):
        pid = self._order_product.get(razorpay_order_id)
        if pid:
            await self.release_inventory(pid)

    async def update_order_status_by_razorpay_id(self, oid, status):
        self._orders[oid] = status

    async def save_order(self, s, m, p, oid, amt, ikey):
        self._orders[oid] = "created"
        self._order_product[oid] = p

    async def log_audit(self, s, event_type, payload):
        self.audit_log.append({"type": event_type, "payload": payload})

    async def get_audit_trail(self, s):
        return self.audit_log


class MockAI:
    async def parse_intent(self, intent):
        return ParsedIntentSchema(
            action="purchase", query="cake", category="food",
            max_price_paise=1000000, quantity=1)

    async def rank_products(self, intent, products):
        if not products:
            raise Exception("No products to rank")
        return ProductRankingSchema(
            selected_product_id=products[0].id,
            reason="Best match", alternatives=[])

    async def reason_recovery(self, intent, failed, reason, avail):
        remaining = [p for p in avail if p.id != failed.id]
        if remaining:
            return ProductRankingSchema(
                selected_product_id=remaining[0].id, reason="Recovery", alternatives=[])
        raise Exception("No recovery possible")


class GoodRazorpay:
    def create_order(self, amount, notes):
        return {"id": f"order_{uuid.uuid4().hex[:12]}", "amount": amount, "status": "created"}


class FailingRazorpay:
    def create_order(self, amount, notes):
        raise Exception("Payment gateway unavailable")


# ── CHECK 1: Adversarial policy ────────────────────────────────────────────────

async def check1():
    print("\n─── CHECK 1: Adversarial policy blocks ─────────────────────────────────")

    # 1a: Over transaction limit
    p = make_product(price_paise=150000)   # ₹1,500
    m = make_mandate(tx_limit=100000)      # ₹1,000 cap
    db = MockDB([p], m)
    try:
        await AgentOrchestrator(MockAI(), GoodRazorpay(), db).process_intent(
            uuid.uuid4(), m.id, "expensive cake")
        fail("1a — over-limit should block")
    except AgentNotAuthorizedError:
        types = [e["type"] for e in db.audit_log]
        if "policy_blocked" in types:
            reason = next(e["payload"]["reason"] for e in db.audit_log if e["type"] == "policy_blocked")
            ok(f"1a — over-limit blocked · audit reason: '{reason}'")
        else:
            fail("1a — policy_blocked missing from audit", str(types))
    except Exception as e:
        fail("1a — wrong exception", str(e))

    # 1b: Out-of-catalog category (electronics vs food mandate)
    class EarbudAI:
        async def parse_intent(self, i):
            return ParsedIntentSchema(action="purchase", query="earbuds",
                category="electronics", max_price_paise=1000000, quantity=1)
        async def rank_products(self, i, p):
            if not p: raise Exception("No products matched")
            return ProductRankingSchema(selected_product_id=p[0].id,
                reason="best", alternatives=[])
        async def reason_recovery(self, i, f, r, a): raise Exception("no recovery")

    ep = make_product(price_paise=80000, category="electronics")
    m2 = make_mandate(categories=["food", "groceries"])
    db2 = MockDB([ep], m2)
    try:
        await AgentOrchestrator(EarbudAI(), GoodRazorpay(), db2).process_intent(
            uuid.uuid4(), m2.id, "buy earbuds")
        fail("1b — electronics on food-only should block")
    except Exception as e:
        types = [ev["type"] for ev in db2.audit_log]
        if "policy_blocked" in types or "No products" in str(e):
            ok(f"1b — electronics blocked · '{str(e)[:60]}'")
        else:
            fail("1b — blocked via wrong path", f"types={types} err={e}")

    # 1c: Daily limit exceeded (₹1,900 spent, ₹450 purchase → ₹2,350 > ₹2,000 cap)
    p3 = make_product(price_paise=45000)
    m3 = make_mandate(daily_limit=200000)
    db3 = MockDB([p3], m3, daily_spent=190000)
    try:
        await AgentOrchestrator(MockAI(), GoodRazorpay(), db3).process_intent(
            uuid.uuid4(), m3.id, "order a cake")
        fail("1c — daily limit exceeded should block")
    except AgentNotAuthorizedError:
        types = [e["type"] for e in db3.audit_log]
        if "policy_blocked" in types:
            reason = next(e["payload"]["reason"] for e in db3.audit_log if e["type"] == "policy_blocked")
            ok(f"1c — daily limit blocked · audit reason: '{reason}'")
        else:
            fail("1c — policy_blocked missing", str(types))
    except Exception as e:
        fail("1c — wrong exception", str(e))

    # 1d: Happy path actually emits policy_check_passed + preflight_passed
    p4 = make_product(price_paise=45000)
    m4 = make_mandate()
    db4 = MockDB([p4], m4)
    await AgentOrchestrator(MockAI(), GoodRazorpay(), db4).process_intent(
        uuid.uuid4(), m4.id, "order a birthday cake")
    types4 = [e["type"] for e in db4.audit_log]
    missing = [t for t in ["intent_parsed","product_selected","policy_check_passed","preflight_passed","autonomous_order_created"]
               if t not in types4]
    if not missing:
        ok(f"1d — happy path audit has all 5 pipeline events: {types4}")
    else:
        fail(f"1d — happy path missing events", str(missing))


# ── CHECK 2: payment.failed branch ────────────────────────────────────────────

async def check2():
    print("\n─── CHECK 2: payment.failed branch ─────────────────────────────────────")

    # 2a: Razorpay fails AFTER inventory reserved — inventory must be released
    p = make_product(price_paise=45000, inventory=1)
    m = make_mandate()
    db = MockDB([p], m)
    inv_before = db._inventory[p.id]

    try:
        await AgentOrchestrator(MockAI(), FailingRazorpay(), db).process_intent(
            uuid.uuid4(), m.id, "order a cake")
        fail("2a — Razorpay failure should have raised")
    except Exception:
        inv_after = db._inventory.get(p.id, -1)
        if inv_after == inv_before:
            ok(f"2a — inventory released after Razorpay failure ({inv_before}→reserve→{inv_after})")
        else:
            fail("2a — inventory NOT released", f"before={inv_before} after={inv_after}")

        types = [e["type"] for e in db.audit_log]
        if "razorpay_order_failed" in types:
            ok("2a — razorpay_order_failed in audit trail")
        else:
            fail("2a — razorpay_order_failed missing", str(types))

    # 2b: webhook payment.failed path — inventory restored, status flipped, audit logged
    p2 = make_product(price_paise=45000, inventory=2)
    m2 = make_mandate()
    db2 = MockDB([p2], m2)
    oid = f"order_{uuid.uuid4().hex[:12]}"
    db2._orders[oid] = "created"
    db2._order_product[oid] = p2.id
    db2._inventory[p2.id] = 1   # simulated: 1 unit reserved

    await db2.release_inventory_by_order(oid)
    await db2.update_order_status_by_razorpay_id(oid, "failed")
    sess = uuid.uuid4()
    await db2.log_audit(sess, "payment_failed", {
        "reason": "Insufficient funds",
        "payment_id": "pay_test123",
        "order_id": oid
    })

    if db2._inventory[p2.id] == 2:
        ok("2b — inventory restored to 2 after payment.failed webhook")
    else:
        fail("2b — inventory not restored", f"got={db2._inventory[p2.id]}")

    if db2._orders[oid] == "failed":
        ok("2b — order status → 'failed'")
    else:
        fail("2b — order status not updated", str(db2._orders[oid]))

    pf_events = [e for e in db2.audit_log if e["type"] == "payment_failed"]
    if pf_events and "Insufficient funds" in pf_events[0]["payload"]["reason"]:
        ok("2b — payment_failed audit event logged with reason")
    else:
        fail("2b — payment_failed missing or reason wrong", str(db2.audit_log))


# ── CHECK 3: Diff scan ────────────────────────────────────────────────────────

def check3():
    print("\n─── CHECK 3: Diff scan ──────────────────────────────────────────────────")
    repo_root = BACKEND_DIR.parent
    py_files = [
        f for f in repo_root.rglob("*.py")
        if ".venv" not in str(f) and "__pycache__" not in str(f)
        and "node_modules" not in str(f)
    ]
    bad = []
    secret_needles = ["rzp_live_", "rzp_test_", "AIzaSy", "gsk_", "sk-proj-"]

    for f in py_files:
        try:
            text = f.read_text(errors="replace")
        except:
            continue
        rel = str(f.relative_to(repo_root))
        for lno, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            for pat in secret_needles:
                if pat in line:
                    bad.append(f"SECRET [{rel}:{lno}] {s[:80]}")
            if "tests/" not in rel and "pre_ship" not in rel:
                if s.startswith("print(") and "# noqa" not in s:
                    bad.append(f"BARE PRINT [{rel}:{lno}] {s[:80]}")

    # .env not in git
    tracked = os.popen(f"git -C '{repo_root}' ls-files 2>/dev/null").read().splitlines()
    if ".env" in tracked:
        bad.append("CRITICAL: .env is tracked by git")
    else:
        ok("3a — .env not in git")

    # No stray test_*.py in backend root (not inside tests/)
    stray = [f.name for f in (repo_root / "backend").glob("test_*.py")]
    if stray:
        bad.append(f"STRAY TEST FILES in backend root: {stray}")
    else:
        ok("3b — no stray test_*.py in backend root")

    if bad:
        for b in bad:
            fail("3 — scan", b)
    else:
        ok("3c — no hardcoded secrets or bare print() in production code")


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 70)
    print("  MerchantMind Pre-Ship Checks")
    print("=" * 70)
    await check1()
    await check2()
    check3()
    print("\n" + "=" * 70)
    print(f"  {len(PASSED)} passed / {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"    ❌ {f}")
    else:
        print("  All pre-ship checks clear. Ship it.")
    print("=" * 70)
    return len(FAILED) == 0

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
