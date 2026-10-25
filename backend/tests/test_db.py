"""Integration tests for the persistence layer (needs a reachable Postgres).

The database must have the schema applied (`alembic upgrade head`); CI and
`docker compose up db` both provide that. Tests seed their own reference rows
(TEST-*) and clean up after themselves.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import repo
from app.db.engine import SessionLocal, ping as db_ping


def _hour() -> datetime:
    return NOW.replace(minute=0, second=0, microsecond=0)


NOW = datetime.now(timezone.utc)


@pytest.fixture
async def db():
    try:
        reachable = await db_ping()
    except Exception:
        reachable = False
    if not reachable:
        pytest.skip("Postgres unreachable — run `docker compose up -d db`")
    async with SessionLocal() as session:
        yield session


async def _wipe(db) -> None:
    await db.execute(text("DELETE FROM measurements"))
    await db.execute(text("DELETE FROM ingest_runs"))
    await db.execute(text("DELETE FROM site"))
    await db.execute(text("DELETE FROM power_curve_points"))
    await db.execute(text("DELETE FROM turbine"))
    await db.execute(text("DELETE FROM mast"))
    await db.commit()


@pytest.fixture(autouse=True)
async def clean(db):
    await _wipe(db)
    yield
    await _wipe(db)


@pytest.fixture
async def reference(db):
    await repo.upsert_mast(db, {
        "id": "TEST-M", "name": "Test mast", "latitude": 51.9,
        "longitude": 14.0, "measurement_height_m": 100.0,
        "operator": "Test ops", "commissioned_at": NOW.date(),
    })
    await repo.upsert_turbine(db, {
        "id": "TEST-T", "name": "Test turbine", "rated_power_kw": 3600.0,
        "hub_height_m": 140.0, "rotor_diameter_m": 136.0,
        "cut_in_wind_speed_ms": 3.0, "cut_out_wind_speed_ms": 25.0,
        "version": 1, "updated_at": NOW,
    }, power_curve=[(0.0, 0.0), (10.0, 1800.0), (20.0, 3600.0)])
    await repo.upsert_site(db, {
        "id": "TEST-S", "name": "Test site", "mast_id": "TEST-M",
        "shear_exponent": 0.2, "availability_loss": 0.03,
        "electrical_loss": 0.02, "wake_loss": 0.05, "uncertainty": 0.1,
        "version": 1, "updated_at": NOW,
    })


def _row(ts: datetime, wind: str | float | None, unit: str = "m/s",
         quality: str = "ok", version: int = 1,
         updated_at: datetime | None = None, wind_dir: int = 180) -> dict:
    wind_speed_ms = None
    if isinstance(wind, float):
        wind_speed_ms = wind
    if unit == "km/h" and wind_speed_ms is not None:
        wind_speed_ms = wind_speed_ms / 3.6
    return {
        "mast_id": "TEST-M",
        "timestamp": ts,
        "timestamp_raw": ts.isoformat(),
        "wind_speed_ms": wind_speed_ms,
        "unit": unit,
        "wind_speed_raw": str(wind),
        "wind_dir_deg": wind_dir,
        "quality": quality,
        "version": version,
        "updated_at": updated_at or ts,
    }


async def stored_value(db, ts: datetime) -> tuple:
    return (await db.execute(
        text("SELECT wind_speed_ms, version FROM measurements"
             " WHERE mast_id = 'TEST-M' AND timestamp = :t"), {"t": ts}
    )).one()


async def test_upsert_precedence(db, reference):
    t0 = _hour()
    assert await repo.upsert_measurements(
        db, [_row(t0, 7.5, version=1, updated_at=t0 + HOUR_LATER)]
    ) == (1, 0)

    # same key with an older updated_at must never overwrite (idempotent replay)
    assert await repo.upsert_measurements(
        db, [_row(t0, 1.0, version=0, updated_at=t0 + HOUR_LATER - timedelta(minutes=1))]
    ) == (0, 0)
    wind_speed_ms, version = await stored_value(db, t0)
    assert (wind_speed_ms, version) == (7.5, 1)

    # a newer revision wins
    assert await repo.upsert_measurements(
        db, [_row(t0, 9.0, version=2, updated_at=t0 + HOUR_LATER + timedelta(minutes=1))]
    ) == (0, 1)
    wind_speed_ms, version = await stored_value(db, t0)
    assert (wind_speed_ms, version) == (9.0, 2)

    # exact replays change nothing
    assert await repo.upsert_measurements(
        db, [_row(t0, 9.0, version=2, updated_at=t0 + HOUR_LATER + timedelta(minutes=1))]
    ) == (0, 0)


HOUR_LATER = timedelta(hours=1)


async def test_upsert_batch_counts_and_persistence(db, reference):
    t0 = _hour()
    rows = [_row(t0, 5.0), _row(t0 + HOUR_LATER, 6.0), _row(t0 + 2 * HOUR_LATER, 7.0)]
    assert await repo.upsert_measurements(db, rows) == (3, 0)

    # one existing hour revised, one new hour, one unchanged hour
    rows[0] = _row(t0, 5.5, version=2, updated_at=t0 + timedelta(minutes=30))
    rows.append(_row(t0 + 3 * HOUR_LATER, 8.0))
    assert await repo.upsert_measurements(db, rows) == (1, 1)
    wind_speed_ms, _ = await stored_value(db, t0)
    assert wind_speed_ms == 5.5


async def test_upsert_dedupes_within_batch(db, reference):
    t0 = _hour()
    # the API reports some UTC hours twice ('Z' vs '+00:00' suffix): same key
    rows = [
        _row(t0, 4.0, version=1, updated_at=t0),
        _row(t0, 6.0, version=2, updated_at=t0 + timedelta(minutes=30)),
    ]
    assert await repo.upsert_measurements(db, rows) == (1, 0)
    wind_speed_ms, version = await stored_value(db, t0)
    assert (wind_speed_ms, version) == (6.0, 2)


async def test_quality_check_constraint(db, reference):
    t0 = _hour()
    with pytest.raises(Exception):  # noqa: B017 — PG IntegrityError, driver-wrapped
        await repo.upsert_measurements(db, [_row(t0, 5.0, quality="broken")])
    await db.rollback()


async def test_power_at_interpolation(db, reference):
    async def curve_at(v: float) -> float:
        return (await db.execute(
            text("SELECT power_at(:v)"), {"v": v})).scalar_one()

    assert await curve_at(-3.0) == 0.0           # below lowest point → calm
    assert await curve_at(2.5) == pytest.approx(450.0)   # interpolated
    assert await curve_at(5.0) == pytest.approx(900.0)
    assert await curve_at(10.0) == pytest.approx(1800.0)
    assert await curve_at(15.0) == pytest.approx(2700.0)
    assert await curve_at(20.0) == pytest.approx(3600.0)   # top grid point
    assert await curve_at(30.0) == 0.0           # beyond the curve → no operation


async def test_hourly_energy_excludes_suspect(db, reference):
    t0 = _hour()
    await repo.upsert_measurements(db, [
        _row(t0, 8.0, quality="ok"),
        _row(t0 + HOUR_LATER, 8.0, quality="suspect"),
    ])
    rows = (await db.execute(
        text("SELECT speed_hub_ms, energy_kwh FROM hourly_energy"
             " WHERE mast_id = 'TEST-M'"))).all()
    assert len(rows) == 1
    hub_speed, energy_kwh = rows[0]
    # α = 0.2 → hub factor (140/100)^0.2 ≈ 1.0696
    assert hub_speed == pytest.approx(8.0 * (140.0 / 100.0) ** 0.2)
    assert 0.0 < energy_kwh < 3600.0 * (140.0 / 100.0) ** 0.2

    aep = await repo.aep_trailing_12m(db)
    assert aep["usable_hours"] == 1
    assert aep["aep_gross_kwh"] == pytest.approx(energy_kwh)


async def test_daily_series_and_coverage(db, reference):
    t0 = _hour()
    await repo.upsert_measurements(db, [
        _row(t0, 8.0, quality="ok"),
        _row(t0 + HOUR_LATER, 8.0, quality="ok"),
        _row(t0 + 2 * HOUR_LATER, None, quality="malformed"),
        _row(t0 + 3 * HOUR_LATER, 9.0, quality="ok"),
    ])
    daily = await repo.daily_series(db)
    assert len(daily) >= 1
    row = next(d for d in daily if d["day"] == t0.date())
    assert row["hours"] == 3
    assert row["mean_wind_ms"] == pytest.approx((8.0 + 8.0 + 9.0) / 3)

    coverage = await repo.coverage(db)
    assert coverage["total_hours"] == 4
    assert coverage["usable_hours"] == 3
    assert coverage["bad_hours"] == 1
    assert coverage["suspect_hours"] == 0
    assert coverage["expected_hours"] == 4          # contiguous 4 h span
    assert coverage["missing_hours"] == 0


async def test_ingest_run_journal(db, reference):
    t0 = _hour()
    health = await repo.ingest_health(db)
    assert health["last_run"] is None

    await repo.upsert_measurements(db, [_row(t0, 5.0)])
    run = await repo.record_ingest_run(
        db, started_at=t0, finished_at=t0 + timedelta(minutes=4),
        status="ok", pages=2, inserted=1, updated=0,
        frame_from=t0, frame_to=t0 + HOUR_LATER)
    await db.commit()

    health = await repo.ingest_health(db)
    assert health["last_run"]["id"] == run.id
    assert health["last_run"]["status"] == "ok"
    assert health["last_run"]["pages"] == 2
    assert health["last_data_update"] is not None


async def test_migrations_roundtrip():
    """downgrade base must be clean, and re-upgrading restores the schema."""
    def run(version: str) -> None:
        alembic = Config("alembic.ini")
        if version == "head":
            command.upgrade(alembic, "head")
        else:
            command.downgrade(alembic, version)

    await asyncio.to_thread(run, "base")
    await asyncio.to_thread(run, "head")
    async with SessionLocal() as session:
        tables = (await session.execute(text(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = 'public'"))).scalars().all()
    assert {"mast", "turbine", "power_curve_points", "site", "measurements",
            "ingest_runs", "daily_energy", "hourly_energy"} <= set(tables)
