import uuid
from typing import List
from sqlalchemy.future import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.all_models import Product, Mandate, AgentOrder, AuditEvent
from app.schemas.schemas import ProductSchema


class DBRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_product(self, product_id: uuid.UUID) -> ProductSchema:
        result = await self.session.execute(select(Product).filter(Product.id == product_id))
        p = result.scalar_one_or_none()
        if not p:
            raise ValueError(f"Product {product_id} not found")
        return ProductSchema(
            id=p.id,
            merchant_id=p.merchant_id,
            name=p.name,
            description=p.description or "",
            category=p.category,
            price_paise=p.price_paise,
            inventory=p.inventory
        )

    async def search_products(self, category: str, max_price: int) -> List[ProductSchema]:
        result = await self.session.execute(
            select(Product)
            .filter(Product.category == category)
            .filter(Product.price_paise <= max_price)
            .filter(Product.inventory > 0)
        )
        products = result.scalars().all()
        return [
            ProductSchema(
                id=p.id,
                merchant_id=p.merchant_id,
                name=p.name,
                description=p.description or "",
                category=p.category,
                price_paise=p.price_paise,
                inventory=p.inventory
            ) for p in products
        ]

    async def get_mandate(self, mandate_id: uuid.UUID):
        result = await self.session.execute(select(Mandate).filter(Mandate.id == mandate_id))
        m = result.scalar_one_or_none()
        if not m:
            raise ValueError(f"Mandate {mandate_id} not found")
        return m

    async def get_daily_spend(self, mandate_id: uuid.UUID) -> int:
        from app.models.all_models import DailySpend
        from datetime import date
        result = await self.session.execute(
            select(DailySpend)
            .filter(DailySpend.mandate_id == mandate_id)
            .filter(DailySpend.spend_date == date.today())
        )
        record = result.scalar_one_or_none()
        return record.total_paise if record else 0

    async def has_order(self, session_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(AgentOrder)
            .filter(AgentOrder.session_id == session_id)
            .filter(AgentOrder.product_id == product_id)
        )
        return result.scalar_one_or_none() is not None

    async def reserve_inventory_atomic(self, product_id: uuid.UUID) -> bool:
        """
        Atomically decrement inventory by 1, but ONLY if inventory > 0.
        
        This is a compare-and-swap operation that closes the race condition window.
        Two concurrent requests can both read inventory=1 and both pass the
        PreflightGuard check. This method ensures only ONE of them actually
        decrements and returns True. The other receives rowcount=0 and returns False.
        
        This is the single correct way to handle the "last unit" race condition
        without holding a DB lock across a long external Razorpay API call.
        
        Returns:
            True  — reservation succeeded, this caller owns the unit.
            False — inventory was already 0, caller must treat as preflight failure.
        """
        result = await self.session.execute(
            update(Product)
            .where(Product.id == product_id)
            .where(Product.inventory > 0)          # Conditional: only if still available
            .values(inventory=Product.inventory - 1)
        )
        await self.session.commit()
        return result.rowcount == 1  # Exactly 1 row updated = reservation won

    async def release_inventory(self, product_id: uuid.UUID) -> None:
        """
        Release a previously reserved inventory unit back.
        Called when payment creation fails after a successful reservation.
        """
        await self.session.execute(
            update(Product)
            .where(Product.id == product_id)
            .values(inventory=Product.inventory + 1)
        )
        await self.session.commit()

    async def save_order(
        self,
        session_id: uuid.UUID,
        mandate_id: uuid.UUID,
        product_id: uuid.UUID,
        order_id: str,
        amount_paise: int,
        idempotency_key: str
    ):
        from app.models.all_models import DailySpend
        from datetime import date

        order = AgentOrder(
            session_id=session_id,
            mandate_id=mandate_id,
            product_id=product_id,
            razorpay_order_id=order_id,
            idempotency_key=idempotency_key,
            amount_paise=amount_paise,
            status="created"
        )
        self.session.add(order)

        # Track daily spend atomically alongside order creation
        today = date.today()
        result = await self.session.execute(
            select(DailySpend)
            .filter(DailySpend.mandate_id == mandate_id)
            .filter(DailySpend.spend_date == today)
        )
        daily_record = result.scalar_one_or_none()
        if daily_record:
            daily_record.total_paise += amount_paise
        else:
            daily_record = DailySpend(mandate_id=mandate_id, spend_date=today, total_paise=amount_paise)
            self.session.add(daily_record)

        await self.session.commit()

    async def update_order_status_by_razorpay_id(self, razorpay_order_id: str, status: str) -> None:
        """Update the status of an order after a webhook."""
        await self.session.execute(
            update(AgentOrder)
            .where(AgentOrder.razorpay_order_id == razorpay_order_id)
            .values(status=status)
        )
        await self.session.commit()

    async def release_inventory_by_order(self, razorpay_order_id: str) -> None:
        """Release reserved inventory if the payment fails."""
        result = await self.session.execute(
            select(AgentOrder.product_id)
            .where(AgentOrder.razorpay_order_id == razorpay_order_id)
        )
        product_id = result.scalar_one_or_none()
        if product_id:
            await self.release_inventory(product_id)

    async def log_audit(self, session_id: uuid.UUID, event_type: str, payload: dict):
        event = AuditEvent(
            session_id=session_id,
            event_type=event_type,
            payload=payload
        )
        self.session.add(event)
        await self.session.commit()

    async def get_audit_trail(self, session_id: uuid.UUID):
        result = await self.session.execute(
            select(AuditEvent)
            .filter(AuditEvent.session_id == session_id)
            .order_by(AuditEvent.timestamp.asc())
        )
        return result.scalars().all()

    async def set_inventory(self, product_id: uuid.UUID, count: int):
        """For demo/testing only: directly set inventory count."""
        await self.session.execute(
            update(Product)
            .where(Product.id == product_id)
            .values(inventory=count)
        )
        await self.session.commit()
