# WindIQ Measurements-API — Quirks (data quality findings)

Status: re-probe 2026-10-25 (fresh full pull over the client facade `app/windiq/client.py`),
supersedes the approximate numbers of the first exploration. **The API serves a sliding 1-year
window**, so every count below will drift — treat them as shapes and patterns, not constants.

Data basis of the re-probe: 18 pages · 8,704 rows received · 8,685 distinct UTC hours ·
range `2025-10-25T20:00Z … 2026-10-25T19:00Z` · 75 missing hours in range · 4 gaps
(worst: 72 h starting `2026-04-09T23:00Z`).

## Row-content quirks

| # | Quirk | Evidence (re-probe) | Consequence for the pipeline |
| --- | --- | --- | --- |
| 1 | `wind_speed` is a union type in JSON | 8,641 × float · 30 × `null` · 33 × numeric string (`"7.47"`); all string values are valid decimals | Validation must branch on the **input shape** first; server/ORM cannot be trusted to coerce |
| 2 | Two different negative patterns | sentinel `-999.0` exactly (no-data), plus small drift values `-0.22 … -2.89` (sensor noise) | Sentinel → `missing`, other negatives → `suspect` — they mean different things |
| 3 | Extreme outliers | 22 rows > 25 m/s, max 83.07 m/s (turbine cut-out is 25 m/s) — e.g. `2025-12-07T15:00Z`, 72.72 m/s | Physically implausible → `suspect`; upper bound derived from the turbine envelope, not hardcoded |
| 4 | Mixed units | `m/s`: 8,355 · `km/h`: 349 (block in December 2025) | Normalize to m/s at ingest, keep `unit` and raw value for audit |
| 5 | Mixed timezone suffixes in `timestamp` | `Z`: 7,965 · `+02:00`: 720 · `+00:00`: 19 | Normalize to UTC (`timestamptz`); suffix is the publication detail only |
| 6 | Exact duplicate hours under different suffixes | the 19 `+00:00` rows duplicate `Z` hours **byte-identically** (same wind speed, same `version`, same `updated_at`) | UTC key collapses them deterministically; last-write-wins upsert safe even on `updated_at` ties |
| 7 | Corrections arrive as new versions | `version` v1: 7,045 · v2: 1,604 · v3: 55; max lag `updated_at − timestamp`: 4 d 3 h | Neueste-Version-wins upsert guarded by `updated_at` |
| 8 | `updated_at` is *not* a correction signal per row | 8,686 of 8,704 rows have `updated_at` minutes after `timestamp`; only `version` distinguishes revisions | Don't filter "suspiciously fresh" rows by lag; rely on `version`/`updated_at` ordering |
| 9 | Missing hours / large gaps incl. the live edge | 75 missing hours; today alone already had 3 single-hour holes at 09/14/17 UTC that later filled in | The latest fetched hour is **provisional** — the sync watermark needs overlap, coverage must be computed at runtime |
| 10 | `wind_direction_deg` is well-behaved | 325 distinct integer degrees, all within [0, 360] | Only range validation, no coercion needed; treat out-of-range as `malformed` anyway |

## Query / behavior quirks

| # | Observation | Consequence |
| --- | --- | --- |
| B1 | `limit > 500` → 422 `less_than_equal[le=500]` | Clamp `limit` inside the facade; never pass caller-supplied values through |
| B2 | `since` is **inclusive** — `since = max(timestamp)` returns that exact boundary row | Sync/backfill must expect +1 row overlap at the boundary; harmless via idempotent upsert |
| B3 | `since='not-a-date'` → 422 (server-side datetime parse) | Facade may pass datetime objects only; no string hand-crafting in callers |
| B4 | `since` in the far future → 200 with 0 rows, `next_cursor = null` | Clean empty-page behavior, no special-casing needed |
| B5 | Pagination has no overlap and chains cleanly (`limit=100`, page1/page2 share 0 timestamps) | Cursor walk needs no dedupe across pages — but dedupe within a batch is still required because of quirk 6 |
| B6 | `updated_since` returns only rows changed since the watermark, sorted by change time | Periodic sync via change-watermark instead of full scan; keep a ≥ 1 h overlap for quirk 9 |
| B7 | Rows are delivered sorted by `timestamp` | No resort needed; a validator may still assert monotonicity as a soft invariant |

## Reference-data asymmetry

- `Turbine` (v43) and `Site` (v44) carry `version` + `updated_at` → upsert-guarded refresh.
- **`Mast` has neither `version` nor `updated_at`** → its upsert must be unconditional;
  a uniform guard pattern would silently skip it.

## Statistical drift warning (sliding window)

Between the first exploration and this re-probe (both 2026-10-25, hours apart):

- worst gap changed 47 h → 72 h (the window slid past a data hole)
- numeric-string count 34 → 33
- km/h block now 349 rows

Consequence: **no hardcoded row counts, gap sizes or anomaly totals in tests or code.**
Tests must be property-based (rule coverage), and all coverage statistics must be computed
at query time.

## Agreed QC contract (decisions 2026-10-25)

| Decision | Rationale |
| --- | --- |
| `-999.0` sentinel → `quality='missing'`, `wind_speed_ms = NULL` | Sentinel means "no data"; small negatives stay `suspect` |
| Numeric strings that parse cleanly (`"7.47"`) → `quality='ok'` | Value is plausible; only the type was sloppy — excluding the hour would corrupt energy stats for no data reason |
| Plausibility upper bound = turbine `cut_out` + margin (from DB, versioned) | Moves with the reference data instead of a magic 25/40 m/s constant |
| Persist `timestamp_raw` (original string with suffix) | 1 column; keeps the `+00:00`/`Z` dupe evidence auditable and re-derivable |
| Unit whitelist `{m/s, km/h}`, unknown unit → `malformed` | Fail typed at parse time instead of mid-pipeline |
| `ingest_runs` gets QC defect counts + max gap per run | A run with > 30 % suspect rows on a page is an API change → status `partial`, not `ok` |
| New rows of unexpected shape (bool, int subtype, dict, …) → `malformed` + explicit unreachable-branch log | Better a loud dead-letter than a silent wrong value |

Schema deltas and the updated QC rule table are tracked in
[implementation-plan.md](implementation-plan.md) (Phase 1 schema deltas, Phase 2 QC rules).
