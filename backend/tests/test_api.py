"""API-level tests: revenue math (pure), dashboard endpoints (Postgres-backed),
and the ingest trigger (broker seam stubbed — the API only produces tasks).

Endpoint tests call the route functions directly and must commit the seeded
session first — each endpoint opens its own SessionLocal session.
"""
from datetime import timedelta

import pytest

import app.api as api_mod
import app.main as main_mod
from app.api import revenue_chain
from app.db import repo

HOUR = timedelta(hours=1)


def test_chain_applies_losses_then_uncertainty():
    chain = revenue_chain(
        1_000_000.0,
        availability_loss=0.03,
        electrical_loss=0.02,
        wake_loss=0.05,
        uncertainty=0.10,
    )
    expected_net = 1_000_000.0 * 0.97 * 0.98 * 0.95
    assert chain["net_kwh"] == pytest.approx(expected_net)
    assert chain["p50_kwh"] == pytest.approx(expected_net)
    assert chain["p90_kwh"] == pytest.approx(expected_net * (1 - 1.282 * 0.10))


def test_zero_losses_keep_gross():
    chain = revenue_chain(500.0, availability_loss=0.0, electrical_loss=0.0,
                          wake_loss=0.0, uncertainty=0.0)
    assert chain["p50_kwh"] == pytest.approx(500.0)
    assert chain["p90_kwh"] == pytest.approx(500.0)


def test_p90_never_exceeds_p50():
    chain = revenue_chain(9_000_000.0, availability_loss=0.1,
                          electrical_loss=0.1, wake_loss=0.1, uncertainty=0.15)
    assert chain["p90_kwh"] < chain["p50_kwh"]


