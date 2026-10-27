"""QC at ingest: only valid hours in the store, qc_note as quality surface

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The same set-based fill the ingest pipeline runs (app/db/repo.py
# `interpolate_gaps`, mirrored here to keep this migration self-protecting)
# over an empty defect table: it interpolates every hour the legacy regime
# had rejected and stamps the historic rows with a migration note.
_FILL_GAPS = """
WITH bounds AS (
    SELECT MIN(timestamp) AS lo, MAX(timestamp) AS hi FROM measurements
), hours AS (
    SELECT generate_series(lo, hi, interval '1 hour') AS ts FROM bounds
), targets AS (
    SELECT h.ts FROM hours h
      LEFT JOIN measurements m ON m.timestamp = h.ts
     WHERE m.timestamp IS NULL
), framed AS (
    SELECT t.ts                   AS ts,
           lag_m.wind_speed_ms    AS v_from,
           lag_m.timestamp        AS t_from,
           lead_m.wind_speed_ms   AS v_to,
           lead_m.timestamp       AS t_to,
           lag_m.wind_dir_deg     AS dir_from,
           lead_m.updated_at      AS edge_updated_at,
           lead_m.version         AS edge_version
      FROM targets t
      LEFT JOIN LATERAL (
           SELECT * FROM measurements
            WHERE timestamp < t.ts
            ORDER BY timestamp DESC LIMIT 1) lag_m ON true
      LEFT JOIN LATERAL (
           SELECT * FROM measurements
            WHERE timestamp > t.ts
            ORDER BY timestamp ASC LIMIT 1) lead_m ON true
     WHERE lag_m.wind_speed_ms IS NOT NULL
       AND lead_m.wind_speed_ms IS NOT NULL
)
INSERT INTO measurements (mast_id, timestamp, timestamp_raw,
                          wind_speed_ms, unit, wind_speed_raw, wind_dir_deg,
                          quality, qc_note, version, updated_at)
SELECT :mast_id,
       f.ts,
       '',
       f.v_from + (f.v_to - f.v_from)
            * EXTRACT(EPOCH FROM f.ts - f.t_from)
            / EXTRACT(EPOCH FROM f.t_to - f.t_from),
       'm/s',
       '',
       f.dir_from,
       'ok',
       'im Altdatenbestand nicht verwertbar',
       COALESCE(f.edge_version, 0),
       f.edge_updated_at
  FROM framed f
"""


def upgrade() -> None:
    bind = op.get_bind()
    # Legacy rows without a usable value leave the store; their hours are
    # interpolated below (reasons pre-dating the new contract stay generic).
    bind.execute(sa.text("DELETE FROM measurements WHERE quality != 'ok'"))
    op.drop_constraint("measurements_quality_check", "measurements")
    op.drop_constraint("measurements_qc_values", "measurements")

    op.add_column("measurements", sa.Column("qc_note", sa.Text(), nullable=True))

    mast_id = bind.execute(sa.text("SELECT mast_id FROM site LIMIT 1")).scalar()
    if mast_id is not None:
        bind.execute(sa.text(_FILL_GAPS), {"mast_id": mast_id})

    op.alter_column("measurements", "wind_speed_ms", nullable=False)
    # the energy views already read the hourly rows they can — rebuild them
    # without the quality filter before the column is gone
    op.execute("DROP VIEW IF EXISTS daily_energy;")
    op.execute("DROP VIEW IF EXISTS hourly_energy;")
    op.drop_column("measurements", "quality")
    op.drop_column("measurements", "unit")
    op.create_index("ix_measurements_timestamp", "measurements", ["timestamp"])

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

    op.drop_column("ingest_runs", "qc_missing")
    op.drop_column("ingest_runs", "qc_suspect")
    op.drop_column("ingest_runs", "qc_malformed")
    op.add_column(
        "ingest_runs",
        sa.Column("interpolated", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("ingest_runs", "interpolated")
    for name in ("qc_missing", "qc_suspect", "qc_malformed"):
        op.add_column(
            "ingest_runs",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )

    op.add_column(
        "measurements",
        sa.Column("quality", sa.Text(), nullable=False, server_default="ok"),
    )
    op.add_column(
        "measurements", sa.Column("unit", sa.Text(), nullable=False,
                                  server_default="m/s", )
    )
    # Interpolated rows have no place in the legacy regime
    op.execute("DELETE FROM measurements WHERE qc_note IS NOT NULL")
    op.drop_column("measurements", "qc_note")
    op.drop_index("ix_measurements_timestamp", table_name="measurements")
    op.alter_column("measurements", "wind_speed_ms", nullable=True)

    op.execute("""
        CREATE OR REPLACE VIEW hourly_energy AS
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

    op.create_check_constraint(
        "measurements_qc_values",
        "measurements",
        "(quality = 'ok' AND wind_speed_ms IS NOT NULL AND wind_speed_ms >= 0)"
        " OR (quality IN ('missing','malformed') AND wind_speed_ms IS NULL)"
        " OR quality = 'suspect'",
    )
    op.create_check_constraint(
        "measurements_quality_check",
        "measurements",
        "quality IN ('ok','suspect','missing','malformed')",
    )
