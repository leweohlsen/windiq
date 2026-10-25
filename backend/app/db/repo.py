from datetime import datetime
from typing import Any, Iterable, Optional, TypedDict

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import IngestRun, Mast, Measurement, PowerCurvePoint, Site, Turbine


class MeasurementRow(TypedDict):
    """Shape of one hourly row fed to `upsert_measurements`."""

    mast_id: str
    timestamp: datetime
    timestamp_raw: str
    wind_speed_ms: Optional[float]
    unit: str
    wind_speed_raw: str
    wind_dir_deg: int
    quality: str
    version: int
    updated_at: datetime


def _upsert_stmt(model, values):
    """INSERT … ON CONFLICT DO UPDATE guarded by `updated_at`.

    Stored rows are only touched when the incoming revision is newer, so a
    replayed backfill or a lagging sync page can never overwrite newer data.
    `fetched_at` always keeps its DB default (it tracks *our* reads).
    """
    stmt = pg_insert(model).values(values)
    kwargs = {"where": model.updated_at < stmt.excluded.updated_at} \
        if hasattr(model, "updated_at") else {}
    return stmt.on_conflict_do_update(
        index_elements=[c.name for c in model.__table__.primary_key.columns],
        set_={c.name: stmt.excluded[c.name]
              for c in model.__table__.columns if c.name != "fetched_at"},
        **kwargs,
    )


async def upsert_measurements(
    session: AsyncSession, rows: Iterable[MeasurementRow], batch_size: int = 1000
) -> tuple[int, int]:
    """Idempotent batched upsert; latest revision wins. Returns (inserted, updated).

    Rows whose stored `updated_at` is not older than the incoming one are
    skipped entirely — they count as neither inserted nor updated. Rows
    colliding within one batch (the same UTC hour reported twice) are reduced
    to their newest revision first, since Postgres forbids touching a conflict
    row twice in one statement.
    """
    keyed: dict[tuple[str, datetime], MeasurementRow] = {}
    for row in rows:
        key = (row["mast_id"], row["timestamp"])
        previous = keyed.get(key)
        if previous is None or row["updated_at"] >= previous["updated_at"]:
            keyed[key] = row
    rows = list(keyed.values())
    inserted = updated = 0
    for i in range(0, len(rows), batch_size):
        stmt = _upsert_stmt(Measurement, rows[i:i + batch_size])
        # xmax = 0 marks rows freshly inserted (a row updated here has a nonzero
        # xmax); rows skipped by the guard produce no output row at all.
        stmt = stmt.returning(text("(xmax = 0) AS fresh"))
        result = await session.execute(stmt)
        verdicts = [r[0] for r in result.fetchall()]
        inserted += sum(1 for v in verdicts if v)
        updated += sum(1 for v in verdicts if not v)
    return inserted, updated


async def upsert_mast(session: AsyncSession, values: dict[str, Any]) -> bool:
    """Update the mast row (static reference data, no version guard)."""
    return (await session.execute(_upsert_stmt(Mast, values))).rowcount > 0


async def upsert_turbine(
    session: AsyncSession, values: dict[str, Any], power_curve: list[tuple[float, float]]
) -> bool:
    """Update the turbine singleton; True → turbine row (and curve) changed."""
    result = await session.execute(_upsert_stmt(Turbine, values))
    changed = result.rowcount > 0
    if changed:
        await session.execute(
            PowerCurvePoint.__table__.delete()
            .where(PowerCurvePoint.turbine_id == values["id"])
        )
        session.add_all(
            PowerCurvePoint(turbine_id=values["id"], wind_speed_ms=ws, power_kw=kw)
            for ws, kw in power_curve
        )
    return changed


async def upsert_site(session: AsyncSession, values: dict[str, Any]) -> bool:
    """Update the site singleton; True when `updated_at` advanced."""
    return (await session.execute(_upsert_stmt(Site, values))).rowcount > 0


