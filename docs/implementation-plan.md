# Implementation Plan — WindIQ Live Revenue Calculation

Status: 2026-10-25 · Phases 1–4 complete (persistence, ingest worker, API,
SPA dashboard — acceptance criteria verified, incl. a live-data smoke);
phase 5 (operations & observability) implemented 2026-10-26 (startup sweep,
backfill gate, run-id logs, ops notes in operations.md).
Budget per assignment: 5.25–6 h (phases 3/4 grew in the dashboard review),
spread over 7 days
Data-basis freshness: quirks re-verified on 2026-10-25 → [api-measurements-quirks.md](api-measurements-quirks.md)

## Goal

A continuously running service (FastAPI + Postgres + React SPA) that pulls hourly
measurement data from the WindIQ mock API, stores it in Postgres, computes the annual
energy production (AEP gross/net, P50, P90) and shows the results on the dashboard.

```
WindIQ API ──cursor pagination──▶ Ingest worker (taskiq) ──upsert──▶ Postgres ──views──▶ /api/* ──▶ SPA (nginx)
                                  backfill + sync         measurements, reference data,
                                  ▲                       quality flags        revenue, P50/P90, charts
                                  └─ triggered via taskiq-pg broker (Postgres LISTEN/NOTIFY):
                                     cron (*/5) · POST /api/ingest/run ("sync now")
```

## Architecture decisions

Summary only; rationale and history are tracked in [decisions.md](decisions.md).

| Topic | Choice |
| --- | --- |
| Database | PostgreSQL 17, own container, named volume |
| ORM | SQLAlchemy 2.0 (async) + asyncpg, Alembic migrations |
| Measurement model | One row per hour, **latest revision wins** (no version history) |
| Time & units | `timestamptz` (UTC) and m/s — canonical value is created **at ingest time** |
| Data quality | Raw value + quality flag is kept; sentinel −999 → `missing`, small negatives → `suspect`; `ok` rows are DB-CHECK-guarded; suspect hours are excluded from energy sums |
| Aggregation | Plain SQL views, no materialized rollups (~8.7k rows/year) |
| Ingest trigger | taskiq + `taskiq-pg` (Postgres doubles as broker, no Redis); separate `worker` + `scheduler` containers; cron `*/5` plus on-demand `POST /api/ingest/run` |

All of these are grounded in the live data exploration ([api-measurements-quirks.md](api-measurements-quirks.md)).

## Phase 1 — Persistence layer (~1 h) — done 2026-10-25

### Dependencies (`backend/pyproject.toml`)

`sqlalchemy>=2.0[asyncio]`, `asyncpg`, `alembic` (plus transitive `greenlet`),
`taskiq`, `taskiq-pg`, `taskiq-scheduler` (ingest worker, phase 2).

### Backend modules

- `backend/app/db/engine.py`
  - async engine + session factory from `DATABASE_URL`
    (`postgresql+asyncpg://windiq:…@db:5432/windiq`)
  - small connection pool (2–5)
  - `ping()` helper for the readiness part of `/api/health`
- `backend/app/db/models.py` — SQLAlchemy models matching the schema below
- `backend/app/db/repo.py` — repository functions:
  - `upsert_measurements(rows)`: batched
    `INSERT … ON CONFLICT (mast_id, timestamp) DO UPDATE SET … WHERE measurements.updated_at < EXCLUDED.updated_at`
    → idempotent, latest revision wins, older sync runs can never overwrite newer values
  - reference-data upserts with the same `updated_at` guard — **mast is the exception**:
    it carries no `version`/`updated_at`, so its upsert is unconditional
    (see [api-measurements-quirks.md](api-measurements-quirks.md) → reference-data asymmetry)
  - read helpers for the later API endpoints: `latest_measurement`, `aep_trailing_12m`,
    `daily_series`, `coverage`, `ingest_health`
- Alembic (async template) with an initial migration: tables + views

### Schema (migration DDL)

