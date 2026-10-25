"""taskiq wiring for the ingest worker.

`backfill.py`/`sync.py`/`qc.py` stay pure async functions; this module only
mounts them on the broker. Postgres doubles as the broker (taskiq-pg,
LISTEN/NOTIFY) — no Redis. Worker runs a startup sweep + a gated backfill
(see `_worker_startup` below), then executes scheduled + on-demand tasks.

Separate `worker` and `scheduler` compose services, same image as `api`:

- worker:     taskiq worker app.worker:broker
- scheduler:  taskiq scheduler app.worker:scheduler   (send-only, cron */5)
- api:        produces tasks only — `broker.startup()` in the lifespan,
              `periodic_sync.kiq()` in the trigger endpoint (phase 3)

taskiq-pg manages its own `taskiq_messages` table inside the windiq DB;
it stays outside alembic (implementation plan §Risks).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import text
from taskiq import TaskiqEvents, TaskiqScheduler
from taskiq.abc.result_backend import AsyncResultBackend
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_pg import AsyncpgBroker

from app.db.engine import SessionLocal
from app.db.repo import ingest_window_covered
from app.ingest import backfill, sync
from app.ingest.common import new_run_id

load_dotenv()

log = logging.getLogger(__name__)

# Minute-quantized: with a single dedicated worker the jitter is irrelevant
SYNC_CRON = "*/5 * * * *"


def _pg_dsn() -> str:
    # DATABASE_URL is ORM-shaped (postgresql+asyncpg://…); the broker only
    # wants the plain asyncpg DSN.
    dsn = os.getenv("DATABASE_URL", "postgresql://windiq:windiq@db:5432/windiq")
    return dsn.replace("+asyncpg", "", 1)


class NullResultBackend(AsyncResultBackend):
    """Task results go nowhere — nobody polls them; ingest_runs is the judge."""

    async def set_result(self, task_id, result) -> None:
        pass

    async def is_result_ready(self, task_id) -> bool:
        return True

    async def get_result(self, task_id, with_logs=False):
        raise LookupError("results are not stored (NullResultBackend)")


broker = AsyncpgBroker(dsn=_pg_dsn()).with_result_backend(
    NullResultBackend()  # nobody polls results; ingest_runs is the source of truth
)


@broker.task(schedule=[{"cron": SYNC_CRON}])
async def periodic_sync(run_id: Optional[str] = None) -> dict:
    """Cron `*/5` + manual `POST /api/ingest/run` (phase 3)."""
    return await sync.run_sync(run_id=run_id)


@broker.task
async def run_backfill(run_id: Optional[str] = None) -> dict:
    """One-time full start; idempotent, safe to repeat."""
    return await backfill.run_backfill(run_id=run_id)


async def _sweep_stale_queue() -> int:
    """Delete unconsumed rows from the broker's own table (plan finding 1).

    taskiq-pg delivers only while a worker LISTENs: a message queued during
    downtime (manual "sync now" or a cron sent by the scheduler) lingers in
    `taskiq_messages` forever — the INSERT-time NOTIFY is lost and a worker
    restart does not replay the table. Rows here can only linger unprocessed
    (consumed ones are ack-deleted by the broker), so the sweep loses nothing
    but ghosts; the data catches up via the next cron tick (≤ 5 min).
    """
    try:
        async with SessionLocal() as session:
            result = await session.execute(
                text("DELETE FROM taskiq_messages")
            )
            await session.commit()
    except Exception:
        log.warning("startup queue sweep failed — continuing anyway", exc_info=True)
        return 0
    return result.rowcount or 0


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _worker_startup(context) -> None:
    """Queue hygiene + gate the startup backfill (plan findings 1 and 2)."""
    run_id = new_run_id()
    swept = await _sweep_stale_queue()
    if swept:
        log.info("startup queue sweep run=%s swept=%s", run_id, swept)
    async with SessionLocal() as session:
        covered = await ingest_window_covered(session)
    if covered:
        log.info("startup backfill skipped run=%s reason=window-covered", run_id)
        return
    log.info("startup backfill scheduled run=%s", run_id)
    await run_backfill(run_id=run_id)


scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
