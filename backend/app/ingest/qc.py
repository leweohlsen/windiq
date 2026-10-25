"""Canonicalization + QC rules for measurement rows.

Turns one API `Measurement` (union-typed value, mixed units, mixed timezone
suffixes) into the one canonical hourly row the DB expects. Evidence for every
rule lives in docs/api-measurements-quirks.md (§Row-content quirks, §Agreed
QC contract). Pure async-free module: no taskiq, no DB.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from wind_iq_measurement_api_client.models import Measurement

log = logging.getLogger(__name__)

OK = "ok"
SUSPECT = "suspect"
MISSING = "missing"
MALFORMED = "malformed"

# Canonical unit factors: canonical value = received value × factor → m/s
UNIT_FACTORS: dict[str, float] = {"m/s": 1.0, "km/h": 1.0 / 3.6}

# "No data" sentinel exactly as received, i.e. before unit conversion (quirk 2)
SENTINEL_RAW = -999.0

# Wind speeds above the turbine envelope are physically implausible;
# the bound moves with the turbine record, this only adds slack (quirk 3)
CUT_OUT_MARGIN_M_S = 3.0


@dataclass(frozen=True, slots=True)
class NormalizedHour:
    """One API row normalized to the DB's canonical hourly shape."""

    timestamp: datetime        # UTC, floored to the measurement hour
    timestamp_raw: str         # original string with suffix (audit)
    wind_speed_ms: Optional[float]
    unit: str
    wind_speed_raw: str
    wind_dir_deg: int
    quality: str
    version: int
    updated_at: datetime

    @property
    def defect(self) -> Optional[str]:
        """QC defect class, or None for an ok row — feeds ingest_runs counters."""
        return None if self.quality == OK else self.quality


def parse_timestamp(raw: str) -> tuple[datetime, bool]:
    """Parse the API timestamp → (UTC datetime floored to the hour, floored?).

    Flags and floors naive timestamps and non-`:00` minutes instead of
    rejecting outright — the hour still exists, it just needs a visible QC mark
    (live edge: rows can arrive with minute offsets during republishing).
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
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def canonicalize_wind_speed(
    value: Any, unit: str, cut_out_ms: float
) -> tuple[Optional[float], str]:
    """QC contract for `wind_speed` → (canonical m/s or None, quality).

    Branches on the input shape first (quirk 1: the union type is not trusted
    to the client stack); returns malformed/missing with `None` so a buggy QC
    rule still hits the DB check wall.
    """
    factor = UNIT_FACTORS.get(unit)
    if factor is None:
        log.warning("unknown unit %r → malformed", unit)
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
        return canonical, SUSPECT        # sensor drift (quirk 2)
    if canonical > cut_out_ms + CUT_OUT_MARGIN_M_S:
        return canonical, SUSPECT        # implausible (quirk 3)
    return canonical, OK


def normalize_measurement(
    row: Measurement, *, mast_id: str, cut_out_ms: float
) -> Optional[NormalizedHour]:
    """Normalize one API row → NormalizedHour, or None when it cannot be keyed.

    Rows with an unparsable timestamp have no UTC key and cannot be stored at
    all; they get dead-letter-logged here and tracked by the caller. Returns
    a defected (not dropped) row for every other input so audit columns stay.
    """
    try:
        timestamp, floored = parse_timestamp(row.timestamp)
    except ValueError:
        log.warning("dead-letter: unparsable timestamp %r", row.timestamp)
        return None

    wind_dir = row.wind_direction_deg
    wind_speed_ms, quality = canonicalize_wind_speed(
        row.wind_speed, row.unit, cut_out_ms
    )

    if not isinstance(wind_dir, int) or isinstance(wind_dir, bool) \
            or not 0 <= wind_dir <= 360:  # noqa: PLR2004 — 360° circle
        log.warning("dead-letter: wind_direction_deg %r out of range", wind_dir)
        wind_dir = 0
        quality = MALFORMED
        wind_speed_ms = None
    elif floored and quality == OK:
        quality = SUSPECT              # floor-and-flag for off-hour stamps

    updated_at = _parse_updated_at(row.updated_at)
    return NormalizedHour(
        timestamp=timestamp,
        timestamp_raw=row.timestamp,
        wind_speed_ms=wind_speed_ms,
        unit=row.unit,
        wind_speed_raw="" if row.wind_speed is None else str(row.wind_speed),
        wind_dir_deg=wind_dir,
        quality=quality,
        version=row.version,
        updated_at=updated_at,
    )
