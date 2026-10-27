"""energy matviews: hourly_energy materialized, daily_energy built on top

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Speed → power interpolation moves out of the plain view (and out of the
# per-row power_at() calls): one row per DISTINCT hub speed, computed once per
# refresh. The lowest-segment-start tie-break matches power_at()'s
# ORDER/LIMIT, so on-curve speeds produce identical numbers; speeds off the
# curve have no segment and stay NULL (power_at() maps them to 0 — for SUM
# the two are the same). `day` (UTC) moves here as well.
_HOURLY_ENERGY_MATVIEW = """
CREATE MATERIALIZED VIEW hourly_energy AS
WITH hourly AS (
    SELECT m.mast_id,
           m.timestamp,
           (m.timestamp AT TIME ZONE 'UTC')::date AS day,
           m.wind_speed_ms  AS speed_mast_ms,
           m.wind_dir_deg,
           m.wind_speed_ms * POWER(t.hub_height_m
                                   / mast.measurement_height_m,
                                   s.shear_exponent) AS speed_hub_ms
      FROM measurements m
      JOIN mast ON mast.id = m.mast_id
      CROSS JOIN turbine t
      CROSS JOIN site s
), segments AS (
    SELECT wind_speed_ms AS ws, power_kw AS kw,
           LAG(wind_speed_ms) OVER (ORDER BY wind_speed_ms) AS ws_prev,
           LAG(power_kw)      OVER (ORDER BY wind_speed_ms) AS kw_prev
      FROM power_curve_points
), speeds AS (
    SELECT DISTINCT ON (d.speed_hub_ms)
           d.speed_hub_ms,
           dt.kw_prev + (dt.kw - dt.kw_prev)
                     * (d.speed_hub_ms - dt.ws_prev) / (dt.ws - dt.ws_prev) AS power_kw
      FROM (SELECT DISTINCT speed_hub_ms FROM hourly) d
      JOIN segments dt
        ON dt.ws_prev IS NOT NULL
       AND dt.ws_prev <= d.speed_hub_ms
       AND dt.ws      >= d.speed_hub_ms
      ORDER BY d.speed_hub_ms, dt.ws
)
SELECT h.mast_id, h.timestamp, h.day,
       h.speed_mast_ms, h.speed_hub_ms, h.wind_dir_deg,
       s.power_kw AS power_kw,
       s.power_kw AS energy_kwh
  FROM hourly h
  LEFT JOIN speeds s ON s.speed_hub_ms = h.speed_hub_ms;
"""

_DAILY_ENERGY_VIEW = """
CREATE VIEW daily_energy AS
SELECT mast_id,
       day,
       SUM(energy_kwh)    AS energy_kwh,
       COUNT(*)           AS hours,
       AVG(speed_mast_ms) AS mean_wind_ms,
       MAX(speed_mast_ms) AS max_wind_ms
  FROM hourly_energy
 GROUP BY mast_id, day;
"""

# The 0003-regime plain views, recreated verbatim for the downgrade path.
_LEGACY_HOURLY_ENERGY_VIEW = """
CREATE VIEW hourly_energy AS
WITH hourly AS (
    SELECT m.mast_id,
           m.timestamp,
           m.wind_speed_ms  AS speed_mast_ms,
           m.wind_dir_deg,
           m.wind_speed_ms * POWER(t.hub_height_m
                                   / mast.measurement_height_m,
                                   s.shear_exponent) AS speed_hub_ms
      FROM measurements m
      JOIN mast ON mast.id = m.mast_id
      CROSS JOIN turbine t
      CROSS JOIN site s
)
SELECT mast_id, timestamp, speed_mast_ms, speed_hub_ms, wind_dir_deg,
       power_at(speed_hub_ms) AS power_kw,
       power_at(speed_hub_ms) AS energy_kwh
  FROM hourly;
"""

_LEGACY_DAILY_ENERGY_VIEW = """
CREATE VIEW daily_energy AS
SELECT mast_id,
       (timestamp AT TIME ZONE 'UTC')::date AS day,
       SUM(energy_kwh)   AS energy_kwh,
       COUNT(*)          AS hours,
       AVG(speed_mast_ms) AS mean_wind_ms,
       MAX(speed_mast_ms) AS max_wind_ms
  FROM hourly_energy
 GROUP BY mast_id, day;
"""


def upgrade() -> None:
    op.execute("DROP VIEW daily_energy;")
    op.execute("DROP VIEW hourly_energy;")
    op.execute(_HOURLY_ENERGY_MATVIEW)
    # Unique index so a later step can run REFRESH ... CONCURRENTLY.
    op.execute("CREATE UNIQUE INDEX ON hourly_energy (mast_id, timestamp);")
    op.execute(_DAILY_ENERGY_VIEW)
    # Fill the matview during migration; the CONCURRENTLY flavor itself is
    # not allowed inside a transaction block, this plain one is.
    op.execute("REFRESH MATERIALIZED VIEW hourly_energy;")


def downgrade() -> None:
    op.execute("DROP VIEW daily_energy;")
    op.execute("DROP MATERIALIZED VIEW hourly_energy;")
    op.execute(_LEGACY_HOURLY_ENERGY_VIEW)
    op.execute(_LEGACY_DAILY_ENERGY_VIEW)
