import json
from datetime import datetime
from typing import Any, Iterable, Optional, TypedDict

from sqlalchemy import and_, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import IngestRun, Mast, Measurement, PowerCurvePoint, Site, Turbine


class MeasurementRow(TypedDict):
    """Shape of one hourly row fed to `upsert_measurements`."""

    mast_id: str
    timestamp: datetime
    timestamp_raw: str
    wind_speed_ms: float
    wind_speed_raw: str
    wind_dir_deg: int
    qc_note: Optional[str]
    version: int
    updated_at: datetime


def _upsert_stmt(model, values, *, real_wins: bool = False):
    """INSERT … ON CONFLICT DO UPDATE guarded by (updated_at, version).

    Stored rows are only touched when the incoming revision is newer —
    compared lexicographically, so a same-timestamp republish with a higher
    version is not dropped and a replayed backfill or lagging sync page can
    never overwrite newer data. Every guarded model pairs `updated_at` with
    `version`. `fetched_at` always keeps its DB default (it tracks *our*
    reads).

    `real_wins` relaxes the guard for measurements: an interpolated row is
    our own synthesis, so *any* real API revision replaces it — even one
    replayed with an older stamp that can no longer pass the guard itself.
    """
    stmt = pg_insert(model).values(values)
    guard = or_(
        model.updated_at < stmt.excluded.updated_at,
        and_(model.updated_at == stmt.excluded.updated_at,
             model.version < stmt.excluded.version),
    ) if hasattr(model, "updated_at") else None
    if real_wins:
        guard = or_(guard, model.__table__.c.qc_note.is_not(None))
    kwargs = {"where": guard} if guard is not None else {}
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

    Rows whose stored (updated_at, version) is not older than the incoming
    one are skipped entirely — they count as neither inserted nor updated.
    Rows colliding within one batch (the same UTC hour reported twice) are
    reduced to their newest revision first, since Postgres forbids touching
    a conflict row twice in one statement.
    """
    keyed: dict[tuple[str, datetime], MeasurementRow] = {}
    for row in rows:
        key = (row["mast_id"], row["timestamp"])
        previous = keyed.get(key)
        if previous is None or (row["updated_at"], row["version"]) >= \
                (previous["updated_at"], previous["version"]):
            keyed[key] = row
    rows = list(keyed.values())
    inserted = updated = 0
    for i in range(0, len(rows), batch_size):
        stmt = _upsert_stmt(Measurement, rows[i:i + batch_size], real_wins=True)
        # xmax = 0 marks rows freshly inserted (a row updated here has a nonzero
        # xmax); rows skipped by the guard produce no output row at all.
        stmt = stmt.returning(text("(xmax = 0) AS fresh"))
        result = await session.execute(stmt)
        verdicts = [r[0] for r in result.fetchall()]
        inserted += sum(1 for v in verdicts if v)
        updated += sum(1 for v in verdicts if not v)
    return inserted, updated


async def interpolate_gaps(
    session: AsyncSession, defects: list[dict[str, Any]], *, mast_id: str
) -> None:
    """Fill hours without a usable value by linear interpolation — idempotently.

    `defects` are this run's rejected hours (one dict per defected
    `NormalizedHour`: ts, note, updated_at, version, wind_speed_raw,
    timestamp_raw, wind_dir). The whole stored range is walked every ingest
    in three statements, so the fill self-heals without any state. All three
    write interpolated rows only (never anchors), so each sees the same
    real-row anchor set — with it they decompose the old single-statement
    pass statement by statement:

    1. recompute stored interpolated rows — their anchors may have moved
       this run; note and stamps stay, unchanged rows are no-ops via the
       conflict guard. Runs first, on the pre-ingest state, so it
       re-anchors exactly the rows interpolated before this run.
    2. fill never-delivered hours — every hour of the stored bounds with
       neither a stored row nor a defect in this payload becomes a
       "Stunde nicht geliefert" row that inherits the bounding lead
       anchor's revision (the sync watermark never runs ahead of the API)
       and the lag anchor's wind direction.
    3. write this run's defect hours unless a stored **real** revision
       (`qc_note IS NULL`) already supersedes the defect's
       (updated_at, version). The row then carries the defect revision's
       stamp — still watermark-safe — plus its rejected raws as audit.

    Anchors are real rows (`qc_note IS NULL`) only, so interpolations never
    anchor on interpolations. `upsert_measurements` lets any real revision
    replace an interpolated row afterwards, so real data always wins
    eventually.
    """
    await session.execute(text("""
        WITH defects AS (
            SELECT d.ts FROM jsonb_to_recordset(CAST(:defects AS jsonb))
                 AS d(ts timestamptz)
        ), targets AS (
            SELECT timestamp, qc_note, updated_at, version,
                   wind_speed_raw, timestamp_raw, wind_dir_deg
              FROM measurements
             WHERE qc_note IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM defects d WHERE d.ts = timestamp)
        ), framed AS (
            SELECT t.timestamp, t.qc_note, t.updated_at, t.version,
                   t.wind_speed_raw, t.timestamp_raw, t.wind_dir_deg,
                   lag_m.wind_speed_ms        AS v_from,
                   lag_m.timestamp            AS t_from,
                   lead_m.wind_speed_ms       AS v_to,
                   lead_m.timestamp           AS t_to
              FROM targets t
              LEFT JOIN LATERAL (
                   SELECT * FROM measurements
                    WHERE timestamp < t.timestamp AND qc_note IS NULL
                    ORDER BY timestamp DESC LIMIT 1) lag_m ON true
              LEFT JOIN LATERAL (
                   SELECT * FROM measurements
                    WHERE timestamp > t.timestamp AND qc_note IS NULL
                    ORDER BY timestamp ASC LIMIT 1) lead_m ON true
             WHERE lag_m.wind_speed_ms IS NOT NULL
               AND lead_m.wind_speed_ms IS NOT NULL
        )
        INSERT INTO measurements (mast_id, timestamp, timestamp_raw,
                                  wind_speed_ms, wind_speed_raw, wind_dir_deg,
                                  qc_note, version, updated_at)
        SELECT :mast_id,
               f.timestamp,
               f.timestamp_raw,
               f.v_from + (f.v_to - f.v_from)
                    * EXTRACT(EPOCH FROM f.timestamp - f.t_from)
                    / EXTRACT(EPOCH FROM f.t_to - f.t_from),
               f.wind_speed_raw,
               f.wind_dir_deg,
               f.qc_note,
               f.version,
               f.updated_at
          FROM framed f
          ON CONFLICT (mast_id, timestamp) DO UPDATE
             SET timestamp_raw  = EXCLUDED.timestamp_raw,
                 wind_speed_ms  = EXCLUDED.wind_speed_ms,
                 wind_speed_raw = EXCLUDED.wind_speed_raw,
                 wind_dir_deg   = EXCLUDED.wind_dir_deg,
                 qc_note        = EXCLUDED.qc_note,
                 version        = EXCLUDED.version,
                 updated_at     = EXCLUDED.updated_at
           WHERE measurements.wind_speed_ms IS DISTINCT FROM EXCLUDED.wind_speed_ms
              OR measurements.qc_note       IS DISTINCT FROM EXCLUDED.qc_note
    """), {"defects": json.dumps(defects), "mast_id": mast_id})

    await session.execute(text("""
        WITH bounds AS (
            SELECT MIN(timestamp) AS lo, MAX(timestamp) AS hi FROM measurements
        ), hours AS (
            SELECT generate_series(lo, hi, interval '1 hour') AS ts FROM bounds
        ), defects AS (
            SELECT d.ts FROM jsonb_to_recordset(CAST(:defects AS jsonb))
                 AS d(ts timestamptz)
        ), targets AS (
            SELECT h.ts FROM hours h
              LEFT JOIN measurements m ON m.timestamp = h.ts
             WHERE m.timestamp IS NULL
               AND NOT EXISTS (SELECT 1 FROM defects d WHERE d.ts = h.ts)
        ), framed AS (
            SELECT t.ts                       AS timestamp,
                   lag_m.wind_speed_ms        AS v_from,
                   lag_m.timestamp            AS t_from,
                   lead_m.wind_speed_ms       AS v_to,
                   lead_m.timestamp           AS t_to,
                   lag_m.wind_dir_deg         AS wind_dir_deg,
                   lead_m.updated_at          AS updated_at,
                   lead_m.version             AS version
              FROM targets t
              LEFT JOIN LATERAL (
                   SELECT * FROM measurements
                    WHERE timestamp < t.ts AND qc_note IS NULL
                    ORDER BY timestamp DESC LIMIT 1) lag_m ON true
              LEFT JOIN LATERAL (
                   SELECT * FROM measurements
                    WHERE timestamp > t.ts AND qc_note IS NULL
                    ORDER BY timestamp ASC LIMIT 1) lead_m ON true
             WHERE lag_m.wind_speed_ms IS NOT NULL
               AND lead_m.wind_speed_ms IS NOT NULL
        )
        INSERT INTO measurements (mast_id, timestamp, timestamp_raw,
                                  wind_speed_ms, wind_speed_raw, wind_dir_deg,
                                  qc_note, version, updated_at)
        SELECT :mast_id,
               f.timestamp,
               '',
               f.v_from + (f.v_to - f.v_from)
                    * EXTRACT(EPOCH FROM f.timestamp - f.t_from)
                    / EXTRACT(EPOCH FROM f.t_to - f.t_from),
               '',
               f.wind_dir_deg,
               'Stunde nicht geliefert',
               f.version,
               f.updated_at
          FROM framed f
          ON CONFLICT (mast_id, timestamp) DO UPDATE
             SET timestamp_raw  = EXCLUDED.timestamp_raw,
                 wind_speed_ms  = EXCLUDED.wind_speed_ms,
                 wind_speed_raw = EXCLUDED.wind_speed_raw,
                 wind_dir_deg   = EXCLUDED.wind_dir_deg,
                 qc_note        = EXCLUDED.qc_note,
                 version        = EXCLUDED.version,
                 updated_at     = EXCLUDED.updated_at
           WHERE measurements.wind_speed_ms IS DISTINCT FROM EXCLUDED.wind_speed_ms
              OR measurements.qc_note       IS DISTINCT FROM EXCLUDED.qc_note
    """), {"defects": json.dumps(defects), "mast_id": mast_id})

    await session.execute(text("""
        WITH defects AS (
            SELECT d.ts AS timestamp, d.note AS qc_note, d.updated_at,
                   d.version, d.wind_speed_raw, d.timestamp_raw, d.wind_dir
              FROM jsonb_to_recordset(CAST(:defects AS jsonb))
                   AS d(ts timestamptz, note text, updated_at timestamptz,
                        version int, wind_speed_raw text, timestamp_raw text,
                        wind_dir int)
        ), framed AS (
            SELECT d.timestamp, d.qc_note, d.updated_at, d.version,
                   d.wind_speed_raw, d.timestamp_raw,
                   COALESCE(d.wind_dir, si.wind_dir_deg, lag_m.wind_dir_deg)
                                                             AS wind_dir_deg,
                   lag_m.wind_speed_ms                       AS v_from,
                   lag_m.timestamp                           AS t_from,
                   lead_m.wind_speed_ms                      AS v_to,
                   lead_m.timestamp                          AS t_to
              FROM defects d
              LEFT JOIN measurements si
                     ON si.timestamp = d.timestamp AND si.qc_note IS NOT NULL
              LEFT JOIN LATERAL (
                   SELECT * FROM measurements
                    WHERE timestamp < d.timestamp AND qc_note IS NULL
                    ORDER BY timestamp DESC LIMIT 1) lag_m ON true
              LEFT JOIN LATERAL (
                   SELECT * FROM measurements
                    WHERE timestamp > d.timestamp AND qc_note IS NULL
                    ORDER BY timestamp ASC LIMIT 1) lead_m ON true
             WHERE NOT EXISTS (
                   SELECT 1 FROM measurements m
                    WHERE m.timestamp = d.timestamp
                      AND m.qc_note IS NULL
                      AND (m.updated_at, m.version) >= (d.updated_at, d.version))
               AND lag_m.wind_speed_ms IS NOT NULL
               AND lead_m.wind_speed_ms IS NOT NULL
        )
        INSERT INTO measurements (mast_id, timestamp, timestamp_raw,
                                  wind_speed_ms, wind_speed_raw, wind_dir_deg,
                                  qc_note, version, updated_at)
        SELECT :mast_id,
               f.timestamp,
               f.timestamp_raw,
               f.v_from + (f.v_to - f.v_from)
                    * EXTRACT(EPOCH FROM f.timestamp - f.t_from)
                    / EXTRACT(EPOCH FROM f.t_to - f.t_from),
               f.wind_speed_raw,
               f.wind_dir_deg,
               f.qc_note,
               f.version,
               f.updated_at
          FROM framed f
          ON CONFLICT (mast_id, timestamp) DO UPDATE
             SET timestamp_raw  = EXCLUDED.timestamp_raw,
                 wind_speed_ms  = EXCLUDED.wind_speed_ms,
                 wind_speed_raw = EXCLUDED.wind_speed_raw,
                 wind_dir_deg   = EXCLUDED.wind_dir_deg,
                 qc_note        = EXCLUDED.qc_note,
                 version        = EXCLUDED.version,
                 updated_at     = EXCLUDED.updated_at
           WHERE measurements.wind_speed_ms IS DISTINCT FROM EXCLUDED.wind_speed_ms
              OR measurements.qc_note       IS DISTINCT FROM EXCLUDED.qc_note
    """), {"defects": json.dumps(defects), "mast_id": mast_id})


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


async def refresh_energy_matview(
    session: AsyncSession, *, concurrently: bool = True
) -> None:
    """Recompute `hourly_energy` (and, transitively, `daily_energy`).

    Runs **outside** any ingest transaction after the store commit: REFRESH
    takes ACCESS EXCLUSIVE immediately (a plain in-tx refresh after the
    minutes-long ingest transaction would block readers for that whole
    span), and CONCURRENTLY may not run inside a transaction block at all —
    hence the AUTOCOMMIT connection there.

    Accepted gap: a crash between the ingest commit and this refresh leaves
    the matview one run stale until the next run (~5 min cron cadence); no
    staleness guard at this data volume. Refresh is unconditional —
    `persist_reference` may have changed mast/turbine/site (shear, heights,
    curve) with zero measurement writes, and those feed the matview math.
    """
    statement = "REFRESH MATERIALIZED VIEW {}hourly_energy".format(
        "CONCURRENTLY " if concurrently else ""
    )
    if concurrently:
        conn = await session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
        await conn.execute(text(statement))
    else:
        await session.execute(text(statement))
        await session.commit()


def _latest_measurement_stmt():
    return Measurement.__table__.select().order_by(
        Measurement.timestamp.desc()
    ).limit(1)


async def latest_measurement(session: AsyncSession) -> Optional[Any]:
    result = await session.execute(_latest_measurement_stmt())
    return result.mappings().first()


async def aep_trailing_12m(session: AsyncSession) -> dict[str, Any]:
    """AEP gross (kWh) and usable hours over the trailing 12 months.

    Straight aggregation over the `hourly_energy` matview; refresh cadence
    and staleness contract are documented on `refresh_energy_matview`.
    """
    result = await session.execute(text("""
        SELECT COALESCE(SUM(energy_kwh), 0) AS aep_gross_kwh,
               COUNT(*)                     AS usable_hours,
               MIN(timestamp)               AS window_start,
               MAX(timestamp)               AS window_end
          FROM hourly_energy
         WHERE timestamp >= now() - interval '12 months'
    """))
    return dict(result.mappings().one())


async def daily_series(session: AsyncSession, days: int = 90) -> list[dict]:
    """Per-day energy series, oldest first.

    Every day of the window is present; days without any stored hour come
    back with NULL energy (a data gap the SPA renders empty). The mast is a
    singleton, so `daily_energy` is joined without a mast key.
    """
    result = await session.execute(text("""
        SELECT d.day, de.energy_kwh, de.hours, de.mean_wind_ms, de.max_wind_ms
          FROM (SELECT generate_series(
                           (now() - make_interval(days => :days))::date,
                           now()::date,
                           interval '1 day')::date AS day) AS d
          LEFT JOIN daily_energy de ON de.day = d.day
         ORDER BY d.day
    """), {"days": days})
    return [dict(row) for row in result.mappings().all()]


async def coverage(session: AsyncSession) -> dict[str, Any]:
    """Measurement range, expected/absent hours, interpolation count, max gap.

    Limited to the trailing 12 months, the same window as AEP, so the coverage
    describes the hours the yield is built from. Every stored hour is usable
    (`absent_hours` are the hours of the covered span with no row at all —
    unfillable edges); interpolated ones counted via `interpolated_hours`.
    """
    result = await session.execute(text("""
        SELECT MIN(timestamp)  AS from_ts,
               MAX(timestamp)  AS to_ts,
               COUNT(*)        AS total_hours,
               COUNT(*) FILTER (WHERE qc_note IS NOT NULL) AS interpolated_hours,
               CASE WHEN MIN(timestamp) IS NULL THEN 0
                    ELSE EXTRACT(EPOCH FROM MAX(timestamp) - MIN(timestamp)) / 3600 + 1
               END                                            AS expected_hours,
               COALESCE((SELECT MAX(gap)
                           FROM (SELECT EXTRACT(EPOCH FROM timestamp
                                                 - LAG(timestamp) OVER (ORDER BY timestamp))
                                        / 3600.0 - 1 AS gap
                                   FROM measurements
                                   WHERE timestamp >= now() - interval '12 months') AS gaps), 0)::int
                                                              AS max_gap_hours
          FROM measurements
         WHERE timestamp >= now() - interval '12 months'
    """))
    row = dict(result.mappings().one())
    row["expected_hours"] = int(row["expected_hours"])
    row["absent_hours"] = row["expected_hours"] - row["total_hours"]
    return row


# Bucket unit + generate_series step per resolution; f-string literals because
# the unit/step cannot be bound as intervals (asyncpg/SQLAlchemy cast ambiguity).
_WIND_RESOLUTIONS = {
    "hour": ("hour", "1 hour"),
    "day": ("day", "1 day"),
    "week": ("week", "1 week"),
}


async def wind_series(
    session: AsyncSession, days: int = 2, resolution: str = "hour"
) -> list[dict]:
    """Per-bucket speed stats + interpolation counts/reasons, oldest first.

    Every bucket of the trailing `days` window is present: hours without a
    stored row surface as empty buckets (NULL speeds) so the SPA can draw
    gaps where data is missing. Buckets are UTC (weeks start Monday); mean/
    min/max are the stored values (for interpolated hours that is the
    interpolation result). `qc_note`/`wind_speed_raw` aggregate the
    interpolated rows' reason and *rejected original* inside the bucket
    (`NULL` when nothing was interpolated) — at `hour` resolution that is
    simply the hour's own row; the raw is unit-dependent text as received.
    """
    unit, step = _WIND_RESOLUTIONS[resolution]
    result = await session.execute(text(f"""
        WITH bounds AS (
            SELECT date_trunc('{unit}', now() AT TIME ZONE 'UTC')
                       AT TIME ZONE 'UTC'                                  AS to_ts,
                   date_trunc('{unit}',
                              date_trunc('{unit}', now() AT TIME ZONE 'UTC')
                                  - make_interval(days => :days))
                       AT TIME ZONE 'UTC'                               AS from_ts
        ), buckets AS (
            SELECT generate_series(from_ts, to_ts, interval '{step}') AS bucket
              FROM bounds
        ), agg AS (
            SELECT date_trunc('{unit}', timestamp AT TIME ZONE 'UTC')
                       AT TIME ZONE 'UTC'                                    AS bucket,
                   AVG(wind_speed_ms) AS mean_wind_ms,
                   MIN(wind_speed_ms) AS min_wind_ms,
                   MAX(wind_speed_ms) AS max_wind_ms,
                   COUNT(*) FILTER (WHERE qc_note IS NOT NULL) AS interpolated_hours,
                   string_agg(DISTINCT qc_note, '; ')          AS qc_note,
                   string_agg(DISTINCT CASE WHEN wind_speed_raw <> ''
                                            THEN wind_speed_raw END, '; ')
                        FILTER (WHERE qc_note IS NOT NULL)
                                                               AS wind_speed_raw
              FROM measurements, bounds
             WHERE timestamp >= from_ts
               AND timestamp <  to_ts + interval '{step}'
             GROUP BY 1
        )
        SELECT b.bucket AS timestamp,
               a.mean_wind_ms, a.min_wind_ms, a.max_wind_ms,
               COALESCE(a.interpolated_hours, 0) AS interpolated_hours,
               a.qc_note, a.wind_speed_raw
          FROM buckets b
          LEFT JOIN agg a USING (bucket)
         ORDER BY b.bucket
    """), {"days": days})
    return [dict(row) for row in result.mappings().all()]


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
         WHERE timestamp >= now() - make_interval(days => :days)
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

_INGEST_RUN_COLS = """
       id, started_at, finished_at, status, pages, inserted, updated,
       frame_from, frame_to, interpolated, max_gap_hours, detail
"""


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
    result = await session.execute(text(f"""
        SELECT {_INGEST_RUN_COLS}
          FROM ingest_runs ORDER BY id DESC LIMIT :limit
    """), {"limit": limit})
    return [dict(row) for row in result.mappings().all()]


async def ingest_health(session: AsyncSession) -> dict[str, Any]:
    """Last ingest run + measurement staleness, feeding /api/health."""
    last_run = (await session.execute(text(f"""
        SELECT {_INGEST_RUN_COLS}
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
    interpolated: int = 0,
    max_gap_hours: Optional[int] = None, detail: Optional[str] = None,
) -> IngestRun:
    run = IngestRun(
        started_at=started_at, finished_at=finished_at, status=status,
        pages=pages, inserted=inserted, updated=updated,
        frame_from=frame_from, frame_to=frame_to,
        interpolated=interpolated, max_gap_hours=max_gap_hours,
        detail=detail,
    )
    session.add(run)
    await session.flush()
    return run
