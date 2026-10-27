"""Test setup: run the suite against a dedicated, disposable test database.

DATABASE_URL is pointed at windiq_test (created if missing, schema applied via
alembic) so integration tests never touch the app's development data. Shared
persistence fixtures (session, cleaning, reference rows, measurement factory)
live here so repo- and endpoint-level tests reuse them.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import repo

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


HOUR = timedelta(hours=1)


@pytest.fixture
async def db() -> AsyncSession:
    from app.db.engine import SessionLocal
    from app.db.engine import ping as db_ping

    try:
        reachable = await db_ping()
    except Exception:
        reachable = False
    if not reachable:
        pytest.skip("Postgres unreachable — run `docker compose up -d db`")
    async with SessionLocal() as session:
        yield session


async def _wipe(db: AsyncSession) -> None:
    await db.execute(text("DELETE FROM measurements"))
    await db.execute(text("DELETE FROM ingest_runs"))
    await db.execute(text("DELETE FROM site"))
    await db.execute(text("DELETE FROM power_curve_points"))
    await db.execute(text("DELETE FROM turbine"))
    await db.execute(text("DELETE FROM mast"))
    await db.commit()


@pytest.fixture
async def clean(db) -> AsyncSession:
    await _wipe(db)
    yield db
    await _wipe(db)


@pytest.fixture
async def reference(db: AsyncSession):
    """Seed the TEST-* reference rows (mast/turbine/site) the row factory keys on."""
    stamp = datetime.now(timezone.utc)
    await repo.upsert_mast(db, {
        "id": "TEST-M", "name": "Test mast", "latitude": 51.9,
        "longitude": 14.0, "measurement_height_m": 100.0,
        "operator": "Test ops", "commissioned_at": stamp.date(),
    })
    await repo.upsert_turbine(db, {
        "id": "TEST-T", "name": "Test turbine", "rated_power_kw": 3600.0,
        "hub_height_m": 140.0, "rotor_diameter_m": 136.0,
        "cut_in_wind_speed_ms": 3.0, "cut_out_wind_speed_ms": 25.0,
        "version": 1, "updated_at": stamp,
    }, power_curve=[(0.0, 0.0), (10.0, 1800.0), (20.0, 3600.0)])
    await repo.upsert_site(db, {
        "id": "TEST-S", "name": "Test site", "mast_id": "TEST-M",
        "shear_exponent": 0.2, "availability_loss": 0.03,
        "electrical_loss": 0.02, "wake_loss": 0.05, "uncertainty": 0.1,
        "version": 1, "updated_at": stamp,
    })


@pytest.fixture
def hour() -> datetime:
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


@pytest.fixture
def measurement_row() -> repo.MeasurementRow:
    def factory(
        ts: datetime, wind: str | float, version: int = 1,
        updated_at: datetime | None = None, mast_id: str = "TEST-M",
        wind_dir: int = 180, qc_note: str | None = None,
    ) -> repo.MeasurementRow:
        wind_speed_ms = float(wind)
        return repo.MeasurementRow(
            mast_id=mast_id,
            timestamp=ts,
            timestamp_raw=ts.isoformat(),
            wind_speed_ms=wind_speed_ms,
            wind_speed_raw=str(wind),
            wind_dir_deg=wind_dir,
            qc_note=qc_note,
            version=version,
            updated_at=updated_at or ts,
        )
    return factory
