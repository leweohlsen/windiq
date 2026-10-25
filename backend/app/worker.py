"""taskiq wiring for the ingest worker.

`backfill.py`/`sync.py`/`qc.py` stay pure async functions; this module only
mounts them on the broker. Postgres doubles as the broker (taskiq-pg,
LISTEN/NOTIFY) — no Redis. Worker runs `run_backfill()` once at startup
(idempotent), then executes scheduled + on-demand tasks.

Separate `worker` and `scheduler` compose services, same image as `api`:

- worker:     taskiq worker app.worker:broker
- scheduler:  taskiq scheduler app.worker:scheduler   (send-only, cron */5)
- api:        produces tasks only — `broker.startup()` in the lifespan,
              `periodic_sync.kiq()` in the trigger endpoint (phase 3)

taskiq-pg manages its own `taskiq_messages` table inside the windiq DB;
it stays outside alembic (implementation plan §Risks).
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from taskiq import TaskiqEvents, TaskiqScheduler
from taskiq.abc.result_backend import AsyncResultBackend
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_pg import AsyncpgBroker

from app.ingest import backfill, sync

load_dotenv()

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
async def periodic_sync() -> dict:
    """Cron `*/5` + manual `POST /api/ingest/run` (phase 3)."""
    return await sync.run_sync()


@broker.task
async def run_backfill() -> dict:
    """One-time full start; idempotent, safe to repeat."""
    return await backfill.run_backfill()


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _backfill_once(context) -> None:
    await run_backfill()


scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
