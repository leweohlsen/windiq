"""Shared ingest pipeline helpers: cursor paging, reference mapping, run stats.

Both the one-time backfill and the periodic sync walk the same paginated
`/v1/measurements` endpoint and journal into `ingest_runs` the same way.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator, Callable, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from wind_iq_measurement_api_client.models import (
    Mast,
    MeasurementPage,
    Site,
    Turbine,
)

from app.db.repo import MeasurementRow, upsert_measurements
from app.ingest.qc import NormalizedHour

log = logging.getLogger(__name__)

# Server 422s above 500 → this is both our request size and the facade clamp
PAGE_LIMIT = 500
# Circuit breaker: a full backfill needs ~18 pages; 10k pages is ≥ 5M rows
MAX_PAGES = 10_000

# A page with more defected rows than this is an API change, not bad data → run status `partial`
DEFECT_PAGE_FRACTION = 0.3

# Ingest advisory lock: prevents cron + manual runs from overlapping
INGEST_LOCK_NAME = "windiq:ingest"


@dataclass
class IngestStats:
    """Tallies over one ingest run, written into `ingest_runs` at the end."""

    pages: int = 0
    inserted: int = 0
    updated: int = 0
    defects: dict = field(default_factory=dict)  # defect class → count
    dead_letters: int = 0
    defect_heavy_pages: int = 0
    frame_from: Optional[datetime] = None
    frame_to: Optional[datetime] = None

    @property
    def status(self) -> str:
        return "partial" if self.defect_heavy_pages else "ok"

    @property
    def interpolated(self) -> int:
        """Hours this run could not store and filled by interpolation."""
        return sum(self.defects.values())

    def merge_page(self, normalized: Iterable[NormalizedHour], dead_letters: int,
                   inserted: int, updated: int, defect_heavy: bool) -> None:
        self.pages += 1
        self.inserted += inserted
        self.updated += updated
        self.dead_letters += dead_letters
        self.defect_heavy_pages += defect_heavy
        for row in normalized:
            if row.defect:
                self.defects[row.defect] = self.defects.get(row.defect, 0) + 1
            ts = row.timestamp
            self.frame_from = min(self.frame_from, ts) if self.frame_from else ts
            self.frame_to = max(self.frame_to, ts) if self.frame_to else ts


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_run_id() -> str:
    """Queue tasks (api trigger) generate it, the ingest run adopts it in logs."""
    return uuid.uuid4().hex[:12]


def mast_values(mast: Mast) -> dict[str, Any]:
    return {
        "id": mast.id,
        "name": mast.name,
        "latitude": mast.latitude,
        "longitude": mast.longitude,
        "measurement_height_m": mast.measurement_height_m,
        "operator": mast.operator,
        # Mast carries no version/updated_at — unconditional upsert by design
        "commissioned_at": date.fromisoformat(mast.commissioned_at),
    }


def turbine_values(turbine: Turbine) -> tuple[dict[str, Any], list[tuple[float, float]]]:
    values = {
        "id": turbine.id,
        "name": turbine.name,
        "rated_power_kw": turbine.rated_power_kw,
        "hub_height_m": turbine.hub_height_m,
        "rotor_diameter_m": turbine.rotor_diameter_m,
        "cut_in_wind_speed_ms": turbine.cut_in_wind_speed_ms,
        "cut_out_wind_speed_ms": turbine.cut_out_wind_speed_ms,
        "version": turbine.version,
        "updated_at": _iso_dt(turbine.updated_at),
    }
    curve = [(p.wind_speed_ms, p.power_kw) for p in turbine.power_curve]
    return values, curve


def site_values(site: Site) -> dict[str, Any]:
    return {
        "id": site.id,
        "name": site.name,
        "mast_id": site.mast_id,
        "shear_exponent": site.shear_exponent,
        "availability_loss": site.losses.availability,
        "electrical_loss": site.losses.electrical,
        "wake_loss": site.losses.wake,
        "uncertainty": site.uncertainty,
        "version": site.version,
        "updated_at": _iso_dt(site.updated_at),
    }


def _iso_dt(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def defect_payload(normalized: Iterable[NormalizedHour]) -> list[dict[str, Any]]:
    """This run's defected hours, ready for `repo.interpolate_gaps`."""
    return [
        {
            "ts": row.timestamp.isoformat(),
            "note": row.reason,
            "updated_at": row.updated_at.isoformat(),
            "version": row.version,
            "wind_speed_raw": row.wind_speed_raw,
            "timestamp_raw": row.timestamp_raw,
            "wind_dir": row.wind_dir_deg,
        }
        for row in normalized if row.defect is not None
    ]


