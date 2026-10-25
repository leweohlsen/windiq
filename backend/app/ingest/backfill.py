"""One-time full start: reference data first, then the whole measurement window.

Idempotent by construction — guarded upserts make a replayed backfill a
no-op (phase-1 acceptance criterion: byte-identical row count on repeat).
Stays a pure async function: no taskiq imports here.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import SessionLocal
from app.db.repo import record_ingest_run, upsert_mast, upsert_site, upsert_turbine
from app.ingest.common import (
    IngestStats,
    compile_detail,
    get_cut_out,
    ingest_page,
    iter_measurement_pages,
    mast_values,
    max_gap_hours,
    now_utc,
    site_values,
    turbine_values,
)
from app.ingest.qc import normalize_measurement
from app.windiq.client import WindIQClient

log = logging.getLogger(__name__)


async def persist_reference(
    session: AsyncSession, client: WindIQClient
) -> tuple[str, float]:
    """Refresh mast, turbine (+ power curve) and site; return (mast_id, cut_out).

    Turbine/Site are `updated_at`-guarded, Mast is unconditional — the
    reference-data asymmetry from the quirks doc. The caller owns the commit.
    """
    values, curve = turbine_values(await client.turbine())
    await upsert_turbine(session, values, power_curve=curve)
    await upsert_mast(session, mast_values(await client.mast()))
    await upsert_site(session, site_values(await client.site()))

    mast_id = await session.scalar(text("SELECT mast_id FROM site LIMIT 1"))
    cut_out_ms = await get_cut_out(session)
    if not mast_id or cut_out_ms is None:
        raise ValueError("reference data incomplete — cannot derive mast/QC bound")
    return mast_id, cut_out_ms


async def _run(
    session: AsyncSession, client: WindIQClient, *,
    started_at: datetime, updated_since: Optional[datetime] = None,
) -> dict[str, Any]:
    """Shared ingest body: reference refresh + paged measurements + journal.

    The whole run is one transaction on one connection; the transaction-level
    advisory lock frees itself on commit *and* rollback — the cron run and a
    manual run can never overlap, the latecomer exits immediately. Passing
    `updated_since=None` walks the full window (backfill), otherwise only
    rows changed inside the watermark window arrive (sync).
    """
    locked = await session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtext('windiq:ingest'))")
    )
    if not locked:
        return {"status": "skipped", "reason": "run already active"}

    mast_id, cut_out_ms = await persist_reference(session, client)
    stats = IngestStats()
    async for page in iter_measurement_pages(client, updated_since=updated_since):
        rows, inserted, updated, dead, suspect_heavy = await ingest_page(
            session, page, mast_id=mast_id, cut_out_ms=cut_out_ms,
            normalize=normalize_measurement,
        )
        stats.merge_page(rows, dead, inserted, updated, suspect_heavy)

    max_gap = await max_gap_hours(session, stats.frame_from, stats.frame_to) \
        if stats.frame_from else None
    await record_ingest_run(
        session, started_at=started_at, finished_at=now_utc(),
        status=stats.status, pages=stats.pages,
        inserted=stats.inserted, updated=stats.updated,
        frame_from=stats.frame_from, frame_to=stats.frame_to,
        qc_missing=stats.qc.get("missing", 0),
        qc_suspect=stats.qc.get("suspect", 0),
        qc_malformed=stats.qc.get("malformed", 0),
        max_gap_hours=max_gap,
        detail=compile_detail(stats, stats.dead_letters),
    )
    await session.commit()
    return {
        "status": stats.status, "pages": stats.pages,
        "inserted": stats.inserted, "updated": stats.updated,
        "max_gap_hours": max_gap,
    }


async def run_backfill(client: Optional[WindIQClient] = None) -> dict[str, Any]:
    """Full backfill (all pages from the API window start → backfill=true)."""
    client = client or WindIQClient()
    started_at = now_utc()
    try:
        async with SessionLocal() as session:
            return await _run(session, client, started_at=started_at)
    except Exception as exc:
        log.exception("backfill failed")
        await journal_error(exc, started_at)
        raise


async def journal_error(exc: Exception, started_at: datetime) -> None:
    """Write an `error` run row in its own transaction (main tx is rolled back)."""
    try:
        async with SessionLocal() as session:
            async with session.begin():
                await record_ingest_run(
                    session, started_at=started_at, finished_at=now_utc(),
                    status="error", pages=0, inserted=0, updated=0,
                    detail=f"{type(exc).__name__}: {exc}",
                )
    except Exception:
        log.exception("could not journal the failed ingest run")
