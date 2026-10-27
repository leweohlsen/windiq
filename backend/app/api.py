"""Dashboard API — plan phase 3: metrics, daily/wind series, run history, trigger.

All endpoints are plain JSON (pydantic response models), no auth — the SPA
sits same-origin behind the nginx proxy. The POST endpoint only produces a
taskiq message; progress is read from `ingest_runs` via GET, never polled.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.db import repo
from app.db.engine import SessionLocal
from app.db.models import Mast, PowerCurvePoint, Site, Turbine
from app.ingest.common import new_run_id
from app.worker import periodic_sync, run_backfill

router = APIRouter()
log = logging.getLogger(__name__)

DAYS_CAP = 365
WIND_HOURS_CAP = 168
RUNS_LIMIT_CAP = 50


def revenue_chain(
    aep_gross_kwh: float,
    *,
    availability_loss: float,
    electrical_loss: float,
    wake_loss: float,
    uncertainty: float,
) -> dict[str, float]:
    """AEP gross → net → P50 → P90 (case-study formulas)."""
    net = (
        aep_gross_kwh
        * (1 - availability_loss)
        * (1 - electrical_loss)
        * (1 - wake_loss)
    )
    return {"net_kwh": net, "p50_kwh": net, "p90_kwh": net * (1 - 1.282 * uncertainty)}


# --- response models (the SPA contract; the frontend client is generated
# from this spec — keep every field always-serialized: no `= None` defaults,
# nullable via `| None`, so the spec marks fields required) ---


class IngestRunOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    pages: int
    inserted: int
    updated: int
    frame_from: datetime | None
    frame_to: datetime | None
    qc_missing: int
    qc_suspect: int
    qc_malformed: int
    max_gap_hours: int | None
    detail: str | None


class AepOut(BaseModel):
    gross_kwh: float
    net_kwh: float | None
    p50_kwh: float | None
    p90_kwh: float | None
    window_start: datetime | None
    window_end: datetime | None
    usable_hours: int


class CoverageOut(BaseModel):
    from_ts: datetime | None
    to_ts: datetime | None
    total_hours: int
    usable_hours: int
    suspect_hours: int
    missing_hours: int
    malformed_hours: int
    expected_hours: int
    absent_hours: int
    max_gap_hours: int | None


class SiteOut(BaseModel):
    name: str
    shear_exponent: float
    availability_loss: float
    electrical_loss: float
    wake_loss: float
    uncertainty: float


class TurbineOut(BaseModel):
    name: str
    rated_power_kw: float
    hub_height_m: float
    rotor_diameter_m: float


class PowerCurvePointOut(BaseModel):
    wind_speed_ms: float
    power_kw: float


class TurbineDetailOut(BaseModel):
    name: str
    rated_power_kw: float
    hub_height_m: float
    rotor_diameter_m: float
    cut_in_wind_speed_ms: float
    cut_out_wind_speed_ms: float
    power_curve: list[PowerCurvePointOut]


class MastOut(BaseModel):
    name: str
    measurement_height_m: float


class StalenessOut(BaseModel):
    last_run: IngestRunOut | None
    data_age_seconds: int | None


class MetricsOut(BaseModel):
    aep: AepOut
    coverage: CoverageOut
    site: SiteOut | None
    turbine: TurbineOut | None
    mast: MastOut | None
    staleness: StalenessOut


class DailyPointOut(BaseModel):
    day: date
    energy_kwh: float | None   # NULL → day without ok hours (gap)
    hours: int | None
    mean_wind_ms: float | None
    max_wind_ms: float | None
    suspect_hours: int
    missing_hours: int


class WindPointOut(BaseModel):
    timestamp: datetime
    wind_speed_ms: float
    wind_dir_deg: int


class RoseSectorOut(BaseModel):
    direction: str
    degrees: int
    frequency: int
    mean_speed_ms: float | None


class WindOut(BaseModel):
    hours: int
    series: list[WindPointOut]
    rose: list[RoseSectorOut]


class QueuedOut(BaseModel):
    queued: bool


# --- endpoints ---


@router.get("/api/metrics", operation_id="metrics")
async def metrics() -> MetricsOut:
    """Dashboard header: revenue chain, coverage, metadata and staleness."""
    async with SessionLocal() as s:
        aep = await repo.aep_trailing_12m(s)
        coverage = await repo.coverage(s)
        staleness = await repo.ingest_health(s)
        site = (await s.execute(_one(Site))).scalar_one_or_none()
        turbine = (await s.execute(_one(Turbine))).scalar_one_or_none()
        mast = (await s.execute(_one(Mast))).scalar_one_or_none()

    chain: dict[str, Any] = (
        revenue_chain(
            aep["aep_gross_kwh"],
            availability_loss=site.availability_loss,
            electrical_loss=site.electrical_loss,
            wake_loss=site.wake_loss,
            uncertainty=site.uncertainty,
        )
        if site
        else {"net_kwh": None, "p50_kwh": None, "p90_kwh": None}
    )

    return {
        "aep": {
            "gross_kwh": aep["aep_gross_kwh"],
            **chain,
            "window_start": aep["window_start"],
            "window_end": aep["window_end"],
            "usable_hours": aep["usable_hours"],
        },
        "coverage": coverage,
        "site": None if site is None else {
            "name": site.name,
            "shear_exponent": site.shear_exponent,
            "availability_loss": site.availability_loss,
            "electrical_loss": site.electrical_loss,
            "wake_loss": site.wake_loss,
            "uncertainty": site.uncertainty,
        },
        "turbine": None if turbine is None else {
            "name": turbine.name,
            "rated_power_kw": turbine.rated_power_kw,
            "hub_height_m": turbine.hub_height_m,
            "rotor_diameter_m": turbine.rotor_diameter_m,
        },
        "mast": None if mast is None else {
            "name": mast.name,
            "measurement_height_m": mast.measurement_height_m,
        },
        "staleness": {
            "last_run": staleness["last_run"],
            "data_age_seconds": _seconds(staleness["data_age"]),
        },
    }


def _one(model):
    return select(model).limit(1)


@router.get("/api/turbine", operation_id="turbine")
async def turbine() -> TurbineDetailOut | None:
    """Reference turbine specs plus the full power curve (1 m/s steps)."""
    async with SessionLocal() as s:
        turbine = (await s.execute(_one(Turbine))).scalar_one_or_none()
        if turbine is None:
            return None
        curve = (
            await s.execute(
                select(PowerCurvePoint.wind_speed_ms, PowerCurvePoint.power_kw)
                .where(PowerCurvePoint.turbine_id == turbine.id)
                .order_by(PowerCurvePoint.wind_speed_ms)
            )
        ).all()
    return TurbineDetailOut(
        name=turbine.name,
        rated_power_kw=turbine.rated_power_kw,
        hub_height_m=turbine.hub_height_m,
        rotor_diameter_m=turbine.rotor_diameter_m,
        cut_in_wind_speed_ms=turbine.cut_in_wind_speed_ms,
        cut_out_wind_speed_ms=turbine.cut_out_wind_speed_ms,
        power_curve=[PowerCurvePointOut(wind_speed_ms=ws, power_kw=kw) for ws, kw in curve],
    )


@router.get("/api/daily", operation_id="daily")
async def daily(days: int = 90) -> list[DailyPointOut]:
    """Daily energy series for the chart; `days` capped at 365."""
    async with SessionLocal() as s:
        return await repo.daily_series(s, days=min(max(days, 1), DAYS_CAP))


@router.get("/api/wind", operation_id="wind")
async def wind(hours: int = 48) -> WindOut:
    """Hourly speed+direction series and the 30-day 16-sector wind rose."""
    capped = min(max(hours, 1), WIND_HOURS_CAP)
    async with SessionLocal() as s:
        series = await repo.wind_series(s, hours=capped)
        rose = await repo.wind_rose(s)
    return {"hours": capped, "series": series, "rose": rose}


@router.get("/api/ingest/runs", operation_id="ingest_runs")
async def ingest_runs(limit: int = 10) -> list[IngestRunOut]:
    """Last N ingest runs, newest first."""
    async with SessionLocal() as s:
        return await repo.ingest_runs_recent(s, limit=min(max(limit, 1), RUNS_LIMIT_CAP))


@router.post("/api/ingest/run", operation_id="queue_ingest")
async def queue_ingest(mode: Literal["sync", "backfill"] = "sync") -> QueuedOut:
    """Queue an ingest run; returns immediately, progress shows in ingest_runs.

    The run id travels with the task message so the api line and the worker
    lines of one cycle share it (phase 5: a run id per ingest cycle).
    """
    run_id = new_run_id()
    log.info("ingest queued run=%s mode=%s", run_id, mode)
    task = run_backfill if mode == "backfill" else periodic_sync
    await task.kiq(run_id=run_id)
    return {"queued": True}


def _seconds(age: Any) -> int | None:
    return round(age.total_seconds()) if isinstance(age, timedelta) else age
