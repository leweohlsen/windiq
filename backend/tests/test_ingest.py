"""Ingest backfill + sync against the test DB, with a fake API client.

No network, no hardcoded data counts (quirks doc §Statistical drift): the
fake client serves a fixed, tiny page set; assertions are about rule
outcomes and idempotence, not about data volume.
"""
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.ingest import backfill, sync
from app.db.engine import SessionLocal
from wind_iq_measurement_api_client.models import (
    Losses,
    Mast,
    Measurement,
    MeasurementPage,
    PowerCurvePoint,
    Site,
    Turbine,
)


REFERENCE_UPDATED_AT = "2026-01-01T00:00:00Z"


def _api_row(ts: str, wind_speed: Any, unit: str = "m/s", version: int = 1,
             minutes_after: int = 5, wind_dir: int = 180) -> Measurement:
    updated = (datetime.fromisoformat(ts.replace("Z", "+00:00"))
               + timedelta(minutes=minutes_after)).isoformat()
    return Measurement(
        timestamp=ts, wind_speed=wind_speed, unit=unit,
        wind_direction_deg=wind_dir, version=version, updated_at=updated,
    )


PAGE1 = [
    _api_row("2026-01-01T00:00:00Z", 7.6),
    _api_row("2026-01-01T01:00:00Z", "8.1"),   # numeric string → ok
    _api_row("2026-01-01T02:00:00Z", None),    # null → missing
    _api_row("2026-01-01T03:00:00Z", -0.5),    # drift → suspect
]
PAGE2 = [
    _api_row("2026-01-01T02:00:00+00:00", 9.4, version=2, minutes_after=90),
    _api_row("2026-01-01T04:00:00Z", 30.0),    # > cut-out + margin → suspect
    _api_row("2026-01-01T05:00:00Z", 20.0),
]


class FakeClient:
    """Fake facade: serves pre-built pages, records the query arguments."""

    def __init__(self, pages: list[list[Measurement]]) -> None:
        self.pages = pages
        self.calls: list[dict] = []

    async def measurements(self, **kwargs):
        self.calls.append(kwargs)
        index = int(kwargs["cursor"]) if kwargs.get("cursor") else 0
        next_cursor = str(index + 1) if index + 1 < len(self.pages) else None
        return MeasurementPage(data=self.pages[index], next_cursor=next_cursor)

    async def turbine(self) -> Turbine:
        return Turbine(
            id="TEST-T", name="Test turbine", rated_power_kw=3600.0,
            hub_height_m=140.0, rotor_diameter_m=136.0,
            cut_in_wind_speed_ms=3.0, cut_out_wind_speed_ms=25.0,
            power_curve=[
                PowerCurvePoint(wind_speed_ms=0.0, power_kw=0.0),
                PowerCurvePoint(wind_speed_ms=10.0, power_kw=1800.0),
                PowerCurvePoint(wind_speed_ms=25.0, power_kw=3600.0),
            ],
            version=1, updated_at=REFERENCE_UPDATED_AT,
        )

    async def mast(self) -> Mast:
        return Mast(
            id="TEST-M", name="Test mast", latitude=51.9, longitude=14.0,
            measurement_height_m=100.0, operator="Test ops",
            commissioned_at="2025-01-01",
        )

    async def site(self) -> Site:
        return Site(
            id="TEST-S", name="Test site", mast_id="TEST-M",
            shear_exponent=0.2,
            losses=Losses(availability=0.03, electrical=0.02, wake=0.05),
            uncertainty=0.1, version=1, updated_at=REFERENCE_UPDATED_AT,
        )


@pytest.fixture
async def db():
    try:
        from app.db.engine import ping as db_ping
        await db_ping()
    except Exception:
        pytest.skip("Postgres unreachable — run `docker compose up -d db`")
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def clean_db(db):
    for table in ("measurements", "ingest_runs", "site",
                  "power_curve_points", "turbine", "mast"):
        await db.execute(text(f"DELETE FROM {table}"))
    await db.commit()
    yield db
    for table in ("measurements", "ingest_runs", "site",
                  "power_curve_points", "turbine", "mast"):
        await db.execute(text(f"DELETE FROM {table}"))
    await db.commit()


@pytest.fixture
async def fake_client(clean_db):
    return FakeClient([PAGE1, PAGE2])


async def _run_row(db, ts: str):
    return (await db.execute(
        text("SELECT wind_speed_ms, unit, quality, version, timestamp_raw"
             " FROM measurements WHERE mast_id = 'TEST-M'"
             " AND timestamp = :t"),
        {"t": datetime.fromisoformat(ts.replace("Z", "+00:00"))},
    )).one()