```sql
-- reference data (singletons, refreshed on each sync, guarded by updated_at)
mast      (id PK, name, lat, lon, measurement_height_m, operator, commissioned_at)
turbine   (id PK, name, rated_power_kw, hub_height_m, rotor_diameter_m, cut_in/out, version, updated_at)
power_curve_points (turbine_id FK, wind_speed_ms, power_kw)    -- 26 points, 1 m/s raster
site      (id PK, mast_id, shear_exponent α, availability_loss, electrical_loss, wake_loss,
           uncertainty U, version, updated_at)

-- core table: measurements
measurements (
  mast_id        TEXT         NOT NULL REFERENCES mast(id),
  timestamp      TIMESTAMPTZ  NOT NULL,        -- UTC, start of the measurement hour
  timestamp_raw  TEXT         NOT NULL,        -- original string (suffix evidence; see quirks doc #5/#6)
  wind_speed_ms  DOUBLE PRECISION NULL,        -- canonical: unit-normalized, string→float;
                                                -- NULL if missing/malformed
  unit           TEXT         NOT NULL,        -- as received ('m/s' | 'km/h')
  wind_speed_raw TEXT         NOT NULL,        -- original value (e.g. "-999.0", "7.47"), for audit
  wind_dir_deg   SMALLINT     NOT NULL,
  quality        TEXT         NOT NULL DEFAULT 'ok' CHECK (quality IN ('ok','suspect','missing','malformed')),
  version        INTEGER      NOT NULL,
  updated_at     TIMESTAMPTZ  NOT NULL,
  fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
  PRIMARY KEY (mast_id, timestamp),
  -- quality/value pairings: even a buggy QC rule must hit a DB wall
  CONSTRAINT measurements_qc_values CHECK (
    (quality = 'ok' AND wind_speed_ms IS NOT NULL AND wind_speed_ms >= 0)
    OR (quality IN ('missing','malformed') AND wind_speed_ms IS NULL)
    OR (quality = 'suspect')
  )
)

-- ops journal → feeds /api/health and the "keep operations in view" requirement
ingest_runs (id BIGSERIAL PK, started_at, finished_at, status TEXT, pages INT,
             inserted INT, updated INT, frame_from TIMESTAMPTZ, frame_to TIMESTAMPTZ,
             qc_missing INT, qc_suspect INT, qc_malformed INT, max_gap_hours INT,
             detail TEXT)

-- aggregation in SQL
CREATE FUNCTION power_at(v DOUBLE PRECISION) …   -- linear interpolation over power_curve_points
CREATE VIEW  hourly_energy AS                    -- only quality='ok':
                                                 -- hub speed = v*(hub/mast)^α → power_at → kWh
CREATE VIEW  daily_energy AS                     -- per (mast_id, day): Σ kWh, hour count, mean/max wind
```

### Ops wiring

- `docker-compose.yml` + `docker-compose.prod.yml`: new service `db`
  (`postgres:17-alpine`, `pg_isready` healthcheck, named volume, **no** host port —
  access via `docker compose exec db psql`)
- one-shot `migrate` service (`alembic upgrade head`); `api`, `worker` and `scheduler`
  use `depends_on: migrate: completed_successfully` (with `db: healthy` upstream) —
  avoids a migration race between api and worker
- `.env.example` + `backend/.env`: add `DATABASE_URL`
- extend `/api/health`: DB ping + last `ingest_runs` row + `max(measurements.updated_at)` staleness

### Tests & CI

- unit tests for upsert precedence and schema constraints (an older `updated_at` must never overwrite)
- CI (`ci.yml`, backend job): Postgres service container + `uv run pytest`

**Acceptance criteria:** `alembic upgrade head` then a repeated full backfill produces a
byte-identical row count; `downgrade base` is clean; `/api/health` shows DB status.

### Schema deltas after the quirks re-probe (2026-10-25)

Migration `0001` exists; the re-probe agreed contract adds a **migration `0002`**:

- `measurements`: add `timestamp_raw TEXT NOT NULL` (raw suffix evidence)
- `measurements`: add the `measurements_qc_values` quality/value pairing constraint
  (see DDL above)
