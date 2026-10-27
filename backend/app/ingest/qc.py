"""Canonicalization + QA rules for measurement rows.

Turns one API `Measurement` (union-typed value, mixed units, mixed timezone
suffixes) into the one canonical hourly shape the DB expects. Rows failing a
rule carry a **defect** label instead of a value — they are never stored; the
ingest fills their hour by linear interpolation and persists *why* (see
`REASONS`). Evidence for every rule lives in docs/api-measurements-quirks.md
(§Row-content quirks). Pure async-free module: no taskiq, no DB.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from wind_iq_measurement_api_client.models import Measurement

log = logging.getLogger(__name__)

# Defect classes of hours without a usable value (`NormalizedHour.defect`).
MISSING = "missing"           # null value / no-data sentinel
NEGATIVE = "negative"         # sensor drift
OVER_CUT_OUT = "over-cut-out"  # above the turbine envelope (quirk 3)
MALFORMED = "malformed"       # value unusable (shape, NaN, unknown unit)
MALFORMED_DIR = "malformed-dir"  # wind direction out of range

# Human-readable reason an hour had to be interpolated (persisted as `qc_note`
# and shown in the wind panel; small and stable enough to aggregate in SQL).
REASONS: dict[str, str] = {
    MISSING: "kein Messwert geliefert",
    NEGATIVE: "negativer Messwert",
    OVER_CUT_OUT: "Messwert über Cut-Out",
    MALFORMED: "unlesbarer Messwert",
    MALFORMED_DIR: "unplausible Windrichtung",
}
# Hours the API never delivered (gap fill beyond any defect row).
ABSENT_REASON = "Stunde nicht geliefert"

# Canonical unit factors: canonical value = received value × factor → m/s
UNIT_FACTORS: dict[str, float] = {"m/s": 1.0, "km/h": 1.0 / 3.6}

# "No data" sentinel exactly as received, i.e. before unit conversion (quirk 2)
SENTINEL_RAW = -999.0

# Wind speeds above the turbine envelope are physically implausible;
# the bound moves with the turbine record, this only adds slack (quirk 3)
CUT_OUT_MARGIN_M_S = 3.0


@dataclass(frozen=True, slots=True)
class NormalizedHour:
    """One API row normalized to the canonical hourly shape.

    `defect is None` marks a usable (storable) row; otherwise the hour is
    interpolated. The raw columns are audit evidence — for a defected row
    they carry the original (rejected) values, so the interpolation row the
    fill later writes can keep the source provenance.
    """

    timestamp: datetime        # UTC, floored to the measurement hour
    timestamp_raw: str         # original string with suffix (audit)
    wind_speed_ms: Optional[float]     # None iff defected
    wind_speed_raw: str        # original value as received (audit)
    wind_dir_deg: Optional[int]        # None iff direction was defected
    defect: Optional[str]      # defect class, or None for a usable row
    version: int
    updated_at: datetime

    @property
    def reason(self) -> str:
        """qc_note text for an interpolated hour: what was wrong instead."""
        return REASONS.get(self.defect or "", ABSENT_REASON)


def parse_timestamp(raw: str) -> tuple[datetime, bool]:
    """Parse the API timestamp → (UTC datetime floored to the hour, floored?).

    Flags and floors naive timestamps and non-`:00` minutes instead of
    rejecting outright — the minute offset is a live-edge quirk (republishing),
    not bad data: the hour still exists, and the raw string stays as evidence.
    """
    dt = datetime.fromisoformat(raw)
    floored = False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
        floored = True
    dt = dt.astimezone(timezone.utc)
    if (dt.minute, dt.second, dt.microsecond) != (0, 0, 0):
        dt = dt.replace(minute=0, second=0, microsecond=0)
        floored = True
    return dt, floored


def _parse_updated_at(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    return dt.astimezone(timezone.utc) if dt.tzinfo \
        else dt.replace(tzinfo=timezone.utc)


def canonicalize_wind_speed(
    value: Any, unit: str, cut_out_ms: float
) -> tuple[Optional[float], Optional[str]]:
    """QA contract for `wind_speed` → (canonical m/s or None, defect).

    Branches on the input shape first (quirk 1: the union type is not trusted
    to the client stack); a defected hour returns `None` so a buggy rule never
    reaches the DB as a value.
    """
    factor = UNIT_FACTORS.get(unit)
    if factor is None:
        log.warning("unknown unit %r → defected", unit)
        return None, MALFORMED

    if value is None:
        return None, MISSING

    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        # Unreachable server-side per the observed shapes — be loud, not silent
        log.warning(
            "dead-letter: wind_speed has unexpected type %s: %r", type(value), value
        )
        return None, MALFORMED

    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None, MALFORMED

    raw_speed = float(value)
    canonical = raw_speed * factor

    if canonical != canonical:  # NaN cannot reach any comparison below
        log.warning("dead-letter: wind_speed is NaN: %r", value)
        return None, MALFORMED
    if raw_speed == SENTINEL_RAW:
        return None, MISSING             # no-data sentinel (quirk 2)
    if canonical < 0:
        return None, NEGATIVE            # sensor drift (quirk 2)
    if canonical > cut_out_ms + CUT_OUT_MARGIN_M_S:
        return None, OVER_CUT_OUT        # implausible (quirk 3)
    return canonical, None


def normalize_measurement(
    row: Measurement, *, mast_id: str, cut_out_ms: float
) -> Optional[NormalizedHour]:
    """Normalize one API row → NormalizedHour, or None when it cannot be keyed.

    Rows with an unparsable timestamp have no UTC key and cannot be stored at
    all; they get dead-letter-logged here and tracked by the caller. Every
    other input — including defected ones — keeps its audit columns so the
    later interpolation row can carry provenance. `mast_id` is unused inside
    but keeps the normalize signature uniform for the page walker.
    """
    try:
        timestamp, _floored = parse_timestamp(row.timestamp)
    except ValueError:
        log.warning("dead-letter: unparsable timestamp %r", row.timestamp)
        return None

    wind_speed_ms, defect = canonicalize_wind_speed(
        row.wind_speed, row.unit, cut_out_ms
    )
    wind_dir_deg: Optional[int] = None
    if not isinstance(wind_dir := row.wind_direction_deg, int) \
            or isinstance(wind_dir, bool) \
            or not 0 <= wind_dir <= 360:  # noqa: PLR2004 — 360° circle
        log.warning("dead-letter: wind_direction_deg %r out of range", wind_dir)
        # a directionless heading is a defected hour like any other — value out
        defect = defect or MALFORMED_DIR
        wind_speed_ms = None
    else:
        wind_dir_deg = wind_dir

    updated_at = _parse_updated_at(row.updated_at)
    return NormalizedHour(
        timestamp=timestamp,
        timestamp_raw=row.timestamp,
        wind_speed_ms=wind_speed_ms,
        wind_speed_raw="" if row.wind_speed is None else str(row.wind_speed),
        wind_dir_deg=wind_dir_deg,
        defect=defect,
        version=row.version,
        updated_at=updated_at,
    )
