"""QC rules — property-based, no hardcoded counts (quirks doc §Statistical drift).

The API window slides; only rule coverage is asserted, never fixed row
counts, gap sizes or anomaly totals.
"""
from datetime import datetime

from hypothesis import assume, given, strategies as st
import pytest

from app.ingest import qc

SENTINEL = -999.0


def make_measurement(wind_speed, unit="m/s",
                     timestamp="2026-10-25T14:00:00Z",
                     updated_at="2026-10-25T14:05:00+00:00",
                     wind_dir=180):
    from wind_iq_measurement_api_client.models import Measurement
    return Measurement(
        timestamp=timestamp, wind_speed=wind_speed, unit=unit,
        wind_direction_deg=wind_dir, version=1, updated_at=updated_at,
    )


def normalize(wind_speed, unit="m/s", cut_out=25.0, **kwargs):
    return qc.normalize_measurement(
        make_measurement(wind_speed, unit, **kwargs),
        mast_id="M", cut_out_ms=cut_out,
    )


CUT_OUT = 25.0
UPPER = CUT_OUT + qc.CUT_OUT_MARGIN_M_S


reasonable_speeds = st.floats(
    min_value=0.0, max_value=UPPER, allow_nan=False, allow_infinity=False
)


@given(st.floats(min_value=-1e4, max_value=-1e-6, allow_nan=False,
                 allow_infinity=False))
def test_small_negatives_are_suspect(value):
    """Negative drift values stay suspect with their canonical value kept."""
    assume(value != SENTINEL)
    row = normalize(value)
    assert row.quality == qc.SUSPECT
    assert row.wind_speed_ms == value
    assert row.defect == "suspect"


def test_sentinel_is_missing():
    row = normalize(SENTINEL)
    assert row.quality == qc.MISSING
    assert row.wind_speed_ms is None
    assert row.wind_speed_raw == str(SENTINEL)


@given(reasonable_speeds)
def test_numeric_strings_are_ok(value):
    """Cleanly parsing in-range numeric strings count as ok (quirk 1, QC contract)."""
    row = normalize(str(value))
    assert row.quality == qc.OK
    assert row.wind_speed_ms == value


@given(st.text(min_size=1).filter(lambda s: not _parseable_number(s.strip())))
def test_unparseable_strings_are_malformed(text_value):
    row = normalize(text_value)
    assert row.quality == qc.MALFORMED
    assert row.wind_speed_ms is None


def _parseable_number(s: str) -> bool:
    try:
        float(s)
    except ValueError:
        return False
    return True


@given(st.sampled_from([True, False, {"v": 1}, [7.0], (2.0,), 3 + 4j]))
def test_unexpected_shapes_dead_letter_to_malformed(value):
    """Unreachable branches (bool, dict, …) can never produce a speed value."""
    row = normalize(value)
    assert row.quality == qc.MALFORMED
    assert row.wind_speed_ms is None


def test_none_is_missing():
    row = normalize(None)
    assert row.quality == qc.MISSING
    assert row.wind_speed_raw == ""


@given(reasonable_speeds)
def test_in_range_floats_are_ok(value):
    # 0 is fine; only strictly negative values are suspect
    row = normalize(value)
    assert row.quality == qc.OK
    assert row.wind_speed_ms == value


def test_above_cut_out_plus_margin_is_suspect():
    row = normalize(UPPER + 0.01)
    assert row.quality == qc.SUSPECT
    assert row.wind_speed_ms == UPPER + 0.01


@given(reasonable_speeds)
def test_km_h_is_normalized(value):
    row = normalize(value, unit="km/h")
    assert row.quality == qc.OK
    assert row.wind_speed_ms == pytest.approx(value / 3.6)
    assert row.unit == "km/h"


@given(st.sampled_from(["mph", "knots", "", "M/S"]))
def test_unknown_unit_is_malformed(unit):
    row = normalize(10.0, unit=unit)
    assert row.quality == qc.MALFORMED
    assert row.wind_speed_ms is None


# Timestamp normalization (quirk 5): suffix is the publication detail only

UTC = datetime.fromisoformat("2026-10-25T14:00:00+00:00")


@given(st.sampled_from(["Z", "+00:00"]))
def test_utc_suffixes_collapse_to_same_key(suffix):
    row_t = normalize(5.0, timestamp=f"2026-10-25T14:00:00{suffix}")
    row_at = normalize(5.0, timestamp=f"2026-10-25T14:00:00+00:00")
    assert row_t.timestamp == row_at.timestamp == UTC
    assert row_t.quality == qc.OK


def test_offset_suffix_is_normalized():
    row = normalize(5.0, timestamp="2026-10-25T16:00:00+02:00")
    assert row.timestamp == UTC
    assert row.timestamp_raw == "2026-10-25T16:00:00+02:00"


def test_naive_timestamp_floors_and_flags():
    row = normalize(5.0, timestamp="2026-10-25T14:00:00")
    assert row.timestamp == UTC
    assert row.quality == qc.SUSPECT          # floor-and-flag


@given(st.integers(min_value=1, max_value=59))
def test_offhour_minutes_floor_to_the_hour_with_flag(minute):
    row = normalize(5.0, timestamp=f"2026-10-25T14:{minute:02d}:00Z")
    assert row.timestamp == UTC
    assert row.quality == qc.SUSPECT


def test_unparseable_timestamp_is_dead_lettered():
    assert normalize(5.0, timestamp="not-a-date") is None


def test_wind_dir_out_of_range_is_malformed():
    row = normalize(5.0, wind_dir=361)
    assert row.quality == qc.MALFORMED
    assert row.wind_speed_ms is None


def test_version_and_updated_at_pass_through():
    row = normalize(5.0, updated_at="2026-10-25T15:10:00+02:00")
    assert row.version == 1
    assert row.updated_at == datetime.fromisoformat("2026-10-25T13:10:00+00:00")
