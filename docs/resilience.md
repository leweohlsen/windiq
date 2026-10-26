# Resilience — process roles, failure modes, recovery

Status: 2026-10-26 · distilled from [implementation-plan.md](implementation-plan.md) phase 5 findings + code survey
Code: `backend/app/worker.py` (wiring, sweep, gate) · `docker-compose.yml` (roles, ordering)
Behavior evidence: [ingest-strategy.md](ingest-strategy.md) (triggers, guard, journal)

## Process roles

Four long-lived containers, one image, different commands:

| Container | Command | Role |
| --- | --- | --- |
| `backend` | uvicorn `app.main:app` | serve API + SPA data; **produce-only** — `broker.startup()` in the lifespan, `.kiq()` in "sync now" |
| `worker` | `taskiq worker app.worker:broker` | consume: execute `periodic_sync`, `run_backfill`; startup sweep + gated backfill |
| `scheduler` | `taskiq scheduler app.worker:scheduler` | send-only: enqueue `periodic_sync` per cron `*/5 * * * *`; never executes tasks |
| `db` | postgres:17 | storage **and** broker (taskiq-pg LISTEN/NOTIFY) — no Redis |

### Why scheduler and worker are separate containers

They boot the same `app.worker` module but run irreconcilably different loops:

- The worker's job is to LISTEN on `taskiq_messages` and drain it; the
  scheduler's job is a cron loop that reads the `@broker.task(schedule=…)`
  labels and INSERTs messages. Two separate taskiq commands (`taskiq worker`
  vs `taskiq scheduler`) with separate event loops — one process can't do
  both.
- **No duplicate sends:** if every worker also ticked the cron, scaling to
  >1 worker fires `periodic_sync` once per worker per tick. One scheduler +
  N workers is the safe shape (here N = 1, but the wiring allows more).
- **Cron independence:** a worker crash/restart does not stop the clock; the
  scheduler keeps firing — see the ghost-message interaction below.
- **Startup events stay with the consumer:** the sweep and the gated backfill
  (`WORKER_STARTUP`) make sense only where tasks are executed, not where
  they are sent.
- The scheduler is send-only and near-idle; keeping it out of the worker
  costs nothing and makes each container's job legible.

`api` is deliberately the third role: it produces tasks via `.kiq()` but
never ticks the schedule and never consumes.

## Startup ordering

```
db (healthy) → migrate (one-shot alembic) → backend / worker / scheduler
```

`depends_on: migrate: completed_successfully` everywhere — a migration can
never race the worker's schema access. `db` has a `pg_isready` healthcheck;
`backend` is probed via `/api/health` (Docker healthcheck); everything
restarts `unless-stopped`.

## Upstream fetch resilience (`app/windiq/`)

The facade is the only place the WindIQ API is touched — all retry policy
lives there (`windiq/retry.py`):

- **Transient-only retries:** 4 attempts (env-tunable `WIQ_MAX_ATTEMPTS`)
  for 429/5xx, timeouts and connection errors; deliberate 4xx/auth failures
  fail fast — they will not succeed on retry (`is_transient`).
- **Server-friendly backoff:** exponential + jitter, and a `Retry-After`
  header is honored when present — capped (`WIQ_RETRY_MAX_WAIT`, 8 s) so a
  hostile header cannot stall the worker.
- **Fail-fast timeouts:** 30 s per API call, 15 s per token fetch — a hanging
  upstream aborts into a retriable transport error instead of pinning a
  worker.
- **Auth survives flakiness:** `BearerTokenAuth` keeps the token fresh with
  a 30 s expiry margin, re-authenticates transparently on a 401 (one retry
  per request), and the token fetch itself goes through the shared retryer.
  Missing credentials abort at construction with `WindIQCredentialsError`
  (loud at startup, not a deferred break).
- **Pagination breaker:** cursor loops stop at `MAX_PAGES` (10 000 pages ≈
  ≥ 5 M rows) with a `RuntimeError` instead of looping forever; `limit` is
  clamped to 500 because the server 422s above (quirks B1).

## Ingest run containment (`app/ingest/`)

- **One transaction per run:** whole run on one connection; nothing is
  stored halfway — a crash rolls the run back completely, and the next run
  replays it harmlessly (guards below).
- **Advisory lock frees itself:** `pg_try_advisory_xact_lock` — released on
  commit *and* rollback, so a crashed run never blocks the next one. The
  latecomer of a cron + manual collision exits with `skipped`.
- **Error journaling is itself guarded:** `journal_error` writes the
  `error` row in its own transaction and swallows its own failures — a
  broken DB cannot turn journaling into a second crash.
- **Bad data is contained per row, not per run:** malformed rows are
  dead-lettered (loud log, NULL value stored, run continues); a page with
  > 30 % `suspect` rows flips the run to `partial` — that pattern signals
  an API change, not dirty data.
- **Raw values kept for forensics:** `timestamp_raw`, `wind_speed_raw`
  store the original strings next to the canonical values — recovery and
  audit need no refetch.
- **Schema-level last line:** the `measurements_qc_values` CHECK constraint
  rejects any value/quality pairing that app code would let slip.

## Failed-delivery handling (taskiq-pg)

taskiq-pg delivers only while a worker LISTENs: the INSERT-time NOTIFY is
lost during downtime and a worker restart does **not** replay the table —
a message queued while the worker was down (manual "sync now" or a cron
sent by the scheduler) lingers in `taskiq_messages` forever.