- `ingest_runs`: add `qc_missing`, `qc_suspect`, `qc_malformed`, `max_gap_hours`
- `app/db/models.py` + `app/db/repo.py` (`MeasurementRow`) updated accordingly

## Phase 2 — Ingest worker (~1.5 h) — done 2026-10-25

### Modules

- `app/ingest/backfill.py` — one-time full start: persist reference data, then fetch all
  measurements via `GET /v1/measurements?since=…&limit=500` including cursor pagination
  until `next_cursor=null`
- `app/ingest/sync.py` — periodic run:
  `measurements(updated_since=watermark − 1 h overlap, limit=500)` → normalize → upsert
  - watermark = `max(measurements.updated_at)` in the DB (no separate state needed)
  - the 1 h overlap catches late revisions that arrive after the last watermark;
    the upsert guards make replaying those rows harmless
- `app/ingest/qc.py` — canonicalization + QC rules (evidence: quirks doc §Row-content quirks
  and §Agreed QC contract):

  | Input | Rule | Result |
  | --- | --- | --- |
  | `wind_speed: null` | row has no value | `missing`, `wind_speed_ms = NULL` |
  | `wind_speed == -999.0` | sentinel → no data | `missing`, `wind_speed_ms = NULL` (raw kept) |
  | `wind_speed: float` < 0 (small negatives) | sensor drift, not a sentinel | `suspect` |
  | `wind_speed: float` > turbine `cut_out` + margin (from DB) | implausible (real max: 83 m/s) | `suspect` |
  | `wind_speed: float` in range | — | `wind_speed_ms` as float |
  | `wind_speed: str` (numeric) | parse | `wind_speed_ms` as float, **`ok`** |
  | `wind_speed: str` unparseable | — | `malformed`, `NULL` |
  | `wind_speed: other shape` (bool, dict, …) | unreachable branch → loud dead-letter log | `malformed`, `NULL` |
  | `unit: 'km/h'` | ÷ 3.6 | canonical m/s |
  | `unit ∉ {'m/s', 'km/h'}` | — | `malformed`, `NULL` |
  | timezone suffix (`Z`, `+00:00`, `+02:00`) | normalize to UTC | `timestamptz` key; suffix preserved in `timestamp_raw` |
  | naive timestamp / non-`:00` minutes | reject or floor-and-flag | — |

- `app/worker.py` — taskiq wiring; `backfill.py`/`sync.py`/`qc.py` stay pure async
  functions without taskiq imports:

  ```python
  broker = PgBroker(dsn=DATABASE_URL, result_backend=NullResultBackend())

  @broker.task(schedule=[{"cron": "*/5 * * * *"}])   # LabelScheduleSource
  async def periodic_sync() -> None: ...

  @broker.task
  async def run_backfill() -> None: ...

  scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
  ```

- ingestion behavior fixes from the behavior probe (quirks doc §Query/behavior quirks):
  - clamp `limit` to 500 in the facade (server 422s above it)
  - expect `since` to be **inclusive** — boundary row may be redelivered; harmless via upsert
  - status `partial` (not `ok`) whenever a page flags > 30 % `suspect` rows — that is an
    API change, not a data problem
- write `ingest_runs` (status ok/partial/error, pages, inserted/updated, QC defect counts,
  max gap, error detail)

### Scheduler

Separate `worker` and `scheduler` compose services (same image as `api`, different
command); taskiq + `taskiq-pg` — Postgres doubles as the broker, **no Redis**.

- `worker` (`taskiq worker app.worker:broker`): runs `run_backfill()` once at startup
  (idempotent, may be repeated — but see phase 5 → finding 2: gate it once the
  stored window is covered), then executes scheduled and on-demand tasks; drains
  the current run on SIGTERM
- `scheduler` (`taskiq scheduler app.worker:scheduler`): send-only, sends `periodic_sync`
  per cron `*/5 * * * *` (minute-quantized — jitter is irrelevant with a dedicated worker)
