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


async def test_inserted_rows_always_carry_a_value(db, clean, reference, measurement_row, hour):
    """The stored invariant: every measurement row has a usable speed."""
    t0 = hour
    await repo.upsert_measurements(db, [
        measurement_row(t0, 5.0),
        measurement_row(t0 + HOUR_LATER, 6.0, qc_note="kein Messwert geliefert"),
    ])
    await db.commit()
    nulls = (await db.execute(text(
        "SELECT COUNT(*) FROM measurements WHERE wind_speed_ms IS NULL"
    ))).scalar_one()
    assert nulls == 0


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


async def test_hourly_energy_covers_all_rows(db, clean, reference, measurement_row, hour):
    """Every stored hour feeds the energy math (the store holds only values)."""
    t0 = hour
    await repo.upsert_measurements(db, [
        measurement_row(t0, 8.0),
        measurement_row(t0 + HOUR_LATER, 6.0, qc_note="kein Messwert geliefert"),
    ])
    rows = (await db.execute(
        text("SELECT speed_hub_ms, energy_kwh FROM hourly_energy"
             " WHERE mast_id = 'TEST-M'"))).all()
    assert len(rows) == 2
    # α = 0.2 → hub factor (140/100)^0.2 ≈ 1.0696
    speeds = sorted(s for s, _ in rows)
    assert speeds == pytest.approx(sorted(
        [v * (140.0 / 100.0) ** 0.2 for v in (6.0, 8.0)]
    ))

    aep = await repo.aep_trailing_12m(db)
    assert aep["usable_hours"] == 2
    assert aep["aep_gross_kwh"] > 0


async def test_daily_series_and_coverage(db, clean, reference, measurement_row, hour):
    # 12:00 anchor, one day back — the 4 h span stays on one UTC day and the
    # gap day (+1) lands inside the 30-day daily window.
    t0 = (hour - timedelta(days=1)).replace(hour=12)
    await repo.upsert_measurements(db, [
        measurement_row(t0, 8.0),
        measurement_row(t0 + HOUR_LATER, 8.0),
        # an interpolated hour keeps counting (the store only has valid values)
        measurement_row(t0 + 2 * HOUR_LATER, 7.0, qc_note="kein Messwert geliefert"),
        measurement_row(t0 + 3 * HOUR_LATER, 9.0),
        # a day with zero stored hours must still appear (as an energy gap)
        measurement_row(t0 + 48 * HOUR_LATER, 7.0),
    ])
    daily = await repo.daily_series(db)
    day = next(d for d in daily if d["day"] == t0.date())
    gap_day = next(d for d in daily if d["day"] == (t0 + timedelta(days=1)).date())
    assert day["hours"] == 4
    assert day["mean_wind_ms"] == pytest.approx((8.0 + 8.0 + 7.0 + 9.0) / 4)
    assert day["energy_kwh"] is not None
    assert gap_day["energy_kwh"] is None
    assert gap_day["hours"] is None

    coverage = await repo.coverage(db)
    assert coverage["total_hours"] == 5
    assert coverage["interpolated_hours"] == 1
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
        measurement_row(t0 - 2 * HOUR_LATER, 6.0),
        # t0 - 1 h and t0 itself get no row: absent hours are empty buckets
    ])
    await db.commit()
    series = await repo.wind_series(db, days=1)
    assert [p["timestamp"] for p in series] == \
        sorted(p["timestamp"] for p in series)      # oldest first
    assert len(series) == 25    # every hour of [trunc(now) - 1 d, trunc(now)]

    by_ts = {p["timestamp"]: p for p in series}
    empty = by_ts[t0]
    assert empty["mean_wind_ms"] is None
    assert empty["min_wind_ms"] is None
    assert empty["max_wind_ms"] is None
    assert empty["interpolated_hours"] == 0
    assert empty["qc_note"] is None
    assert empty["wind_speed_raw"] is None

    ok = by_ts[t0 - 3 * HOUR_LATER]
    assert ok["mean_wind_ms"] == pytest.approx(5.0)
    assert ok["interpolated_hours"] == 0


