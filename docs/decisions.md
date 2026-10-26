# Decisions

Why the system is built the way it is. Each entry records the decision and the
reason for it. Data evidence is in [api-measurements-quirks.md](api-measurements-quirks.md);
the phase history is in [implementation-plan.md](implementation-plan.md).

## Storage and data model

**PostgreSQL 17 with SQLAlchemy 2.0 (async), asyncpg and Alembic.**
The pipeline is fully async, and Alembic keeps the schema versioned.

**One row per measurement hour; the latest revision wins.**
The API publishes corrections as new versions. The yield calculation only needs the
current value. Earlier revisions are overwritten, so there is no version history.
`version` and `updated_at` describe the stored revision.

**Canonical values are created at ingest: UTC `timestamptz` and m/s.**
The API mixes units (m/s and km/h) and timezone suffixes (`Z`, `+00:00`, `+02:00`).
Normalizing once makes the primary key, upserts and indexes simple. The raw
values are kept next to the canonical ones.

**Quality flag plus raw value in the same row.**
The API sends `null`, numeric strings like `"7.47"`, the sentinel `-999.0`, and outliers
up to 83 m/s. Keeping the raw value and the flag makes every cleaning step visible.
Numeric strings that parse cleanly are `ok`, because only the type was wrong, not the value.
The upper plausibility bound comes from the turbine cut-out (plus a margin) in the
database, so it changes with the reference data and is not a hardcoded constant.

**Suspect, missing and malformed hours yield no energy.**
They show up in the coverage figures instead. A guessed value would silently change the
yield number.

**Reference data (mast, turbine, site) lives in the database, not in config.**
These records change occasionally (turbine version 43, site version 44 in the sample).
Each refresh is applied through an upsert guard. The mast table has no `version` or
`updated_at`, so its upsert is unconditional. A guard there would skip it forever.

**Plain SQL views, no materialized rollups, no TimescaleDB or partitioning.**
The data is about 8.7k rows per year, under 1 MB. Aggregating on each query is fast
enough, and there is nothing to refresh or maintain.

## Ingest

**Incremental sync with a change watermark (`updated_since`) and a 1-hour overlap.**
The watermark is `MAX(measurements.updated_at)` in the database, so no separate state
is needed. The overlap catches late revisions. Replays are harmless because of the upserts.

**Upsert guard on `updated_at`, not on `version`.**
The API orders `updated_since` by `updated_at`. Using the same column for the watermark
and the guard keeps the logic in one place.

**Ingest runs in a separate `worker` container, not inside the API process.**
This supersedes the first plan, which ran ingest as an asyncio task in the backend's
lifespan. Scheduled runs need to keep going when the API restarts. The worker can also
be restarted on its own, and the cron keeps ticking. The ingest modules are plain async
functions with no taskiq imports, so a fallback to a plain asyncio loop would not touch them.

**A separate `scheduler` container, not a cron loop in the worker.**
The worker drains a queue. The scheduler is a cron loop that inserts messages. One process
cannot do both well. With one scheduler and N workers, each cron tick fires once. If every
worker ran the cron, each tick would fire N times.

**Postgres is the task broker (taskiq-pg), no Redis.**
One fewer service to run, and the broker lives in the database we already back up.
The trade-off: a message queued while no worker is listening is lost. The worker sweeps
these leftovers at startup, and the next cron tick catches up (see [resilience.md](resilience.md)).

**`ingest_runs` is the journal; task results are not stored.**
Nobody polls task results. The dashboard needs run history, so each run writes a row with
its status, counts, QC defects and largest gap.

**A transaction per run, plus an advisory lock.**
A run commits all at once or not at all. The advisory lock stops a cron run and a manual
run from overlapping. The lock is released on rollback too, so a crash never blocks the next run.

**Startup backfill is gated on coverage.**
A restart does not repeat the full backfill when the store already has history (350 days
or more) and recent progress (within 48 h). Restarts therefore don't add noise to the journal.

**Only transient upstream failures are retried.**
429, 5xx, timeouts and connection errors get exponential backoff with jitter (4 attempts by default).
Other 4xx responses fail fast, because they won't succeed on retry. `Retry-After` is
honored but capped at 8 s, so a hostile header cannot stall the worker.

## API and dashboard

**The API has no authentication and is only reachable through nginx.**
The SPA and the API share one origin through the nginx proxy, and the backend is not published on the host.

**P50/P90 math stays in Python, not SQL.**
It is a few lines and easy to property-test. The power curve interpolation and the sums stay in SQL.

**Energies are shown in MWh, daily and annual.**
The assignment specifies annual figures in MWh, and the dashboard uses the same unit for daily energy.

**Wind rose sectors are centered on their compass direction.**
Sector bins are `ROUND(deg / 22.5) % 16`. A floor-based left edge would place 30° in NNE
instead of NE.

**The dashboard UI is German, the backend and API are English.**
See [terminology.md](terminology.md) for the mapping.