- `NullResultBackend`: nobody polls task results; `ingest_runs` is the source of truth
- `pg_try_advisory_lock` around the sync body: a cron run and a manual run never overlap —
  the latecomer logs "skipped, run already active" and exits
- `api` only produces tasks: `broker.startup()` in the FastAPI lifespan, `.kiq()` in the
  trigger endpoint (phase 3)

**Acceptance criteria:** full backfill (≈ 8,700 rows, 18 pages) completes well under 30 s;
repeating it changes nothing; periodic sync uses `updated_since` and stays duplicate-free;
QC tests are **property-based** on the rules above (no hardcoded row counts or gap sizes —
the API window slides, so any count asserted today drifts within a month; quirks doc
§Statistical drift warning); task wrappers smoke-tested with an in-memory broker.

## Phase 3 — API for the SPA (~0.75 h) — done 2026-10-25

- `POST /api/ingest/run` — queues an ingest via `periodic_sync.kiq()`
  (`?mode=sync|backfill` for the full backfill); returns `{queued: true}`
  immediately, no result polling — progress is read from `ingest_runs`
- `GET /api/metrics` — one call for the dashboard header:
  - the revenue chain: AEP gross → net → P50 → P90 (trailing 12 months), window
    range, usable hours (`quality='ok'`) vs. expected hours
  - site/turbine/mast metadata (names, heights, α/availability/electrical/wake
    losses, uncertainty) — powers the header metadata and the methodology blurb
  - staleness of the last ingest (`data_age`, last run status)
  - formulas (per assignment), computed in Python from the DB site parameters:
    `v_hub = v_mast · (h_hub / h_mast)^α` · AEP gross = Σ power_at(v_hub) over 12 months
    · AEP net = gross × (1−availability) × (1−electrical) × (1−wake)
    · P50 = net · P90 = P50 × (1 − 1.282 × U)
- `GET /api/daily?days=90` — daily series for the chart: `energy_kwh`, `hours`,
  `mean_wind_ms` **plus per-day `suspect_hours`/`missing_hours`** (new repo query
  or view extension) so the SPA can color QC marks without a second call;
  `days` capped at 365
- `GET /api/wind?hours=48` — `series` (hourly speed + direction for tooltips) and
  `rose`: 16-sector frequency + mean-speed histogram, precomputed server-side
  over the trailing 30 days of ok hours; `hours` capped at 168
- `GET /api/ingest/runs?limit=10` — last N runs (cap 50) from `ingest_runs`,
  feeds the dashboard history table
- plain pydantic response models; no auth (SPA same-origin via the nginx proxy)

New repo helpers: `ingest_runs_recent(limit)`, `wind_series()`, `wind_rose()`;
`daily_series()` gains the QC columns. P50/P90 math stays in Python — easy to
property-test.

**Acceptance criteria:** endpoints return values consistent with the power-curve math;
no N+1 query loops; staleness info is exposed; the rose histogram matches a
hand-computed sector count.

### Implementation deltas (2026-10-25)

- All responses are pydantic models (`app/api.py`) — the SPA contract mirrored
  1:1 in `frontend/src/api.ts`; the MVP slice's dict endpoints were folded in.
- `daily_series` gained the QC columns as a **repo query** (ok-hours
  aggregation left-joined with per-day QC counts; no view change, no
  migration). Days without ok hours appear with `energy_kwh = NULL` — the SPA
  draws them as gaps.
- Coverage renamed/extended: `bad_hours` → split into `missing_hours`
  (sentinel rows) + `malformed_hours`; span holes (`missing_hours` before) →
  `absent_hours`; added whole-window `max_gap_hours`. `staleness.last_run`
  carries the full run row (frame, QC counts, gap) for the status panel.
- Wind rose: **direction-centered** sectors `ROUND(deg / 22.5) % 16` (360°
  wraps back to N) over the trailing 30 days; all 16 sectors always present
  (0 frequency when empty). A FLOOR-left-edge binning was rejected — 30° maps
  to NNE, not NE.
