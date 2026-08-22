import uuid
from datetime import datetime, timezone
from app.core.policy_engine import PolicyEngine
from app.core.preflight_guard import PreflightGuard
from app.core.logger import StructuredLogger
from app.schemas.schemas import SpendingMandateSchema
from app.core.errors import (
    AgentNotAuthorizedError,
    PreflightInventoryError,
    IdempotencyConflictError,
)

logger = StructuredLogger("agent_orchestrator")


class AgentOrchestrator:
    def __init__(self, ai_provider, razorpay_client, db_session):
        self.ai = ai_provider
        self.rzp = razorpay_client
        self.db = db_session

    async def process_intent(
        self,
        session_id: uuid.UUID,
        mandate_id: uuid.UUID,
        user_intent: str
    ):
        # ── Step 1: Parse Intent (AI) ────────────────────────────────────────
        parsed_intent = await self.ai.parse_intent(user_intent)
        logger.info(
            "agent.intent_parsed",
            session_id=str(session_id),
            intent=parsed_intent.model_dump()
        )

        # ── Step 2: Search Catalog (DB) ──────────────────────────────────────
        products = await self.db.search_products(
            parsed_intent.category, parsed_intent.max_price_paise
        )
        if not products:
            raise Exception("No products found matching intent constraints")

        # Snapshot original prices so we can detect staleness during preflight.
        original_prices = {p.id: p.price_paise for p in products}

        # ── Step 3: Rank Products (AI) ───────────────────────────────────────
        ranking = await self.ai.rank_products(parsed_intent, products)
        selected_product_id = ranking.selected_product_id

        # ── Recovery loop: max 3 attempts ────────────────────────────────────
        max_attempts = 3
        for attempt in range(max_attempts):

            # Refresh product from DB every attempt (get fresh inventory/price)
            product = await self.db.get_product(selected_product_id)
            mandate = await self.db.get_mandate(mandate_id)
            daily_spent = await self.db.get_daily_spend(mandate_id)

            # ── Step 4: Mandate Validation (Deterministic) ───────────────────
            # NOTE: Amount comes from DB, never from AI output.
            policy_res = PolicyEngine.validate(
                amount_paise=product.price_paise,  # Always DB price
                daily_spent_paise=daily_spent,
                mandate=mandate,
                product_category=product.category,
                merchant_id=product.merchant_id
            )

            if not policy_res.approved:
                logger.info(
                    "ai_boundary_enforced",
                    session_id=str(session_id),
                    boundary_triggered="policy_engine",
                    outcome="blocked",
                    reason=policy_res.reason,
                    ai_override_possible=False,
                    note="Deterministic rule, not AI"
                )
                await self.db.log_audit(
                    session_id, "policy_blocked", {"reason": policy_res.reason}
                )
                raise AgentNotAuthorizedError(policy_res.reason)

            # ── Step 5: Preflight Guard (Deterministic) ──────────────────────
            has_order = await self.db.has_order(session_id, product.id)

            # quoted_price is what AI saw during catalog search
            quoted_price = original_prices.get(product.id, product.price_paise)

            guard_res = PreflightGuard.validate(
                product_id=product.id,
                session_id=session_id,
                mandate_id=mandate.id,
                quoted_price_paise=quoted_price,
                current_price_paise=product.price_paise,  # Fresh from DB
                inventory_count=product.inventory,
                has_existing_order=has_order,
            )

            if not guard_res.passed:
                logger.info(
                    "ai_boundary_enforced",
                    session_id=str(session_id),
                    boundary_triggered="preflight_guard",
                    outcome="blocked",
                    reason=guard_res.reason,
                    ai_override_possible=False,
                    note="Deterministic rule, not AI"
                )
                await self.db.log_audit(
                    session_id,
                    "preflight_failed",
                    {"reason": guard_res.reason, "product_id": str(product.id)}
                )

                if "Inventory" in guard_res.reason or "Price" in guard_res.reason:
                    # ── Step 6: Recovery Reasoning (AI) ──────────────────────
                    ranking = await self.ai.reason_recovery(
                        parsed_intent, product, guard_res.reason, products
                    )
                    selected_product_id = ranking.selected_product_id
                    continue
                else:
                    raise IdempotencyConflictError(guard_res.reason)

            # ── Step 7: Atomic Inventory Reservation ─────────────────────────
            # This closes the TOCTOU race condition window.
            # The preflight guard above read inventory > 0, but another concurrent
            # request may also have read inventory > 0. Only ONE will win this
            # conditional UPDATE. The loser gets False and must treat it as a
            # preflight failure and attempt recovery.
            reserved = await self.db.reserve_inventory_atomic(product.id)
            if not reserved:
                await self.db.log_audit(
                    session_id,
                    "inventory_race_condition_lost",
                    {"product_id": str(product.id), "attempt": attempt}
                )
                logger.info(
                    "ai_boundary_enforced",
                    session_id=str(session_id),
                    boundary_triggered="atomic_inventory_reservation",
                    outcome="blocked",
                    reason="Inventory race condition: another buyer won the reservation",
                )
                # Attempt AI recovery to find an alternative
                ranking = await self.ai.reason_recovery(
                    parsed_intent, product, "Inventory unavailable (race condition)", products
                )
                selected_product_id = ranking.selected_product_id
                continue

            # ── Step 8: Authorization Gate (Deterministic) ───────────────────
            amount = product.price_paise  # Always DB price — never AI-sourced
            notes = {
                "mandate_id": str(mandate_id),
                "session_id": str(session_id),
                "product_id": str(product.id),
                "agent_id": "merchantmind_agent",
                "preflight_passed": "true",
                "inventory_reserved": "true",
            }

            if amount <= mandate.auto_approve_limit_paise:
                # ── 8a: Autonomous Execution ──────────────────────────────
                try:
                    order = self.rzp.create_order(amount, notes)
                except Exception as e:
                    # Payment creation failed — release the reservation so
                    # inventory is not permanently locked.
                    await self.db.release_inventory(product.id)
                    await self.db.log_audit(
                        session_id,
                        "razorpay_order_failed",
                        {"error": str(e), "product_id": str(product.id)}
                    )
                    raise

                await self.db.save_order(
                    session_id, mandate_id, product.id,
                    order["id"], amount, guard_res.idempotency_key
                )
                await self.db.log_audit(
                    session_id,
                    "autonomous_order_created",
                    {"order_id": order["id"], "amount_paise": amount}
                )
                logger.info(
                    "agent.order_created.autonomous",
                    session_id=str(session_id),
                    order_id=order["id"]
                )
                return {
                    "status": "autonomous_order_created",
                    "order_id": order["id"],
                    "amount_paise": amount,
                    "product_name": product.name,
                }
            else:
                # ── 8b: Human-in-the-loop ─────────────────────────────────
                import time
                expire_by = int(time.time()) + 300
                try:
                    plink = self.rzp.create_payment_link(
                        amount, f"Approval for {product.name}", notes, expire_by
                    )
                except Exception as e:
                    await self.db.release_inventory(product.id)
                    await self.db.log_audit(
                        session_id,
                        "razorpay_payment_link_failed",
                        {"error": str(e)}
                    )
                    raise

                await self.db.log_audit(
                    session_id,
                    "human_approval_required",
                    {"payment_link": plink["short_url"], "amount_paise": amount}
                )
                logger.info(
                    "agent.payment_link_created.human_approval",
                    session_id=str(session_id),
                    plink_id=plink["id"]
                )
                return {
                    "status": "human_approval_required",
                    "payment_link": plink["short_url"],
                    "amount_paise": amount,
                    "product_name": product.name,
                }

        raise Exception("Failed to recover after max attempts")