async def iter_measurement_pages(
    client, *, since=None, updated_since=None,
    fetch: Optional[Callable] = None,
) -> AsyncIterator[MeasurementPage]:
    """Walk cursor pagination until `next_cursor = null` (quirks B5/B4).

    `fetch` is injectable for tests; defaults to the client facade, which
    clamps `limit` and retries transient failures itself.
    """
    fetch_page = fetch or client.measurements
    cursor: Optional[str] = None
    for _ in range(MAX_PAGES):
        page = await fetch_page(
            limit=PAGE_LIMIT, cursor=cursor, since=since, updated_since=updated_since
        )
        yield page
        if page.next_cursor is None:
            return
        cursor = page.next_cursor
    raise RuntimeError(f"cursor pagination did not terminate after {MAX_PAGES} pages")


async def get_cut_out(session: AsyncSession) -> Optional[float]:
    """Turbine cut-out from the DB — the QA bound moves with reference data."""
    return await session.scalar(text(
        "SELECT cut_out_wind_speed_ms FROM turbine LIMIT 1"
    ))


async def ingest_page(
    session: AsyncSession, page: MeasurementPage,
    *, mast_id: str, cut_out_ms: float, normalize,
) -> tuple[list[NormalizedHour], int, int, int, bool]:
    """Normalize + upsert one page (single transaction step).

    Only rows with a usable value are stored; defected hours come back in the
    normalized list for the end-of-run interpolation.
    """
    dead_letters = 0
    rows: list[MeasurementRow] = []
    normalized: list[NormalizedHour] = []
    for api_row in page.data:
        n = normalize(api_row, mast_id=mast_id, cut_out_ms=cut_out_ms)
        if n is None:
            dead_letters += 1
            continue
        normalized.append(n)
        if n.defect is None:
            rows.append(MeasurementRow(
                mast_id=mast_id,
                timestamp=n.timestamp,
                timestamp_raw=n.timestamp_raw,
                wind_speed_ms=n.wind_speed_ms,
                wind_speed_raw=n.wind_speed_raw,
                wind_dir_deg=n.wind_dir_deg,
                qc_note=None,
                version=n.version,
                updated_at=n.updated_at,
            ))
    inserted, updated = await upsert_measurements(session, rows)
    page_rows = len(page.data)
    defect_count = sum(1 for r in normalized if r.defect is not None)
    defect_heavy = page_rows > 0 and defect_count > page_rows * DEFECT_PAGE_FRACTION
    return normalized, inserted, updated, dead_letters, defect_heavy


async def max_gap_hours(
    session: AsyncSession, frame_from: datetime, frame_to: datetime
) -> Optional[int]:
    """Largest consecutive-timestamp hole (hours) inside the fetched frame."""
    result = await session.execute(text("""
        SELECT MAX(gap) AS max_gap
          FROM (SELECT EXTRACT(EPOCH FROM timestamp - LAG(timestamp)
                              OVER (ORDER BY timestamp)) / 3600.0 - 1 AS gap
                  FROM measurements
                 WHERE timestamp BETWEEN :from_ts AND :to_ts) AS gaps
    """), {"from_ts": frame_from, "to_ts": frame_to})
    value = result.scalar_one_or_none()
    return int(value) if value is not None and value > 0 else 0


def compile_detail(stats: IngestStats, dead_letter_count: int) -> str:
    """Run detail: defect-class breakdown of the interpolated hours."""
    parts = [
        f"{cls}={count}"
        for cls, count in sorted(stats.defects.items())
    ]
    if dead_letter_count:
        parts.append(f"dead_letter={dead_letter_count}")
    if stats.defect_heavy_pages:
        parts.append(f"defect_heavy_pages={stats.defect_heavy_pages}")
    return "; ".join(parts) if parts else None
