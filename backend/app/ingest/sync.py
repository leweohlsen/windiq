"""Periodic change-watermark sync: only rows changed since the last watermark.

`updated_since = max(measurements.updated_at) − 1 h overlap` — the overlap
catches late revisions that landed after the previous watermark; the upsert
guards make replaying the boundary row harmless (quirks B2/B6).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import SessionLocal
from app.ingest.backfill import _run, journal_error
from app.windiq.client import WindIQClient

log = logging.getLogger(__name__)

# Late revisions can land after the previous watermark → re-read this window;
# guarded upserts make the overlap harmless
SYNC_OVERLAP_HOURS = 1


async def watermark(session: AsyncSession) -> Optional[datetime]:
    return await session.scalar(text("SELECT MAX(updated_at) FROM measurements"))


def _as_utc(dt: datetime) -> datetime:
    # asyncpg returns tz-aware datetimes already; naive is defensive only
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None \
        else dt.replace(tzinfo=timezone.utc)


async def run_sync(client: Optional[WindIQClient] = None) -> dict[str, Any]:
    """One periodic ingest cycle; same journaling + locking as the backfill."""
    started_at = _as_utc(datetime.now(timezone.utc))
    client = client or WindIQClient()
    try:
        async with SessionLocal() as session:
            mark = await watermark(session)
            updated_since: Optional[datetime] = None
            if mark is not None:
                updated_since = _as_utc(mark) - timedelta(hours=SYNC_OVERLAP_HOURS)
            return await _run(
                session, client, started_at=started_at, updated_since=updated_since
            )
    except Exception as exc:
        log.exception("sync failed")
        await journal_error(exc, started_at)
        raise
