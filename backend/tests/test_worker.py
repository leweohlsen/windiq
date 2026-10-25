"""taskiq wiring smoke tests: task registration, cron schedule, broking.

The real PgBroker never connects at import time; the execute-path is
smoke-tested with an in-memory broker (task wrappers only — the ingest
bodies are covered by test_ingest.py). Startup sweep + backfill gating are
integration-tested against Postgres (ghost `taskiq_messages` rows).
"""
from datetime import timedelta

from sqlalchemy import text
from taskiq import InMemoryBroker
from taskiq.schedule_sources import LabelScheduleSource

import app.ingest.backfill as backfill_mod
import app.ingest.sync as sync_mod
import app.worker as worker_mod
from app.db import repo
from app.db.engine import SessionLocal
from app.worker import SYNC_CRON, broker, scheduler


async def test_tasks_are_registered():
    names = list(broker.get_all_tasks())
    assert any(n.endswith("periodic_sync") for n in names)
    assert any(n.endswith("run_backfill") for n in names)
    assert [type(s) for s in scheduler.sources] == [LabelScheduleSource]


async def test_cron_schedule_is_picked_up():
    source = LabelScheduleSource(broker)
    await source.startup()
    schedules = await source.get_schedules()
    assert len(schedules) == 1
    assert schedules[0].cron == SYNC_CRON
    assert schedules[0].task_name.endswith("periodic_sync")


async def test_task_execution_smoke(monkeypatch):
    """The task bodies delegate to the ingest modules (replaceable seams)."""
    async def fake_sync():
        return {"status": "ok"}

    async def fake_backfill():
        return {"status": "ok"}

    monkeypatch.setattr(sync_mod, "run_sync", fake_sync)
    monkeypatch.setattr(backfill_mod, "run_backfill", fake_backfill)

    smoke_broker = InMemoryBroker()

    @smoke_broker.task
    async def smoke_sync():
        return await sync_mod.run_sync()

    @smoke_broker.task
    async def smoke_backfill():
        return await backfill_mod.run_backfill()

    sync_handle = await smoke_sync.kiq()
    backfill_handle = await smoke_backfill.kiq()
    await smoke_broker.wait_all()
    assert (await sync_handle.get_result()).return_value == {"status": "ok"}
    assert (await backfill_handle.get_result()).return_value == {"status": "ok"}


# --- phase 5: startup sweep + gated backfill (plan findings 1 and 2) ---


async def _seed_ghost_messages(db) -> None:
    """Simulate rows lingering from a worker-less downtime (schema stub).

    The real taskiq-pg table has the same name; the sweep only DELETEs, so a
    minimal stub is enough.
    """
    await db.execute(text(
        "CREATE TABLE IF NOT EXISTS taskiq_messages"
        " (message_id TEXT PRIMARY KEY, message TEXT NOT NULL)"
    ))
    await db.execute(text("DELETE FROM taskiq_messages"))
    await db.execute(text(
        "INSERT INTO taskiq_messages (message_id, message)"
        " VALUES ('ghost-1', '{}'), ('ghost-2', '{}')"
    ))
    await db.commit()


async def test_sweep_deletes_unconsumed_queue_rows(db, clean):
    await _seed_ghost_messages(db)
    assert await worker_mod._sweep_stale_queue() == 2
    # second sweep is a no-op — nothing lingers
    assert await worker_mod._sweep_stale_queue() == 0

    async with SessionLocal() as s:
        await s.execute(text("DROP TABLE taskiq_messages"))
        await s.commit()


async def test_sweep_survives_missing_queue_table(db, clean):
    async with SessionLocal() as s:
        await s.execute(text("DROP TABLE IF EXISTS taskiq_messages"))
        await s.commit()
    assert await worker_mod._sweep_stale_queue() == 0


async def test_worker_startup_runs_backfill_and_sweeps_when_not_covered(
    monkeypatch, db, clean
):
    await _seed_ghost_messages(db)
    sent: list[str | None] = []

    async def fake_backfill(run_id=None):
        sent.append(run_id)
        return {"status": "ok"}

    monkeypatch.setattr(worker_mod, "run_backfill", fake_backfill)
    await worker_mod._worker_startup(None)

    assert len(sent) == 1 and sent[0]                    # run id passed to the backfill

    async with SessionLocal() as s:
        left = (await s.execute(
            text("SELECT COUNT(*) FROM taskiq_messages"))).scalar()
    assert left == 0                                     # ghosts swept at startup

    async with SessionLocal() as s:
        await s.execute(text("DROP TABLE taskiq_messages"))
        await s.commit()


async def test_worker_startup_skips_backfill_when_window_covered(
    monkeypatch, db, clean, reference, measurement_row, hour
):
    await repo.upsert_measurements(db, [
        # deep history, fresh forward progress → covered (repo test: case 3)
        measurement_row(hour - timedelta(days=400), 7.0, updated_at=hour)
    ])
    await db.commit()

    calls: list[dict] = []

    async def fake_backfill(run_id=None):
        calls.append({"run_id": run_id})
        return {"status": "ok"}

    async def quiet_sweep():
        return 0

    monkeypatch.setattr(worker_mod, "run_backfill", fake_backfill)
    monkeypatch.setattr(worker_mod, "_sweep_stale_queue", quiet_sweep)
    await worker_mod._worker_startup(None)

    assert calls == []                                   # gated: no journal noise