- Broker wiring: FastAPI lifespan starts/stops the taskiq broker; the POST
  endpoint only sends a task (`kiq()`), `{queued: true}` immediately.

## Phase 4 — SPA dashboard (~2 h) — done 2026-10-25

Recharts for all charts; plain CSS/component layout, no CSS framework. Six panels
(signed off in the 2026-10-25 dashboard review):

- **Header** — two stat cards **P50** and **P90** (MWh); plus gross/net AEP,
  measurement range, usable vs. expected hours, site metadata
- **Daily chart** — `ComposedChart`: bars = daily energy (MWh), line = mean wind
  (m/s) on a second y-axis, tooltip shows hours + QC counts; per-bar QC coloring
  via `Cell`: primary = clean day, amber = suspect hours present, gap = day absent
  (no ok hours); range switcher 30/90/365 days
- **Wind panel** — wind rose as `RadarChart` over the 16 server-computed
  sectors (frequency in radius, bearing-mapped spokes, ok-hours tooltip) +
  a plain 48 h speed line (`LineChart`); direction appears only in the rose
- **Data status** — last `ingest_runs` entry (status pill, finished at, duration,
  inserted/updated, QC counts), data age with warning state past a threshold,
  coverage %, missing/suspect/malformed totals, max gap, "sync now" button →
  `POST /api/ingest/run` (optimistic "queued…" until the next poll shows a new run)
- **Ingest history** — table of the last 10 runs from `GET /api/ingest/runs`
- **Methodology** — static blurb with the formulas; loss factors (α, availability,
  electrical, wake, U) come live from `/api/metrics`

- data fetching: one polling hook fetches all four GETs in parallel every 60 s
  (paused when `document.hidden`), plus a manual refresh button; per-panel
  loading/error states
- units: fixed — energies (daily and yearly AEP/P50/P90) → MWh, fixed decimals
- if the budget runs tight, cut here (in order): rose → plain frequency table
  (~30 min saved), methodology → one static paragraph (~15 min)

**Acceptance criteria:** the dashboard shows realistic values after the backfill;
if the ingest worker stops, the staleness is visibly surfaced; the range switcher
works; all six panels render sensibly also with empty/degraded data.

### Implementation deltas (2026-10-25)

- One polling hook (`useDashboard.ts`) refetches all four GETs in parallel
  every 60 s (paused while `document.hidden`); per-panel loading/error state —
  stale data stays visible when a refresh fails, a failed first load shows
  retry inside the panel. Panels live in `src/components/`.
- Daily chart colors bars via `Cell`: blue = clean day, amber = suspect hours
  present, gray = day absent (`energy_kwh NULL`); tooltip shows ok hours + QC
  counts; range switcher 30/90/365.
- Wind rose as `RadarChart` (Recharts) over the 16 server sectors: numeric
  angle axis (`dataKey="bearing"`, domain 0–360, 22.5° ticks) so every spoke
  sits on its exact compass bearing — 0° N on top, clockwise; radius encodes
  ok-hours. (First attempt used `RadialBarChart`, which renders one concentric
  ring *per data row*, not sectors — rejected as the wrong chart type.
  Category-type angle axes land off-center via a d3 band scale — also rejected.)
- "Sync now" sets an optimistic `queued…` badge, cleared when the next poll
  shows *any* run started after the click — with the worker down the badge
  persists and the staleness panel carries the signal (phase 5 finding).

## Phase 5 — Operations & observability (rest of budget) — done 2026-10-26

- structured logs (uvicorn/taskiq stdout) with a run id per ingest cycle — ties `api`,
  `worker` and `scheduler` log lines together; errors surfaced in `/api/health`
- taskiq-pg hygiene from the findings below: worker-startup sweep of stale
  `taskiq_messages` rows (finding 1) + gate the startup backfill on covered
  windows (finding 2)
- ops notes: "sync now" semantics during worker downtime (badge clears
  with the next newer run after recovery — finding 3) and the pg_dump recipe
