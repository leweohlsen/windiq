"""Test setup: run the suite against a dedicated, disposable test database.

DATABASE_URL is pointed at windiq_test (created if missing, schema applied via
alembic) so integration tests never touch the app's development data.
"""
import asyncio
import os
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()

TEST_DB = "windiq_test"


def _with_db_name(url: str, db_name: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname
    port = parts.port or 5432
    auth = ""
    if parts.username:
        auth = parts.username
        if parts.password:
            auth += f":{parts.password}"
        auth += "@"
    return urlunsplit((
        parts.scheme,
        f"{auth}{host}:{port}",
        f"/{db_name}",
        parts.query or "",
        "",
    ))


app_url = os.getenv("DATABASE_URL") or "postgresql+asyncpg://windiq:windiq@localhost:5432/windiq"
os.environ["DATABASE_URL"] = _with_db_name(app_url, TEST_DB)


async def _create_database() -> None:
    engine = create_async_engine(app_url)
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        try:
            await conn.execute(
                text(f"CREATE DATABASE {TEST_DB}")  # noqa: S608 — fixed identifier
            )
        except Exception:  # noqa: S110 — already exists
            pass
    await engine.dispose()


def pytest_configure(config):
    asyncio.run(_create_database())

    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