async def test_wind_series_carries_interpolation_notes(
    db, clean, reference, measurement_row, hour
):
    """Interpolated hours surface per bucket: count + (aggregated) reasons."""
    # 12:00 anchor, one day back — all four hours sit inside the 24 h window
    t0 = (hour - timedelta(days=1)).replace(hour=12)
    await repo.upsert_measurements(db, [
        measurement_row(t0 - HOUR_LATER, 5.0),
        measurement_row(t0, 6.0, qc_note="kein Messwert geliefert"),
        measurement_row(t0 + HOUR_LATER, 7.0, qc_note="negativer Messwert"),
    ])
    await db.commit()

    hourly = await repo.wind_series(db, days=1)
    by_ts = {p["timestamp"]: p for p in hourly}
    assert by_ts[t0]["interpolated_hours"] == 1
    assert by_ts[t0]["qc_note"] == "kein Messwert geliefert"
    # the rejected original of the interpolated hour travels with the bucket
    assert by_ts[t0]["wind_speed_raw"] == "6.0"

    daily = await repo.wind_series(db, days=1, resolution="day")
    day = next(p for p in daily if p["timestamp"].date() == t0.date())
    assert day["interpolated_hours"] == 2
    assert day["qc_note"] == "kein Messwert geliefert; negativer Messwert"
    assert day["wind_speed_raw"] == "6.0; 7.0"   # rejected originals aggregated


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


async def test_interpolate_gaps_fills_absent_hours(
    db, clean, reference, measurement_row, hour
):
    t0 = hour.replace(hour=12)
    await repo.upsert_measurements(db, [
        measurement_row(t0, 2.0),
        measurement_row(t0 + 4 * HOUR_LATER, 6.0),
    ])
    await repo.interpolate_gaps(db, [], mast_id="TEST-M")
    rows = (await db.execute(
        text("SELECT wind_speed_ms, qc_note, version, updated_at, wind_dir_deg"
             " FROM measurements WHERE mast_id = 'TEST-M' ORDER BY timestamp")
    )).all()
    assert [r[0] for r in rows] == [2.0, 3.0, 4.0, 5.0, 6.0]   # linear in between
    assert all(r[1] == "Stunde nicht geliefert" for r in rows[1:3+1])
    # absent rows inherit the revision stamp of the bounding anchor (the edge
    # lead), so the sync watermark never runs ahead of the API
    assert all(r[2] == 1 and r[3] == t0 + 4 * HOUR_LATER for r in rows[1:3+1])
    assert all(r[4] == 180 for r in rows[1:3+1])

    # idempotent: a replay does not add or shift anything
    await repo.interpolate_gaps(db, [], mast_id="TEST-M")
    rows2 = (await db.execute(
        text("SELECT COUNT(*) FROM measurements"))).scalar_one()
    assert rows2 == len(rows)


async def test_interpolate_defect_hour_from_payload(
    db, clean, reference, measurement_row, hour
):
    t0 = hour.replace(hour=12)
    bad = t0 + HOUR_LATER
    await repo.upsert_measurements(db, [
        measurement_row(t0, 2.0, updated_at=t0),
        measurement_row(t0 + 2 * HOUR_LATER, 8.0, updated_at=t0 + 2 * HOUR_LATER),
    ])
    await repo.interpolate_gaps(db, [{
        "ts": bad.isoformat(),
        "note": "kein Messwert geliefert",
        "updated_at": bad.isoformat(),
        "version": 3,
        "wind_speed_raw": "-999.0",
        "timestamp_raw": bad.isoformat(),
        "wind_dir": 200,
    }], mast_id="TEST-M")
    wind_speed_ms, note, version, updated_at, raw, raw_ts, wind_dir = (
        await db.execute(text(
            "SELECT wind_speed_ms, qc_note, version, updated_at,"
            " wind_speed_raw, timestamp_raw, wind_dir_deg FROM measurements"
            " WHERE mast_id = 'TEST-M' AND timestamp = :t"
        ), {"t": bad})
    ).one()
    assert wind_speed_ms == pytest.approx(5.0)
    assert note == "kein Messwert geliefert"
    # the rejected revision stamps the interpolated row
    assert version == 3 and updated_at == bad
    assert raw == "-999.0" and raw_ts == bad.isoformat()
    assert wind_dir == 200


