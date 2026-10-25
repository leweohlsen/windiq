"""persistence layer: reference data, measurements, ingest runs, energy views

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mast",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column("measurement_height_m", sa.Double(), nullable=False),
        sa.Column("operator", sa.Text(), nullable=False),
        sa.Column("commissioned_at", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "turbine",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("rated_power_kw", sa.Double(), nullable=False),
        sa.Column("hub_height_m", sa.Double(), nullable=False),
        sa.Column("rotor_diameter_m", sa.Double(), nullable=False),
        sa.Column("cut_in_wind_speed_ms", sa.Double(), nullable=False),
        sa.Column("cut_out_wind_speed_ms", sa.Double(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "power_curve_points",
        sa.Column("turbine_id", sa.String(), nullable=False),
        sa.Column("wind_speed_ms", sa.Double(), nullable=False),
        sa.Column("power_kw", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(["turbine_id"], ["turbine.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("turbine_id", "wind_speed_ms"),
    )
    op.create_table(
        "site",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mast_id", sa.String(), nullable=False),
        sa.Column("shear_exponent", sa.Double(), nullable=False),
        sa.Column("availability_loss", sa.Double(), nullable=False),
        sa.Column("electrical_loss", sa.Double(), nullable=False),
        sa.Column("wake_loss", sa.Double(), nullable=False),
        sa.Column("uncertainty", sa.Double(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mast_id"], ["mast.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "measurements",
        sa.Column("mast_id", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wind_speed_ms", sa.Double(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("wind_speed_raw", sa.Text(), nullable=False),
        sa.Column("wind_dir_deg", sa.SmallInteger(), nullable=False),
        sa.Column("quality", sa.Text(), nullable=False, server_default="ok"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["mast_id"], ["mast.id"]),
        sa.PrimaryKeyConstraint("mast_id", "timestamp"),
        sa.CheckConstraint(
            "quality IN ('ok','suspect','missing','malformed')",
            name="measurements_quality_check",
        ),
    )
    op.create_index(
        "ix_measurements_updated_at", "measurements", ["updated_at"]
    )
    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("inserted", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("frame_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frame_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Single-turbine case: the interpolation runs over the whole curve table.
    # Below the lowest point and above the last point (cut-out) → 0 kW.
    op.execute("""
        CREATE FUNCTION power_at(v double precision)
        RETURNS double precision
        LANGUAGE sql
        STABLE
        AS $fn$
            SELECT COALESCE(
                (SELECT pts.kw_prev
                        + (pts.kw - pts.kw_prev) * (v - pts.ws_prev)
                          / (pts.ws - pts.ws_prev)
                   FROM (SELECT wind_speed_ms AS ws, power_kw AS kw,
                                LAG(wind_speed_ms) OVER (ORDER BY wind_speed_ms)
                                    AS ws_prev,
                                LAG(power_kw) OVER (ORDER BY wind_speed_ms)
                                    AS kw_prev
                           FROM power_curve_points) AS pts
                  WHERE pts.ws_prev IS NOT NULL
                    AND pts.ws_prev <= v
                    AND pts.ws >= v
                  ORDER BY pts.ws
                  LIMIT 1),
                0::double precision
            )
        $fn$;
    """)
    # Hub-height wind → power curve → kWh (power × 1 h); suspect/missing hours
    # are excluded from energy accounting.
    op.execute("""
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
             WHERE m.quality = 'ok'
        )
        SELECT mast_id, timestamp, speed_mast_ms, speed_hub_ms, wind_dir_deg,
               power_at(speed_hub_ms) AS power_kw,
               power_at(speed_hub_ms) AS energy_kwh
          FROM hourly;
    """)
    op.execute("""
        CREATE VIEW daily_energy AS
        SELECT mast_id,
               (timestamp AT TIME ZONE 'UTC')::date AS day,
               SUM(energy_kwh)   AS energy_kwh,
               COUNT(*)          AS hours,
               AVG(speed_mast_ms) AS mean_wind_ms,
               MAX(speed_mast_ms) AS max_wind_ms
          FROM hourly_energy
         GROUP BY mast_id, day;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS daily_energy;")
    op.execute("DROP VIEW IF EXISTS hourly_energy;")
    op.execute("DROP FUNCTION IF EXISTS power_at(double precision);")
    op.drop_table("ingest_runs")
    op.drop_table("measurements")
    op.drop_table("site")
    op.drop_table("power_curve_points")
    op.drop_table("turbine")
    op.drop_table("mast")
