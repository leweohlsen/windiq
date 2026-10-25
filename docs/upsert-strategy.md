# Upsert strategy — idempotent ingest with "latest revision wins"

Status: 2026-10-25 · Code: `backend/app/db/repo.py` (`_upsert_stmt`, `upsert_measurements`,
reference upserts) + `backend/app/ingest/common.py` (`ingest_page`)
Evidence: quirks 6–8 (duplicates, revisions), B2/B6 (inclusive `since`, change-watermark)

## Why upserts at all

The ingest never "inserts fresh data": every source — the full backfill, the
watermark sync with its 1 h look-back overlap, and a manual `POST /api/ingest/run`
(quoted cron runs included) — can deliver rows we already have. One row shape and
one conflict rule make **every** caller idempotent:

```
INSERT … ON CONFLICT (mast_id, timestamp) DO UPDATE SET …
       WHERE measurements.updated_at < EXCLUDED.updated_at
```

This is the single load-bearing decision. It turns "don't corrupt data on replay"
from a caller discipline into a **DB-level property**: a latecomer, a lagging page
or a whole re-run simply cannot overwrite newer data, no matter how buggy the
fetch loop is.

## Conflict key

`(mast_id, timestamp)` is the primary key of `measurements`; `timestamp` is the
canonical UTC hour (timezone suffixes normalized at ingest, see qc.py). Two
source rows for the same hour — the `Z`/`+00:00` byte-identical duplicates
(quirk 6) — collapse onto one key deterministically.

## The `updated_at` guard

The `ON CONFLICT DO UPDATE` carries one extra guard clause,
`WHERE measurements.updated_at < EXCLUDED.updated_at`:

| Situation | Stored `updated_at` vs incoming | Effect |
| --- | --- | --- |
| New hour | row absent | INSERT → `(1, 0)` |
| Newer revision arrives | stored < incoming | UPDATE → `(0, 1)` |
| Exact replay (or 1 h overlap re-reading) | stored = incoming | **skipped** → `(0, 0)` |
| Stale latecomer (older sync page after newer sync) | stored > incoming | **skipped** → `(0, 0)` |
| Same `updated_at`, different value (ordering tie) | stored = incoming | **skipped**, first stored version wins |

Equal `updated_at` means "same revision": the observably tied rows are
byte-identical (quirk 6), and replaying the *newest* row first is guaranteed by
the in-batch reduction below. A tie with *conflicting* values would be an API
contract change; skipping the second row is the conservative outcome and shows
up in `ingest_runs.inserted/updated` staying lower than expected — visible,
not corrupt.

Why `updated_at` and not `version` is the guard column: `version` distinguishes
revisions (quirk 8) but is not globally ordered across rows, while `updated_at`
is the change-ordering the API itself uses for `updated_since` (quirk B6) — one
column serves both the sync watermark and the upsert guard.

## Two statements (and one Python step) per ingest burst

### 1. In-batch dedupe (Python, `upsert_measurements`)

Postgres forbids touching the same conflict row twice in one statement — a
batch containing the same `(mast_id, timestamp)` twice with different revisions
would abort the whole batch. The rows are first reduced to the newest revision
per key:

```python
keyed[key] = row if row["updated_at"] >= previous["updated_at"] else keyed[key]
```

This also makes the run's `(inserted, updated)` numbers stable no matter how the
API splits pages. A one-hour key collision across *pages* (B6 says none occur
today) is still safe: page 2's upsert sees page 1's committed row.

### 2. Statement-batched ON CONFLICT (batch_size = 1000)

One parameterized statement per 1000 rows keeps round trips low; the API's
500-row pages mean a statement per page in practice.

### 3. `(inserted, updated)` accounting via `xmax`

```sql
RETURNING (xmax = 0) AS fresh
```

`xmax = 0` marks rows freshly inserted (a row updated in this statement has a
nonzero xmax), and rows skipped by the guard produce **no output row at all** —
so inserted vs updated vs silent skips fall out of a single query, with no extra
post-comparison `SELECT` needed. These counters land in `ingest_runs` and are
what makes the "repeated full backfill is byte-identical" acceptance check a
plain `inserted == 0 AND updated == 0` assertion.

## What is *not* touched on conflict: `fetched_at`

The `set_` clause covers every column **except `fetched_at`** — it always keeps
its DB default and answers "when did WE last read this hour?", independent of
when the API last changed the value. A replayed row keeps `fetched_at`
advancing (it's re-read) but the data columns stay frozen by the guard.

## Reference data — same pattern, one asymmetry

Every sync run refreshes all three reference singletons. Turbine and site use
the same `updated_at`-guarded upsert as `measurements`; **`mast` is the
exception**: it carries neither `version` nor `updated_at`, so its upsert is
unconditional — a uniform guard pattern would silently skip it forever
(reference-data asymmetry, quirks doc).

| Table | Guard | Notes |
| --- | --- | --- |
| `turbine` | `updated_at <` | On change: `power_curve_points` deleted + refilled — the curve is a child table, not upserted point-by-point |
| `site` | `updated_at <` | Losses flattened from `site.losses.*` |
| `mast` | — (none) | Unconditional `ON CONFLICT DO UPDATE` |

The QC upper bound (`cut_out` + margin) is read **from the DB turbine row**
(`get_cut_out`), never hardcoded — a refreshed turbine version moves the QC
bound with the reference data.

## Failure interactions this buys us

| Scenario | Outcome |
| --- | --- |
| Backfill replayed after a crash mid-run | remaining pages fill the holes; finished pages count `(0, 0)` |
| Cron run + manual `POST /api/ingest/run` five seconds apart | advisory xact lock makes the latecomer exit with `skipped` before touching data; even *without* the lock the upserts would merge harmlessly |
| Sync overlap re-reads a row revised in the meantime | newer revision overwrites; unchanged rows skipped |
| Cursor invalidated mid-backfill → restart page loop from the beginning | replay of finished pages is a no-op |
| Two different source rows for one UTC hour (suffix quirk 6) | one key, in-batch revision reduction inserts the newest |

## Test coverage

- `backend/tests/test_db.py`
  `test_upsert_precedence`, `test_upsert_batch_counts_and_persistence`,
  `test_upsert_dedupes_within_batch`, `test_quality_check_constraint` —
  an older `updated_at` **must never** overwrite (`== (0, 0)` counting)
- `backend/tests/test_ingest.py`
  `test_backfill_is_idempotent` (replay = byte-identical, `(6,1)` → `(0,0)`),
  `test_sync_uses_watermark_window_and_overlaps`, `test_locked_run_is_skipped`
- Property-based QC rules (which feed these rows): `tests/test_qc.py`