class StubTask:
    """Stands in for a taskiq task; records kiq() sends on the broker seam."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.sent: list[dict] = []

    async def kiq(self, **kwargs) -> None:
        self.sent.append(kwargs)


async def test_queue_ingest_defaults_to_sync(monkeypatch):
    sync_task, backfill_task = StubTask("periodic_sync"), StubTask("run_backfill")
    monkeypatch.setattr(api_mod, "periodic_sync", sync_task)
    monkeypatch.setattr(api_mod, "run_backfill", backfill_task)

    assert await api_mod.queue_ingest() == {"queued": True}
    assert list(sync_task.sent[0]) == ["run_id"]         # run id travels with the task
    assert backfill_task.sent == []


async def test_queue_ingest_backfill_mode(monkeypatch):
    sync_task, backfill_task = StubTask("periodic_sync"), StubTask("run_backfill")
    monkeypatch.setattr(api_mod, "periodic_sync", sync_task)
    monkeypatch.setattr(api_mod, "run_backfill", backfill_task)

    assert await api_mod.queue_ingest("backfill") == {"queued": True}
    assert "run_id" in backfill_task.sent[0]
    assert sync_task.sent == []


async def test_daily_endpoint_daily_energy(db, clean, reference, measurement_row, hour):
    daily = await api_mod.daily(30)
    assert len(daily) == 31                    # every day is present
    assert all(p["energy_kwh"] is None for p in daily)   # empty store → gaps

    # 12:00 anchor — hour+1 crossing UTC midnight would split into two days
    # and flake for runs between 21:00 and 24:00 UTC (see test_db.py sibling)
    t0 = hour.replace(hour=12)
    await repo.upsert_measurements(db, [
        measurement_row(t0, 8.0),
        measurement_row(t0 + HOUR, 6.0, qc_note="kein Messwert geliefert"),
    ])
    await db.commit()
    daily = await api_mod.daily(30)
    today = next(p for p in daily if p["day"] == t0.date())
    assert today["energy_kwh"] is not None
    assert today["hours"] == 2


async def test_daily_endpoint_caps_days(db, clean, reference, measurement_row):
    # clamped to a 1-day window; the day list length tracks the window
    assert len(await api_mod.daily(0)) == 2
    assert len(await api_mod.daily(-5)) == 2


async def test_metrics_endpoint_chain_and_staleness(
    db, clean, reference, measurement_row, hour
):
    await repo.upsert_measurements(db, [measurement_row(hour, 10.0)])
    await db.commit()
    payload = await api_mod.metrics()

    # α = 0.2 → hub speed 10·(140/100)^0.2 ≈ 10.6964 → curve slope 180 kW/(m/s)
    hub = 10.0 * (140.0 / 100.0) ** 0.2
    expected_gross = 1800.0 + (3600.0 - 1800.0) * (hub - 10.0) / 10.0
    chain = revenue_chain(
        expected_gross,
        availability_loss=0.03, electrical_loss=0.02, wake_loss=0.05, uncertainty=0.1,
    )
    assert payload["aep"]["gross_kwh"] == pytest.approx(expected_gross)
    assert payload["aep"]["p90_kwh"] == pytest.approx(chain["p90_kwh"])
    assert payload["site"]["shear_exponent"] == 0.2
    assert payload["turbine"]["hub_height_m"] == 140.0
    assert payload["mast"]["measurement_height_m"] == 100.0
    assert payload["staleness"]["last_run"] is None
    assert payload["coverage"]["absent_hours"] == 0
    assert payload["coverage"]["interpolated_hours"] == 0


async def test_turbine_endpoint_specs_and_curve(db, clean, reference):
    await db.commit()      # reference rows are seeded uncommitted (see metrics test)
    payload = await api_mod.turbine()
    assert payload.name == "Test turbine"
    assert payload.rated_power_kw == 3600.0
    assert payload.hub_height_m == 140.0
    assert payload.rotor_diameter_m == 136.0
    assert payload.cut_in_wind_speed_ms == 3.0
    assert payload.cut_out_wind_speed_ms == 25.0
    assert [(p.wind_speed_ms, p.power_kw) for p in payload.power_curve] == [
        (0.0, 0.0), (10.0, 1800.0), (20.0, 3600.0),
    ]


async def test_turbine_endpoint_none_without_turbine(db, clean):
    assert await api_mod.turbine() is None


async def test_wind_endpoint_series_and_rose(db, clean, reference, measurement_row, hour):
    await repo.upsert_measurements(db, [
        measurement_row(hour, 5.0, wind_dir=10),
        measurement_row(hour - HOUR, 6.0, wind_dir=200, qc_note="negativer Messwert"),
        measurement_row(hour - 2 * HOUR, 4.0, qc_note="kein Messwert geliefert"),
    ])
    await db.commit()
    payload = await api_mod.wind(2)
    assert payload["days"] == 2
    assert payload["resolution"] == "hour"
    assert len(payload["series"]) == 49      # every hour of the 2-day window
    by_ts = {p["timestamp"]: p for p in payload["series"]}
    assert by_ts[hour]["interpolated_hours"] == 0
    assert by_ts[hour]["qc_note"] is None
    assert by_ts[hour - HOUR]["interpolated_hours"] == 1
    assert by_ts[hour - HOUR]["qc_note"] == "negativer Messwert"
    assert by_ts[hour - 2 * HOUR]["interpolated_hours"] == 1
    assert by_ts[hour - 2 * HOUR]["wind_speed_raw"] == "4.0"   # rejected original
    assert by_ts[hour - 3 * HOUR]["mean_wind_ms"] is None   # absent hour: gap
    assert len(payload["rose"]) == 16               # all sectors, never filtered
    north = next(s for s in payload["rose"] if s["direction"] == "N")
    assert north["frequency"] == 1
    assert north["mean_speed_ms"] == pytest.approx(5.0)

    # days is clamped to [1, 365]
    assert (await api_mod.wind(0))["days"] == 1
    assert (await api_mod.wind(9999))["days"] == 365


async def test_runs_endpoint_newest_first_and_limit_cap(db, clean, hour):
    for i in range(3):
        await repo.record_ingest_run(
            db, started_at=hour, finished_at=hour, status="ok" if i else "error",
            pages=i, inserted=i, updated=0,
        )
    await db.commit()

    runs = await api_mod.ingest_runs(2)
    assert [r["pages"] for r in runs] == [2, 1]
    assert runs[0]["status"] == "ok"

    # 50 further runs → limit={100} is clamped to 50 server-side
    for _ in range(50):
        await repo.record_ingest_run(
            db, started_at=hour, finished_at=hour, status="ok", pages=0,
            inserted=0, updated=0,
        )
    await db.commit()
    assert len(await api_mod.ingest_runs(100)) == 50


async def test_health_is_200_when_database_is_up(db):
    assert (await main_mod.health()).status_code == 200


async def test_health_is_503_when_database_is_down(monkeypatch):
    async def unreachable() -> bool:
        return False

    monkeypatch.setattr(main_mod, "db_ping", unreachable)
    assert (await main_mod.health()).status_code == 503
