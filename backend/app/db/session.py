import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

if DEMO_MODE:
    DATABASE_URL = "sqlite+aiosqlite:///:memory:"
else:
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/merchantmind")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()