- keep the Coolify pipeline as is (CI builds images, deploy webhook pulls); do **not**
  drop the `db` volume during rebuilds
- "operations in view": `/api/health` green after > 24 h unattended runtime,
  `ingest_runs` table as the ops log, `docker compose logs` for debugging

### Findings from the phase 3/4 session (2026-10-25) — addressed here

1. **taskiq-pg delivers only while a worker is LISTENing.** A message queued
   during worker downtime (manual "sync now", or cron sent by the scheduler)
   lingers in `taskiq_messages` forever: the INSERT-time NOTIFY is lost and a
   worker restart does *not* replay the table (no startup poll). Verified
   live: re-`NOTIFY taskiq, '<id>'` while a worker ran → the worker consumed
   the row, executed the sync and ack-deleted it.
   → **Worker-startup sweep**: `DELETE FROM taskiq_messages;` at
   `WORKER_STARTUP`. Rows can only linger unprocessed (consumed ones are
   ack-deleted by the broker), so the sweep loses nothing but ghosts; the
   data itself catches up via the next cron tick (≤ 5 min). A race with an
   enqueue landing exactly during the sweep is acceptable for the same
   reason. Keep alembic far away from that table.
2. **The worker replays the full startup backfill on every container
   start** — idempotent (~8 s, guarded upserts) but writes one `ingest_runs`
   row per start (the smoke session left three). → **Gate it**: skip the
   startup backfill when the store already reflects a complete ingest —
   cheap check: `MIN(timestamp) < now() − 350 d` (history reaches back) and
   `MAX(updated_at) ≥ now() − 48 h` (fresh forward progress); a partial or
   crashed first backfill fails one of the two and retriggers as before.
   Restarts stay visible in `docker compose ps`/logs, not as journal noise.
3. **"Sync now" with the worker down**: POST returns `{queued: true}`, the
   optimistic badge persists until the next poll shows *any* newer run — i.e.
   ≤ 5 min after the worker returns (cron compensates). Document this
   expectation in operations.md together with the sweep; staleness + max-gap
   remain the outage signal (finding 1 explains why the queued task itself
   never runs).

**Acceptance criteria (phase 5):** queue a sync with the worker stopped →
restart the worker → `taskiq_messages` is empty after startup, and the next
cron tick journals a normal run; a worker restart with the window covered adds
**no** `ingest_runs` row; `/api/health` stays green over a 24 h unattended run
with cron runs ≤ 5 min apart.

## Budget check

| Phase | Effort | Status |
| --- | --- | --- |
| 1 Persistence layer | ~1 h | done 2026-10-25 |
| 2 Ingest worker | ~1.5 h | done 2026-10-25 |
| 3 API endpoints | ~0.75 h | done 2026-10-25 |
| 4 SPA dashboard | ~2 h | done 2026-10-25 |
| 5 Operations | rest | done 2026-10-26 |
| **Total** | **5.25–6 h** | |

**Risks and mitigations:**
- API misbehaves (429/5xx, latency) — already covered by the existing tenacity facade (`app/windiq/retry.py`)
- cursors possibly invalidated mid-backfill — restart the page loop from the beginning; upserts make replay safe
- watermark skips same-time revisions — the 1 h overlap plus upsert guards handle it
- dashboard lies (e.g. stale pool state) — surfaced via staleness in `/api/health` and the status panel
- `taskiq-pg` is a third-party plugin, less battle-tested than taskiq core — the broker
  seam is thin; a fallback to a plain asyncio-loop container touches none of the ingest modules
- taskiq-pg manages its own jobs table inside the windiq DB — keep alembic autogenerate
  away from it; retention/delivery **verified 2026-10-25**: rows queued without a
  listening worker linger unprocessed (NOTIFY lost) → worker-startup sweep in phase 5
- worker/scheduler crash independently of api — `ingest_runs` staleness in `/api/health`
  and the status panel surface it; a "sync now" queued during downtime never runs but the
  next cron tick after recovery compensates (phase 5 findings)