async def _db_counts(db) -> tuple[int, dict]:
    rows = (await db.execute(
        text("SELECT quality, COUNT(*) FROM measurements"
             " GROUP BY quality ORDER BY quality"))).all()
    counts = {quality: n for quality, n in rows}
    total = sum(counts.values())
    return total, counts


async def test_backfill_is_idempotent(fake_client):
    first = await backfill.run_backfill(client=fake_client)
    assert first["status"] == "partial"   # page2: 2/3 suspect rows > 30 %
    assert first["inserted"] == 6 and first["updated"] == 1

    async with SessionLocal() as db:
        total, counts = await _db_counts(db)
        assert total == 6
        # the 02Z hour arrived missing (v1) and was revised to ok (v2) —
        # stored state is ok; the run journal still shows the defect source
        assert counts == {"ok": 4, "suspect": 2}   # no missing row stored at all

        wind_speed_ms, unit, quality, version, timestamp_raw = await _run_row(
            db, "2026-01-01T02:00:00Z")
        assert wind_speed_ms == pytest.approx(9.4)   # newest revision wins
        assert version == 2
        assert timestamp_raw == "2026-01-01T02:00:00+00:00"

        # whole-run replay: identical revisions → nothing inserted or updated
        replay = await backfill.run_backfill(client=fake_client)
        assert replay["inserted"] == 0 and replay["updated"] == 0

        run_rows = (await db.execute(text(
            "SELECT status, pages, inserted, updated, qc_missing,"
            " qc_suspect, qc_malformed, max_gap_hours"
            " FROM ingest_runs ORDER BY id"))).all()
        assert len(run_rows) == 2
        for status, pages, inserted, updated, missing, suspect, malformed, gap in run_rows:
            assert status == "partial"
            assert pages == 2
            assert (inserted, updated) in {(6, 1), (0, 0)}
            assert (missing, suspect, malformed) == (1, 2, 0)
            assert gap == 0                # contiguous frame


async def test_backfill_journals_reference_values(fake_client):
    await backfill.run_backfill(client=fake_client)
    async with SessionLocal() as db:
        turbine, curve = (await db.execute(
            text("SELECT t.cut_out_wind_speed_ms, COUNT(p.wind_speed_ms)"
                 " FROM turbine t LEFT JOIN power_curve_points p"
                 " ON p.turbine_id = t.id GROUP BY t.id"))).one()
        # fake curve has 3 points — proof the curve was refreshed, not empty
        assert turbine == 25.0 and curve == 3
        first = (await db.execute(text("SELECT * FROM site"))).mappings().first()
        assert first["availability_loss"] == 0.03
        assert first["wake_loss"] == 0.05


async def test_sync_uses_watermark_window_and_overlaps(fake_client):
    watermark = await backfill.run_backfill(client=fake_client)

    async with SessionLocal() as db:
        mark = (await db.execute(
            text("SELECT MAX(updated_at) FROM measurements"))).scalar_one()

    revision_client = FakeClient([
        [_api_row("2026-01-01T05:00:00Z", 21.0, version=2, minutes_after=10)]
    ])
    result = await sync.run_sync(client=revision_client)
    assert result["status"] == "ok"
    assert result["inserted"] == 0 and result["updated"] == 1

    # the 1 h overlap: window starts one hour before the watermark
    assert revision_client.calls[0]["updated_since"] == mark - timedelta(hours=1)

    async with SessionLocal() as db:
        wind_speed_ms, *_ = await _run_row(db, "2026-01-01T05:00:00Z")
        assert wind_speed_ms == pytest.approx(21.0)


async def test_sync_from_empty_db_behaves_like_backfill(fake_client):
    result = await sync.run_sync(client=fake_client)
    assert result["inserted"] == 6 and result["updated"] == 1
    assert fake_client.calls[0]["updated_since"] is None


async def test_locked_run_is_skipped(fake_client):
    from sqlalchemy import text as sql_text
    from app.db.engine import engine

    async with engine.connect() as conn:
        await conn.execute(
            sql_text("SELECT pg_advisory_lock(hashtext('windiq:ingest'))"))
        result = await sync.run_sync(client=fake_client)
        await conn.execute(
            sql_text("SELECT pg_advisory_unlock(hashtext('windiq:ingest'))"))
    assert result == {"status": "skipped", "reason": "run already active"}

    # no journal row for a skipped no-op run
    async with SessionLocal() as db:
        count = (await db.execute(
            text("SELECT COUNT(*) FROM ingest_runs"))).scalar_one()
        assert count == 0
