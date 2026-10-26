import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://windiq:windiq@localhost:5432/windiq",
)

# Small pool: one API consumer (the SPA) and one ingest worker.
# JIT is off: dashboard queries are tiny, and Postgres spends more time
# compiling those plan functions (~900 ms measured) than running them.
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    pool_size=2,
    max_overflow=3,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={"server_settings": {"jit": "off"}},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def ping() -> bool:
    async with engine.connect() as conn:
        return bool(await conn.scalar(text("SELECT 1")))
