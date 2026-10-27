# Ingest strategy — triggers, normalization, guarded upserts, journal

Status: 2026-10-26 · expanded from [upsert-strategy.md] (original in git history)
Code: `backend/app/ingest/`, `db/repo.py` (upserts, gate), `app/worker.py` (wiring, sweep, gate)
Evidence: [api-measurements-quirks.md](api-measurements-quirks.md) · ops: [operations.md](operations.md)

## Overview

One run shape for every trigger:

```
 triggers                      one ingest run (one transaction)         storage
 ──────────                    ────────────────────────────────         ────────
 startup backfill   ───┐
   (gated)             │     advisory xact lock ("skipped" if busy)
 cron */5             ─┼──▶  → refresh reference data                    ──▶  guarded upserts
 "Sync now" (POST)     │     → paged fetch → normalize + QA each row     │   (ON CONFLICT +
                       │     → interpolation fill over the whole range   │   updated_at guard)
                                                                ──▶  ingest_runs journal
```

Bugs in any fetch/QA layer can never corrupt stored data — the upsert guard is
the single load-bearing decision. The stored invariant: **every row in
`measurements` has a usable `wind_speed_ms`**; hours rejected at ingest are
filled by linear interpolation with a persisted reason (`qc_note`).

## Triggers

| Trigger | Fetch mode | Notes |
| --- | --- | --- |
| Startup backfill | full window | **gated**: skipped when `ingest_window_covered` (repo) |
| Sync (cron `*/5`) | `updated_since = MAX(updated_at) − 1 h` | watermark is the DB column — no separate state |
| Manual (POST `/api/ingest/run`) | same as sync | `?mode=backfill` forces the full window |

- **Watermark + overlap**: `MAX(measurements.updated_at)` − 1 h; the boundary
  row is returned inclusively (quirks B2), so the overlap re-reads it — replay
  is harmless via the guard.
- **Startup gate (finding 2)**: cheap two-point check — history reached the
  bottom (`MIN(timestamp) < now() − 350 d`) **and** fresh progress
  (`MAX(updated_at) ≥ now() − 48 h`). Covered → skip (no journal noise per
  restart); first run / crashed fill / wipe → backfill runs.
- **Task delivery + sweep (finding 1)**: taskiq-pg delivers only while a worker
  LISTENs; a task queued during downtime lingers in `taskiq_messages` forever
  (NOTIFY lost, no startup replay). At worker start, `DELETE FROM
  taskiq_messages` — rows can only be unprocessed ghosts (consumed ones are
  ack-deleted); data catches up via the next cron tick. Keep alembic away from
  that table.

## Fetching (cursor pagination)

`limit ≤ 500` (facade clamps, server 422s above), `since`/`updated_since`,
cursor loop until `next_cursor = null`, `MAX_PAGES` (10k) breaker. Inclusive
boundary rows and re-looped pages upsert to `(0, 0)`.

## Normalization + QA

Canonical m/s + UTC `timestamptz` key created at ingest (`app/ingest/qc.py`;
full evidence: quirks doc). A row either converts cleanly (stored) or is
*rejected with a defect class* — rejected hours exist as interpolated rows:

| Input | Defect class | `qc_note` after the fill |
| --- | --- | --- |
| `null` / sentinel `−999.0` | `missing` | "kein Messwert geliefert" |
| small negative (drift) | `negative` | "negativer Messwert" |
| > cut-out + margin (read from DB) | `over-cut-out` | "Messwert über Cut-Out" |
| unparseable value, other shapes, bad unit | `malformed` | "unlesbarer Messwert" |
| direction out of range | `malformed-dir` | "unplausible Windrichtung" |
| hour the API never delivered | — | "Stunde nicht geliefert" |
| numeric string / float in range, valid direction | none (stored) | NULL |

The stored contract: rows carry the rejected *originals* as provenance —
`wind_speed_raw`/`timestamp_raw` keep what the API sent, so `wind_speed_raw =
"-999.0"` next to `qc_note` discloses exactly what was interpolated away.
`unit` is gone: values are canonical m/s before storage.

### Interpolation fill (`repo.interpolate_gaps`)

One set-based statement at the end of every ingest, over the **whole stored
range** — self-healing instead of bookkeeping:

- fills hours with no stored row (API never delivered them) between the two
  closest real rows; both anchors missing (store edges) → hour stays absent;
