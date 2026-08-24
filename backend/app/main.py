import os
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.logger import StructuredLogger
from app.api.endpoints import router as api_router
from app.api.demo import router as demo_router
from app.db.session import engine, Base, DEMO_MODE, AsyncSessionLocal

logger = StructuredLogger("main")

async def seed_demo_data():
    """Seed the in-memory SQLite database with demo products and mandate."""
    from app.models.all_models import Product, Mandate
    import hashlib

    async with AsyncSessionLocal() as session:
        merchant_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

        products = [
            Product(
                id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                merchant_id=merchant_id,
                name="Birthday Cake",
                description="Classic vanilla birthday cake with chocolate frosting",
                category="food",
                price_paise=45000,  # ₹450
                inventory=3,
            ),
            Product(
                id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                merchant_id=merchant_id,
                name="Chocolate Truffle Cake",
                description="Rich Belgian chocolate truffle cake",
                category="food",
                price_paise=40000,  # ₹400
                inventory=5,
            ),
            Product(
                id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
                merchant_id=merchant_id,
                name="Red Velvet Cake",
                description="Premium red velvet with cream cheese frosting",
                category="food",
                price_paise=55000,  # ₹550
                inventory=2,
            ),
            Product(
                id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
                merchant_id=merchant_id,
                name="Wireless Earbuds",
                description="Bluetooth 5.0 earbuds with noise cancellation",
                category="electronics",
                price_paise=150000,  # ₹1,500
                inventory=10,
            ),
        ]

        mandate = Mandate(
            id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            principal_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            allowed_categories=["food", "groceries"],
            merchant_whitelist=None,
            transaction_limit_paise=100000,  # ₹1,000
            daily_limit_paise=200000,        # ₹2,000
            auto_approve_limit_paise=100000, # ₹1,000
            expires_at=None,
            hmac_signature=hashlib.sha256(b"demo_mandate").hexdigest(),
        )

        for p in products:
            session.add(p)
        session.add(mandate)
        await session.commit()

    logger.info("demo.data_seeded", products=len(products), mandate_id="00000000-0000-0000-0000-000000000000")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app.startup", status="initializing", demo_mode=DEMO_MODE)
    if DEMO_MODE:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await seed_demo_data()
        logger.info("app.startup.demo_mode", status="ready")
    yield
    logger.info("app.shutdown", status="shutting_down")

app = FastAPI(title="MerchantMind MVP API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(demo_router)

@app.get("/health")
async def health_check():
    return {"status": "ok", "demo_mode": DEMO_MODE}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
