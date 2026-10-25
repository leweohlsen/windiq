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
    """Per-day energy + QC counts, so the SPA can color bars without a 2nd call.

    `suspect_hours`/`missing_hours` count defective rows of that day (missing
    = sentinel rows and malformed rows combined). Days without any ok hours
    appear with NULL energy instead of dropping out — the SPA draws them as a
    gap. `mean_wind_ms` is the ok-hour mean, weighted by per-mast day rows.
    """
    result = await session.execute(text("""
        WITH qc AS (
            SELECT (timestamp AT TIME ZONE 'UTC')::date AS day,
                   COUNT(*) FILTER (WHERE quality = 'suspect')                 AS suspect_hours,
                   COUNT(*) FILTER (WHERE quality IN ('missing', 'malformed')) AS missing_hours
              FROM measurements
             WHERE timestamp >= now() - make_interval(days => :days)
             GROUP BY 1
        ), ok AS (
            SELECT day,
                   SUM(energy_kwh) AS energy_kwh,
                   SUM(hours)      AS hours,
                   CASE WHEN SUM(hours) > 0
                        THEN SUM(mean_wind_ms * hours) / SUM(hours) END AS mean_wind_ms,
                   MAX(max_wind_ms) AS max_wind_ms
              FROM daily_energy
             WHERE day >= (now() - make_interval(days => :days))::date
             GROUP BY 1
        )
        SELECT o.day, o.energy_kwh, o.hours, o.mean_wind_ms, o.max_wind_ms,
               COALESCE(q.suspect_hours, 0) AS suspect_hours,
               COALESCE(q.missing_hours, 0) AS missing_hours
          FROM ok o
          LEFT JOIN qc q USING (day)
        UNION ALL
        SELECT q.day, NULL, NULL, NULL, NULL, q.suspect_hours, q.missing_hours
          FROM qc q
         WHERE NOT EXISTS (SELECT 1 FROM ok o WHERE o.day = q.day)
         ORDER BY day
    """), {"days": days})
    return [dict(row) for row in result.mappings().all()]


async def coverage(session: AsyncSession) -> dict[str, Any]:
    """Measurement range, expected/absent hours, QC row splits, max gap.

    Hour classes are counted by stored quality; `absent_hours` are the hours
    of the covered span with no row at all; `max_gap_hours` is the largest
    consecutive hole across the whole stored window.
    """
    result = await session.execute(text("""
        SELECT MIN(timestamp)  AS from_ts,
               MAX(timestamp)  AS to_ts,
               COUNT(*)        AS total_hours,
               COUNT(*) FILTER (WHERE quality = 'ok')        AS usable_hours,
               COUNT(*) FILTER (WHERE quality = 'suspect')   AS suspect_hours,
               COUNT(*) FILTER (WHERE quality = 'missing')   AS missing_hours,
               COUNT(*) FILTER (WHERE quality = 'malformed') AS malformed_hours,
               CASE WHEN MIN(timestamp) IS NULL THEN 0
                    ELSE EXTRACT(EPOCH FROM MAX(timestamp) - MIN(timestamp)) / 3600 + 1
               END                                            AS expected_hours,
               COALESCE((SELECT MAX(gap)
                           FROM (SELECT EXTRACT(EPOCH FROM timestamp
                                                 - LAG(timestamp) OVER (ORDER BY timestamp))
                                        / 3600.0 - 1 AS gap
                                   FROM measurements) AS gaps), 0)::int
                                                              AS max_gap_hours
          FROM measurements
    """))
    row = dict(result.mappings().one())
    row["expected_hours"] = int(row["expected_hours"])
    row["absent_hours"] = row["expected_hours"] - row["total_hours"]
    return row


async def wind_series(session: AsyncSession, hours: int = 48) -> list[dict]:
    """Trailing hourly speed + direction of ok rows, oldest first."""
    result = await session.execute(text("""
        SELECT timestamp, wind_speed_ms, wind_dir_deg
          FROM measurements
         WHERE quality = 'ok' AND wind_speed_ms IS NOT NULL
         ORDER BY timestamp DESC
         LIMIT :hours
    """), {"hours": hours})
    return [dict(row) for row in reversed(result.mappings().all())]


# 16 compass sectors spanning 22.5° each, centered on the named direction
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")

ROSE_WINDOW_DAYS = 30


async def wind_rose(session: AsyncSession, days: int = ROSE_WINDOW_DAYS) -> list[dict]:
    """16-sector frequency + mean-speed histogram of the last `days` ok hours.

    Sector membership is `ROUND(deg / 22.5) % 16`, i.e. sector i = [(i−0.5)·22.5°,
    (i+0.5)·22.5°) and 360° wraps back to N. All 16 sectors are always present
    (0 frequency when empty) so the SPA can draw a closed rose without
    re-indexing.
    """
    result = await session.execute(text("""
        SELECT ROUND((wind_dir_deg % 360) / 22.5)::int % 16 AS sector,
               COUNT(*)            AS frequency,
               AVG(wind_speed_ms)  AS mean_speed_ms
          FROM measurements
         WHERE quality = 'ok'
           AND wind_speed_ms IS NOT NULL
           AND timestamp >= now() - make_interval(days => :days)
         GROUP BY 1
    """), {"days": days})
    counted = {r["sector"]: dict(r) for r in result.mappings().all()}
    return [
        {
            "direction": COMPASS[i],
            "degrees": i * 360 // len(COMPASS),
            "frequency": counted[i]["frequency"] if i in counted else 0,
            "mean_speed_ms": counted[i]["mean_speed_ms"] if i in counted else None,
        }
        for i in range(len(COMPASS))
    ]


# Startup-backfill gate: history reach + forward freshness (plan finding 2)
WINDOW_MIN_HISTORY_DAYS = 350
WINDOW_FRESH_HOURS = 48


async def ingest_window_covered(session: AsyncSession) -> bool:
    """True when the store already reflects a complete ingest.

    Cheap two-point check, not a full audit: history reaches back (the API
    slides a 1-year window, so ≥ 350 d means the backfill ran to the bottom)
    and the newest revision arrived within the last 48 h. A partial or
    crashed first backfill fails at least one of the two and then re-runs.
    """
    result = await session.execute(text("""
        SELECT COALESCE(
                   (SELECT MIN(timestamp) FROM measurements)
                   < now() - make_interval(days => :min_history_days), false)
               AND COALESCE(
                   (SELECT MAX(updated_at) FROM measurements)
                   >= now() - make_interval(hours => :fresh_hours), false)
    """), {
        "min_history_days": WINDOW_MIN_HISTORY_DAYS,
        "fresh_hours": WINDOW_FRESH_HOURS,
    })
    return bool(result.scalar())


async def ingest_runs_recent(session: AsyncSession, limit: int = 10) -> list[dict]:
    """Last N ingest runs, newest first (dashboard history table)."""
    result = await session.execute(text("""
        SELECT id, started_at, finished_at, status, pages, inserted, updated,
               frame_from, frame_to, qc_missing, qc_suspect, qc_malformed,
               max_gap_hours, detail
          FROM ingest_runs ORDER BY id DESC LIMIT :limit
    """), {"limit": limit})
    return [dict(row) for row in result.mappings().all()]


async def ingest_health(session: AsyncSession) -> dict[str, Any]:
    """Last ingest run + measurement staleness, feeding /api/health."""
    last_run = (await session.execute(text("""
        SELECT id, started_at, finished_at, status, pages, inserted, updated,
               frame_from, frame_to, qc_missing, qc_suspect, qc_malformed,
               max_gap_hours, detail
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
