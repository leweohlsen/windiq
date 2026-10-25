"""taskiq wiring smoke tests: task registration, cron schedule, broking.

The real PgBroker never connects at import time; the execute-path is
smoke-tested with an in-memory broker (task wrappers only — the ingest
bodies are covered by test_ingest.py).
"""
from taskiq import InMemoryBroker
from taskiq.schedule_sources import LabelScheduleSource

import app.ingest.backfill as backfill_mod
import app.ingest.sync as sync_mod
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