async def test_interpolate_skips_superseded_defects(
    db, clean, reference, measurement_row, hour
):
    """A stored real revision newer than the defect payload stays untouched."""
    t0 = hour.replace(hour=12)
    bad = t0 + HOUR_LATER
    await repo.upsert_measurements(db, [
        measurement_row(t0, 2.0, updated_at=t0),
        # the hour real-good, newer than the defect revision below
        measurement_row(bad, 9.0, version=4, updated_at=bad + timedelta(hours=1)),
        measurement_row(t0 + 2 * HOUR_LATER, 8.0, updated_at=t0 + 2 * HOUR_LATER),
    ])
    await repo.interpolate_gaps(db, [{
        "ts": bad.isoformat(),
        "note": "negativer Messwert",
        "updated_at": bad.isoformat(),
        "version": 3,
        "wind_speed_raw": "-1.0",
        "timestamp_raw": bad.isoformat(),
        "wind_dir": 200,
    }], mast_id="TEST-M")
    wind_speed_ms, note = (await db.execute(text(
        "SELECT wind_speed_ms, qc_note FROM measurements"
        " WHERE mast_id = 'TEST-M' AND timestamp = :t"
    ), {"t": bad})).one()
    assert wind_speed_ms == pytest.approx(9.0)
    assert note is None


async def test_real_revision_replaces_interpolation(
    db, clean, reference, measurement_row, hour
):
    """Real data always wins, even when its own stamp is older than the fill."""
    t0 = hour.replace(hour=12)
    gap = t0 + HOUR_LATER
    await repo.upsert_measurements(db, [
        measurement_row(t0, 2.0, updated_at=t0),
        measurement_row(t0 + 2 * HOUR_LATER, 8.0, updated_at=t0 + 2 * HOUR_LATER),
    ])
    await repo.interpolate_gaps(db, [], mast_id="TEST-M")
    await repo.upsert_measurements(db, [
        # the late real delivery carries the hour's own (older) stamp
        measurement_row(gap, 9.0, version=1, updated_at=gap),
    ])
    wind_speed_ms, note = (await db.execute(text(
        "SELECT wind_speed_ms, qc_note FROM measurements"
        " WHERE mast_id = 'TEST-M' AND timestamp = :t"
    ), {"t": gap})).one()
    assert wind_speed_ms == pytest.approx(9.0)
    assert note is None


async def test_ingest_runs_recent(db, clean, hour):
    t0 = hour
    for i, status in enumerate(["ok", "partial", "ok"]):
        await repo.record_ingest_run(
            db, started_at=t0 + timedelta(minutes=i),
            finished_at=t0 + timedelta(minutes=i + 1),
            status=status, pages=i, inserted=i, updated=0,
            interpolated=2 * i if status == "partial" else 0,
        )
    await db.commit()

    runs = await repo.ingest_runs_recent(db, limit=2)
    assert [r["status"] for r in runs] == ["ok", "partial"]     # newest first
    assert runs[1]["interpolated"] == 2
    assert runs[0]["interpolated"] == 0
    assert {"id", "started_at", "finished_at", "status", "pages", "inserted",
            "updated", "frame_from", "frame_to", "interpolated",
            "max_gap_hours", "detail"} <= set(runs[0])
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