def _latest_measurement_stmt():
    return Measurement.__table__.select().order_by(
        Measurement.timestamp.desc()
    ).limit(1)


async def latest_measurement(session: AsyncSession) -> Optional[Any]:
    result = await session.execute(_latest_measurement_stmt())
    return result.mappings().first()


async def aep_trailing_12m(session: AsyncSession) -> dict[str, Any]:
    """AEP gross (kWh) and usable hours over the trailing 12 months."""
    result = await session.execute(text("""
        SELECT COALESCE(SUM(energy_kwh), 0)   AS aep_gross_kwh,
               COUNT(*)                       AS usable_hours,
               MIN(timestamp)                 AS window_start,
               MAX(timestamp)                 AS window_end
          FROM hourly_energy
         WHERE timestamp >= now() - interval '12 months'
    """))
    return dict(result.mappings().one())


async def daily_series(session: AsyncSession, days: int = 90) -> list[dict]:
    result = await session.execute(text("""
        SELECT day, energy_kwh, hours, mean_wind_ms, max_wind_ms
          FROM daily_energy
         WHERE day >= (now() - make_interval(days => :days))::date
         ORDER BY day
    """), {"days": days})
    return [dict(row) for row in result.mappings().all()]


async def coverage(session: AsyncSession) -> dict[str, Any]:
    """Measurement range, expected hours, present rows, and QC splits."""
    result = await session.execute(text("""
        SELECT MIN(timestamp)  AS from_ts,
               MAX(timestamp)  AS to_ts,
               COUNT(*)        AS total_hours,
               COUNT(*) FILTER (WHERE quality = 'ok')                AS usable_hours,
               COUNT(*) FILTER (WHERE quality = 'suspect')           AS suspect_hours,
               COUNT(*) FILTER (WHERE quality IN ('missing','malformed')) AS bad_hours,
               CASE WHEN MIN(timestamp) IS NULL THEN 0
                    ELSE EXTRACT(EPOCH FROM MAX(timestamp) - MIN(timestamp)) / 3600 + 1
               END                                                    AS expected_hours
          FROM measurements
    """))
    row = dict(result.mappings().one())
    row["expected_hours"] = int(row["expected_hours"])
    row["missing_hours"] = row["expected_hours"] - row["total_hours"]
    return row


async def ingest_health(session: AsyncSession) -> dict[str, Any]:
    """Last ingest run + measurement staleness, feeding /api/health."""
    last_run = (await session.execute(text("""
        SELECT id, started_at, finished_at, status, pages, inserted, updated, detail
          FROM ingest_runs ORDER BY id DESC LIMIT 1
    """))).mappings().first()
    staleness = (await session.execute(text("""
        SELECT MAX(updated_at) AS last_data_update, now() - MAX(updated_at) AS data_age
          FROM measurements
    """))).mappings().one()
    return {
        "last_run": dict(last_run) if last_run else None,
        "last_data_update": staleness["last_data_update"],
        "data_age": staleness["data_age"],
    }


async def record_ingest_run(
    session: AsyncSession, *, started_at: datetime, finished_at: datetime,
    status: str, pages: int, inserted: int, updated: int,
    frame_from: Optional[datetime] = None, frame_to: Optional[datetime] = None,
    qc_missing: int = 0, qc_suspect: int = 0, qc_malformed: int = 0,
    max_gap_hours: Optional[int] = None, detail: Optional[str] = None,
) -> IngestRun:
    run = IngestRun(
        started_at=started_at, finished_at=finished_at, status=status,
        pages=pages, inserted=inserted, updated=updated,
        frame_from=frame_from, frame_to=frame_to,
        qc_missing=qc_missing, qc_suspect=qc_suspect,
        qc_malformed=qc_malformed, max_gap_hours=max_gap_hours,
        detail=detail,
    )
    session.add(run)
    await session.flush()
    return run
