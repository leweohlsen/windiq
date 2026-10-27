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
    _api_row("2026-01-01T02:00:00Z", None),    # null → defect (missing)
    _api_row("2026-01-01T03:00:00Z", -0.5),    # drift → defect (negative)
]
PAGE2 = [
    _api_row("2026-01-01T02:00:00+00:00", 9.4, version=2, minutes_after=90),
    _api_row("2026-01-01T04:00:00Z", 30.0),    # > cut-out + margin → defect
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
        text("SELECT wind_speed_ms, qc_note, version, timestamp_raw"
             " FROM measurements WHERE mast_id = 'TEST-M'"
             " AND timestamp = :t"),
        {"t": datetime.fromisoformat(ts.replace("Z", "+00:00"))},
    )).one()


async def _db_counts(db) -> tuple[int, dict]:
    row = (await db.execute(
        text("SELECT COUNT(*) FILTER (WHERE qc_note IS NULL) AS measured,"
             " COUNT(*) FILTER (WHERE qc_note IS NOT NULL) AS interpolated,"
             " COUNT(*) FILTER (WHERE wind_speed_ms IS NULL) AS invalid"
             " FROM measurements"))).mappings().one()
    total = row["measured"] + row["interpolated"]
    return total, row


async def test_backfill_is_idempotent(fake_client):
    first = await backfill.run_backfill(client=fake_client)
    assert first["status"] == "partial"   # page2: 1/3 defected > 30 %
    assert first["inserted"] == 4 and first["updated"] == 0
    assert first["interpolated"] == 3     # 02Z missing · 03Z negative · 04Z cut-out

    async with SessionLocal() as db:
        total, counts = await _db_counts(db)
        assert total == 6                       # 00Z…05Z, every hour present
        assert counts["measured"] == 4
        assert counts["interpolated"] == 2      # 03Z + 04Z recharged by the fill
        assert counts["invalid"] == 0           # the store only holds values

        # the 02Z hour arrived missing (v1) and was revised to ok (v2) —
        # stored state is ok; the defect payload never supersedes the revision
        wind_speed_ms, qc_note, version, timestamp_raw = await _run_row(
            db, "2026-01-01T02:00:00Z")
        assert wind_speed_ms == pytest.approx(9.4)   # newest revision wins
        assert qc_note is None and version == 2
        assert timestamp_raw == "2026-01-01T02:00:00+00:00"

        # the rejected hours 03Z/04Z are linearly interpolated 02Z → 05Z
        v03 = await _run_row(db, "2026-01-01T03:00:00Z")
        v04 = await _run_row(db, "2026-01-01T04:00:00Z")
        assert v03[0] == pytest.approx(9.4 + (20.0 - 9.4) / 3)
        assert v04[0] == pytest.approx(9.4 + 2 * (20.0 - 9.4) / 3)
        assert v03[1] == "negativer Messwert"
        assert v04[1] == "Messwert über Cut-Out"

        # whole-run replay: identical revisions → nothing inserted or updated
        replay = await backfill.run_backfill(client=fake_client)
        assert replay["inserted"] == 0 and replay["updated"] == 0

        run_rows = (await db.execute(text(
            "SELECT status, pages, inserted, updated, interpolated,"
            " max_gap_hours FROM ingest_runs ORDER BY id"))).all()
        assert len(run_rows) == 2
        for status, pages, inserted, updated, interpolated, gap in run_rows:
            assert status == "partial"
            assert pages == 2
            assert (inserted, updated) in {(4, 0), (0, 0)}
            assert interpolated == 3
            assert gap == 0                # contiguous frame after the fill


async def test_run_refreshes_energy_matview_once(fake_client, monkeypatch):
    """_run refreshes the matview exactly once, after commit — an upserted
    hour is visible in hourly_energy without any manual refresh."""
    import app.db.repo as repo_mod

    real_refresh = repo_mod.refresh_energy_matview
    refresh_sessions: list = []

    async def spy(session, **kwargs):
        refresh_sessions.append(session)
        await real_refresh(session, **kwargs)

    monkeypatch.setattr(backfill.repo, "refresh_energy_matview", spy)

    result = await backfill.run_backfill(client=fake_client)
    assert result["inserted"] == 4
    assert len(refresh_sessions) == 1        # one refresh per run

    async with SessionLocal() as db:
        matview_rows, stored_rows = (await db.execute(text(
            "SELECT (SELECT COUNT(*) FROM hourly_energy),"
            "       (SELECT COUNT(*) FROM measurements)"
        ))).one()
    assert matview_rows == stored_rows == 6   # fresh rows are already visible


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
    assert result["inserted"] == 4 and result["updated"] == 0
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