→ Worker-startup sweep (`_sweep_stale_queue`): `DELETE FROM
taskiq_messages` at `WORKER_STARTUP`. Consumed rows are already
ack-deleted, so the sweep loses nothing but unprocessed ghosts; the data
catches up via the next cron tick (≤ 5 min). The task never runs, but the
outcome (a sync) does. Keep alembic away from that table — taskiq-pg
manages it inside the windiq DB, outside migrations.

## Restart hygiene

- **No replay of the startup backfill** once the store is covered: the gate
  checks `MIN(timestamp) < now() − 350 d` (history complete) **and**
  `MAX(updated_at) ≥ now() − 48 h` (fresh forward progress). Restarts stay
  visible in `docker compose ps`/logs, not as `ingest_runs` noise; a wiped
  DB or a crashed first backfill fails one of the two and retriggers.
- **Idempotency underneath:** watermark `MAX(updated_at) − 1 h` overlap +
  guarded upserts make replays (crash mid-run, cursor invalidation, double
  cron/manual runs) harmless — the replay is a no-op `(0, 0)` or a retry.
- **No concurrent runs:** `pg_try_advisory_lock` around the sync body; a
  cron run and a manual run never overlap — the latecomer logs `skipped`
  and exits.
- **DB connection hygiene:** `pool_pre_ping` + `pool_recycle` (30 min) —
  a `db` restart drops stale pooled connections instead of erroring one
  request per pool slot.
- **SIGTERM:** taskiq drains the in-flight task before the container exits.

## Failure → outcome table

| Scenario | Outcome |
| --- | --- |
| Worker container down | scheduler keeps ticking, messages linger; sweep discards them at restart; next cron tick ≤ 5 min compensates |
| Scheduler container down | no cron for the window; staleness grows; no backlog to catch up — the next tick resumes at `MAX(updated_at) − 1 h` |
| `backend` down | SPA stale (front polls every 60 s), but worker/scheduler unaffected |
| `db` down | everything stalls; healthchecks + health endpoint surface it; named volume survives rebuilds; pool recovers via `pre_ping` |
| WindIQ API flaky (429/5xx, latency) | facade retries with backoff/`Retry-After`; after 4 attempts the run journals `error` and the next cron tick retries the window |
| Worker crash mid-task | run rolls back wholesale, journals `error` in its own transaction; restart → sweep + gated startup |
| "Sync now" while worker down | POST returns `{queued: true}`, badge persists until the next newer run after recovery (≤ 5 min) |
| Task queued exactly during the sweep | acceptable: same cron compensation as above |
| Malformed source row | dead-lettered loudly, NULL stored — one bad row never poisons a page |

## Dashboard degradation (SPA)

- **Per-panel state:** all four GETs poll independently (60 s, paused while
  the tab is hidden, refetch on visibilitychange) — one endpoint failing
  does not blank the page; each panel keeps its own loading/error state.
- **Stale beats blank:** a failed refresh keeps the previous data visible;
  only a first-load failure shows the inline retry.
- **Honest staleness:** data older than `STALE_AFTER_SECONDS` (3 h) is
  flagged in the status panel — a silent worker failure looks loud.
- **"Sync now" is optimistic but truthful:** the queued badge clears only
  when a newer `ingest_runs` row appears, never on its own timer.

## Delivery / deployment

- CI runs the backend suite against a real Postgres 17 and builds both
  images; only then does `deploy.yml` push to GHCR and ping the Coolify
  webhook.
- prod compose uses `pull_policy: always` — plain `docker compose up -d`
  would otherwise redeploy a stale cached `:latest`.
- Rollback path: `sha-<commit>` image tags; pin the tag in
  `docker-compose.prod.yml` and `compose up -d`.
- Deploy never touches the `windiq-pgdata` volume.

## Visibility

- `ingest_runs` is the ops journal (status ok/partial/error, counts, max
  gap, detail); `NullResultBackend` because nobody polls task results — the
  journal is the source of truth.
- `/api/health`: DB ping + last run + `max(measurements.updated_at)`
  staleness → the dashboard status panel turns amber/gray; worker/scheduler
  failures surface as staleness, not as a traffic error. The endpoint never
  crashes — every failure is caught and reported (`degraded`), which is
  what the Docker healthcheck depends on.
- Each cycle carries a `run=<id>` marker through api/worker/scheduler logs;
  `docker compose logs` + `docker compose ps` are the debugging entry points.
- A "sync now" queued during downtime is a known no-op (sweep) — the
  expectation is documented in [operations.md](operations.md).

## Known limits

- **`worker`/`scheduler` have no Docker healthchecks** (fast volumes: the
  API runs on uvicorn only). Their failure signals indirectly via data-age
  staleness in `/api/health` and the status panel — deliberate, one signal
  instead of three.
- **One transaction per run** keeps the backfill all-or-nothing: a mid-run
  crash re-fetches all pages next run (cheap → the run takes ~8 s).
- **No external alerting** — staleness lives in the dashboard only; nobody
  gets pinged when the worker dies unattended.

## Tests

`test_worker.py`: sweep + gate orchestration (window covered → no journal
row), task smoke, schedule source shape; `test_ingest.py`: idempotent
backfill, watermark + overlap, lock skip; `test_retry.py`: transient
classification, backoff/`Retry-After` cap; `test_qc.py`: property-based
rules.
