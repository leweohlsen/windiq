"""Integration tests for the persistence layer (needs a reachable Postgres).

The database must have the schema applied (`alembic upgrade head`); CI and
`docker compose up db` both provide that. Shared fixtures (db/clean/reference/
measurement_row) come from conftest; tests seed their own TEST-* rows here.
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import repo
from app.db.engine import SessionLocal

HOUR_LATER = timedelta(hours=1)


async def stored_value(db, ts: datetime) -> tuple:
    return (await db.execute(
        text("SELECT wind_speed_ms, version FROM measurements"
             " WHERE mast_id = 'TEST-M' AND timestamp = :t"), {"t": ts}
    )).one()


async def test_upsert_precedence(db, clean, reference, measurement_row, hour):
    t0 = hour
    assert await repo.upsert_measurements(
        db, [measurement_row(t0, 7.5, version=1, updated_at=t0 + HOUR_LATER)]
    ) == (1, 0)

    # same key with an older updated_at must never overwrite (idempotent replay)
    assert await repo.upsert_measurements(
        db, [measurement_row(
            t0, 1.0, version=0, updated_at=t0 + HOUR_LATER - timedelta(minutes=1)
        )]
    ) == (0, 0)
    wind_speed_ms, version = await stored_value(db, t0)
    assert (wind_speed_ms, version) == (7.5, 1)

    # a newer revision wins
    assert await repo.upsert_measurements(
        db, [measurement_row(
            t0, 9.0, version=2, updated_at=t0 + HOUR_LATER + timedelta(minutes=1)
        )]
    ) == (0, 1)
    wind_speed_ms, version = await stored_value(db, t0)
    assert (wind_speed_ms, version) == (9.0, 2)

    # equal updated_at, higher version: the tiebreak still updates
    assert await repo.upsert_measurements(
        db, [measurement_row(
            t0, 9.5, version=3, updated_at=t0 + HOUR_LATER + timedelta(minutes=1)
        )]
    ) == (0, 1)
    wind_speed_ms, version = await stored_value(db, t0)
    assert (wind_speed_ms, version) == (9.5, 3)

    # equal updated_at, equal version: an exact replay changes nothing
    assert await repo.upsert_measurements(
        db, [measurement_row(
            t0, 9.5, version=3, updated_at=t0 + HOUR_LATER + timedelta(minutes=1)
        )]
    ) == (0, 0)


async def test_upsert_batch_counts_and_persistence(
    db, clean, reference, measurement_row, hour
):
    t0 = hour
    rows = [
        measurement_row(t0, 5.0),
        measurement_row(t0 + HOUR_LATER, 6.0),
        measurement_row(t0 + 2 * HOUR_LATER, 7.0),
    ]
    assert await repo.upsert_measurements(db, rows) == (3, 0)

    # one existing hour revised, one new hour, one unchanged hour
    rows[0] = measurement_row(t0, 5.5, version=2, updated_at=t0 + timedelta(minutes=30))
    rows.append(measurement_row(t0 + 3 * HOUR_LATER, 8.0))
    assert await repo.upsert_measurements(db, rows) == (1, 1)
    wind_speed_ms, _ = await stored_value(db, t0)
    assert wind_speed_ms == 5.5


async def test_upsert_dedupes_within_batch(db, clean, reference, measurement_row, hour):
    t0 = hour
    # the API reports some UTC hours twice ('Z' vs '+00:00' suffix): same key
    rows = [
        measurement_row(t0, 4.0, version=1, updated_at=t0),
        measurement_row(t0, 6.0, version=2, updated_at=t0 + timedelta(minutes=30)),
    ]
    assert await repo.upsert_measurements(db, rows) == (1, 0)
    wind_speed_ms, version = await stored_value(db, t0)
    assert (wind_speed_ms, version) == (6.0, 2)

    # equal updated_at: the version tiebreak decides, not arrival order
    rows = [
        measurement_row(t0 + HOUR_LATER, 6.0, version=2, updated_at=t0 + HOUR_LATER),
        measurement_row(t0 + HOUR_LATER, 4.0, version=1, updated_at=t0 + HOUR_LATER),
    ]
    assert await repo.upsert_measurements(db, rows) == (1, 0)
    wind_speed_ms, version = await stored_value(db, t0 + HOUR_LATER)
    assert (wind_speed_ms, version) == (6.0, 2)


async def test_quality_check_constraint(db, clean, reference, measurement_row, hour):
    t0 = hour
    with pytest.raises(Exception):  # noqa: B017 — PG IntegrityError, driver-wrapped
        await repo.upsert_measurements(db, [measurement_row(t0, 5.0, quality="broken")])
    await db.rollback()


async def test_power_at_interpolation(db, clean, reference):
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


async def test_hourly_energy_excludes_suspect(db, clean, reference, measurement_row, hour):
    t0 = hour
    await repo.upsert_measurements(db, [
        measurement_row(t0, 8.0, quality="ok"),
        measurement_row(t0 + HOUR_LATER, 8.0, quality="suspect"),
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


async def test_daily_series_and_coverage(db, clean, reference, measurement_row, hour):
    # 12:00 anchor — a 4 h span crossing midnight would split into two days
    # and flake for runs between 21:00 and 24:00 UTC.
    t0 = hour.replace(hour=12)
    await repo.upsert_measurements(db, [
        measurement_row(t0, 8.0, quality="ok"),
        measurement_row(t0 + HOUR_LATER, 8.0, quality="ok"),
        measurement_row(t0 + 2 * HOUR_LATER, None, quality="malformed"),
        measurement_row(t0 + 3 * HOUR_LATER, 9.0, quality="ok"),
        # a day with zero ok hours must still appear (a gap that carries QC counts)
        measurement_row(t0 + 48 * HOUR_LATER, -0.5, quality="suspect"),
    ])
    daily = await repo.daily_series(db)
    day = next(d for d in daily if d["day"] == t0.date())
    gap_day = next(d for d in daily if d["day"] == (t0 + timedelta(days=2)).date())
    assert day["hours"] == 3
    assert day["mean_wind_ms"] == pytest.approx((8.0 + 8.0 + 9.0) / 3)
    assert day["suspect_hours"] == 0
    assert day["missing_hours"] == 1
    assert day["energy_kwh"] is not None
    assert gap_day["energy_kwh"] is None
    assert gap_day["hours"] is None
    assert gap_day["suspect_hours"] == 1
    assert gap_day["missing_hours"] == 0

    coverage = await repo.coverage(db)
    assert coverage["total_hours"] == 5
    assert coverage["usable_hours"] == 3
    assert coverage["suspect_hours"] == 1
    assert coverage["missing_hours"] == 0
    assert coverage["malformed_hours"] == 1
    assert coverage["expected_hours"] == 49   # contiguous span: 48 h + first hour
    assert coverage["absent_hours"] == 44     # 49 expected - 5 stored
    assert coverage["max_gap_hours"] == 44    # 45 h between the day neighbours


async def test_coverage_ignores_rows_older_than_twelve_months(
    db, clean, reference, measurement_row, hour
):
    await repo.upsert_measurements(db, [
        measurement_row(hour - timedelta(days=400), 8.0),
        measurement_row(hour, 8.0),
    ])
    coverage = await repo.coverage(db)
    assert coverage["total_hours"] == 1
    assert coverage["expected_hours"] == 1
    assert coverage["max_gap_hours"] == 0


async def test_wind_series_trailing_window(db, clean, reference, measurement_row, hour):
    t0 = hour
    await repo.upsert_measurements(db, [
        measurement_row(t0 - 3 * HOUR_LATER, 5.0),
        measurement_row(t0 - 2 * HOUR_LATER, 83.0, quality="suspect"),
        measurement_row(t0 - HOUR_LATER, None, quality="missing"),
        # t0 itself gets no row: the absent hour must surface as an empty bucket
    ])
    series = await repo.wind_series(db, days=1)
    assert [p["timestamp"] for p in series] == \
        sorted(p["timestamp"] for p in series)      # oldest first
    assert len(series) == 25    # every hour of [trunc(now) - 1 d, trunc(now)]

    by_ts = {p["timestamp"]: p for p in series}
    empty = by_ts[t0]
    assert empty["mean_wind_ms"] is None
    assert empty["min_wind_ms"] is None
    assert empty["max_wind_ms"] is None
    assert (empty["ok_hours"], empty["suspect_hours"],
            empty["missing_hours"], empty["malformed_hours"]) == (0, 0, 0, 0)

    ok = by_ts[t0 - 3 * HOUR_LATER]
    assert ok["mean_wind_ms"] == pytest.approx(5.0)
    assert ok["ok_hours"] == 1

    suspect = by_ts[t0 - 2 * HOUR_LATER]
    assert suspect["max_wind_ms"] == pytest.approx(83.0)   # suspect value is a value
    assert (suspect["ok_hours"], suspect["suspect_hours"]) == (0, 1)

    missing = by_ts[t0 - HOUR_LATER]
    assert missing["mean_wind_ms"] is None
    assert missing["missing_hours"] == 1


async def test_wind_series_day_and_week_buckets(db, clean, reference, measurement_row, hour):
    # 12:00 anchor — the four hours stay on one UTC day (see sibling tests)
    t0 = hour.replace(hour=12)
    monday = (t0 - timedelta(days=t0.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    await repo.upsert_measurements(db, [
        measurement_row(t0 - 3 * HOUR_LATER, 5.0),
        measurement_row(t0 - 2 * HOUR_LATER, 83.0, quality="suspect"),
        measurement_row(t0 - HOUR_LATER, -1.0, quality="suspect"),
        measurement_row(t0, None, quality="missing"),
        measurement_row(monday - timedelta(days=3), 3.0),   # previous ISO week
    ])

    daily = await repo.wind_series(db, days=2, resolution="day")
    day = next(p for p in daily if p["timestamp"].date() == t0.date())
    assert day["mean_wind_ms"] == pytest.approx((5.0 + 83.0 - 1.0) / 3)
    assert day["min_wind_ms"] == pytest.approx(-1.0)   # original values feed min/max
    assert day["max_wind_ms"] == pytest.approx(83.0)
    assert (day["ok_hours"], day["suspect_hours"], day["missing_hours"]) == (1, 2, 1)

    weekly = await repo.wind_series(db, days=14, resolution="week")
    by_ts = {p["timestamp"]: p for p in weekly}
    this_week = by_ts[monday]
    assert (this_week["ok_hours"], this_week["suspect_hours"],
            this_week["missing_hours"]) == (1, 2, 1)
    last_week = by_ts[monday - timedelta(days=7)]
    assert last_week["mean_wind_ms"] == pytest.approx(3.0)
    assert last_week["ok_hours"] == 1


async def test_wind_rose_matches_hand_computed_sectors(
    db, clean, reference, measurement_row, hour
):
    """The rose histogram matches a hand-computed sector count (plan phase 3)."""
    t0 = hour
    # sectors hand-computed with ROUND(deg / 22.5) % 16 (direction-centered):
    # 8×N (0° → sector 0), 1×N wrap (358° → 15.9¹¹ → 16 % 16 = 0),
    # 3×NNE (30° → 1), 2×S (180° → 8), 1×NNW (343° → 15.24 → 15)
    rows = (
        [measurement_row(t0 + timedelta(hours=h), 6.0, wind_dir=0)
         for h in range(8)]
        + [measurement_row(t0 + timedelta(hours=50, minutes=5), 5.0, wind_dir=358)]
        + [measurement_row(t0 + timedelta(hours=60 + h, minutes=5), 7.0, wind_dir=30)
           for h in range(3)]
        + [measurement_row(t0 + timedelta(hours=100 + h, minutes=10), 4.0, wind_dir=180)
           for h in range(2)]
        + [measurement_row(t0 + timedelta(hours=200, minutes=15), 5.0, wind_dir=343)]
    )
    await repo.upsert_measurements(db, rows)

    rose = await repo.wind_rose(db)
    assert len(rose) == 16
    by_direction = {s["direction"]: s for s in rose}
    assert by_direction["N"]["frequency"] == 9           # incl. the 360° wrap
    assert by_direction["N"]["mean_speed_ms"] == pytest.approx((8 * 6.0 + 5.0) / 9)
    assert by_direction["NNE"]["frequency"] == 3
    assert by_direction["NNE"]["mean_speed_ms"] == pytest.approx(7.0)
    assert by_direction["S"]["frequency"] == 2
    assert by_direction["S"]["mean_speed_ms"] == pytest.approx(4.0)
    assert by_direction["NNW"]["frequency"] == 1
    assert by_direction["SW"]["frequency"] == 0          # empty sector stays present
    assert by_direction["SW"]["mean_speed_ms"] is None
    assert by_direction["N"]["degrees"] == 0
    assert by_direction["E"]["degrees"] == 90


async def test_ingest_runs_recent(db, clean, hour):
    t0 = hour
    for i, status in enumerate(["ok", "partial", "ok"]):
        await repo.record_ingest_run(
            db, started_at=t0 + timedelta(minutes=i),
            finished_at=t0 + timedelta(minutes=i + 1),
            status=status, pages=i, inserted=i, updated=0,
            qc_suspect=2 * i if status == "partial" else 0,
        )
    await db.commit()

    runs = await repo.ingest_runs_recent(db, limit=2)
    assert [r["status"] for r in runs] == ["ok", "partial"]     # newest first
    assert runs[1]["qc_suspect"] == 2
    assert runs[0]["qc_suspect"] == 0
    assert {"id", "started_at", "finished_at", "status", "pages", "inserted",
            "updated", "frame_from", "frame_to", "qc_missing", "qc_suspect",
            "qc_malformed", "max_gap_hours", "detail"} <= set(runs[0])
    assert len(await repo.ingest_runs_recent(db, limit=10)) == 3


async def test_ingest_run_journal(db, clean, reference, measurement_row, hour):
    t0 = hour
    health = await repo.ingest_health(db)
    assert health["last_run"] is None

    await repo.upsert_measurements(db, [measurement_row(t0, 5.0)])
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


async def test_ingest_window_covered_gate(
    db, clean, reference, measurement_row, hour
):
    """Startup-backfill gate: deep history + fresh forward progress = covered."""
    fresh = hour  # within the 48 h freshness window
    assert await repo.ingest_window_covered(db) is False   # empty store

    # deep history but no forward progress (stale revisions) → not covered
    await repo.upsert_measurements(db, [
        measurement_row(hour - timedelta(days=400), 7.0, updated_at=fresh - timedelta(days=10))
    ])
    await db.commit()
    assert await repo.ingest_window_covered(db) is False

    # fresh forward progress, but history not deep → not covered
    await db.execute(text("DELETE FROM measurements"))
    await repo.upsert_measurements(db, [measurement_row(hour - HOUR_LATER, 7.0)])
    await db.commit()
    assert await repo.ingest_window_covered(db) is False

    # both conditions met → a worker restart must not re-run the backfill
    await repo.upsert_measurements(db, [
        measurement_row(hour - timedelta(days=400), 7.0, updated_at=fresh)
    ])
    await db.commit()
    assert await repo.ingest_window_covered(db) is True


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