- recomputes interpolated rows whose anchors changed (keeping their note);
- anchors on real rows only (`qc_note IS NULL`), so fills never chain fills;
- writes a defect hour only when its rejected revision is not superseded by
  an already-stored real one (late `ok` revisions re-land via the upsert).

Interpolated rows carry the defect revision's `(updated_at, version)` — safe
for the sync watermark — or the bounding anchor's for never-delivered hours.

### Where the numbers land

- energy/AEP/rose/series queries have **no QC filter at all** — every stored
  row counts;
- the wind panel shows the reason per bucket from `qc_note`, plus the
  rejected original (`wind_speed_raw`) — `wind_series` aggregates both for
  day/week buckets (raws are unit-dependent text as received);
- `ingest_runs.interpolated` counts the hours a run rejected;
- `coverage` reports `absent_hours` (unfillable edges) and
  `interpolated_hours`.

QA is property-tested (`test_qc.py`), the fill integration-tested
(`test_db.py`: fill idempotence, revision supersede, real-beats-interpolated).

## Guarded upsert

```
INSERT … ON CONFLICT (mast_id, timestamp) DO UPDATE SET …
       WHERE measurements.updated_at < EXCLUDED.updated_at
```

Conflict key: `(mast_id, timestamp)` — canonical UTC hour; `Z`/`+00:00`
duplicate rows (quirk 6) collapse deterministically.

For measurements the guard has one relaxation: **any real revision replaces an
interpolated row**, even one replayed with an older stamp the guard would
skip — the stored interpolation is our synthesis, not an API revision, so a
replayed `ok` revision must still win.

| Situation | stored vs incoming `updated_at` | Effect |
| --- | --- | --- |
| New hour | absent | INSERT `(1, 0)` |
| Newer revision | stored < incoming | UPDATE `(0, 1)` |
| Exact replay / overlap re-read | equal | **skipped** `(0, 0)` |
| Stale latecomer | stored > incoming | **skipped** `(0, 0)` |
| Tie with different value | equal | **skipped** — first stored wins (visible via counters, not corrupt) |

`updated_at` over `version` as guard: not globally ordered across rows, but it
is the same column the API orders `updated_since` by (quirk B6) — one column
serves watermark and guard.

**Per burst:**
1. in-batch dedupe to the newest revision per key (Postgres forbids touching
   a conflict row twice per statement) — `(inserted, updated)` stays stable
   across page splits,
2. statement batching (1000/page → effectively one statement per page),
3. `RETURNING (xmax = 0)` → inserted vs updated vs skipped from one query;
   the "repeated backfill is byte-identical" check is a plain `(0, 0)`.

`fetched_at` is never in the `set_` clause — it always answers "when did WE
last read this hour".

**Reference data** — every run refreshes the singletons:

| Table | Guard | Notes |
| --- | --- | --- |
| `turbine` | `updated_at <` | change → `power_curve_points` deleted + refilled |
| `site` | `updated_at <` | losses flattened |
| `mast` | — | no `version`/`updated_at` exists → unconditional upsert, else it would be skipped forever |

The QC bound (cut-out + margin) is read from the DB turbine row — reference
refreshes move the bound with it.

## Journaling (`ingest_runs`)

Every run journals: `ok`/`partial`/`error`, pages, inserted/updated, the
interpolation count, max gap, detail (defect-class breakdown). > 30 % rejected
rows in a page → run `partial` (API change, not bad data). A crash journals `error` in its own transaction (main tx rolls
back). Failures surface in `/api/health` + dashboard; each cycle carries a
`run=<id>` marker through api/worker/scheduler logs.

## Failure interactions

| Scenario | Outcome |
| --- | --- |
| Backfill replayed after crash | pages fill holes; finished pages `(0, 0)` |
| Cron + manual run seconds apart | advisory lock → latecomer `skipped`; upserts would merge harmlessly anyway |
| "Sync now" while worker down | ghost row swept at next start; cron compensates ≤ 5 min |
| Worker restart, window covered | no backfill, no journal row |
| Watermark skips a same-time revision | 1 h overlap re-reads; guard overwrites |
| Cursor invalidated mid-backfill | restart from page 1 → replay is a no-op |
| Two source rows for one UTC hour (quirk 6) | one key, in-batch reduction inserts newest |

## Tests

`test_db.py`: upsert precedence/batch/dedupe, interpolation fill, gate
outcomes · `test_ingest.py`: idempotent backfill (real + interpolated rows),
watermark + overlap, lock skip · `test_worker.py`: sweep + gate orchestration,
task smoke · `test_qc.py`: property-based rules.
