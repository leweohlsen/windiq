"""quirk-driven schema deltas: timestamp_raw, QC pairing check, run QC metrics

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "measurements",
        sa.Column("timestamp_raw", sa.Text(), nullable=True),
    )
    # Existing rows have no suffix evidence left — the UTC key is the next best thing.
    op.execute(
        "UPDATE measurements SET timestamp_raw = timestamp::text"
        " WHERE timestamp_raw IS NULL"
    )
    op.alter_column("measurements", "timestamp_raw", nullable=False)
    op.create_check_constraint(
        "measurements_qc_values",
        "measurements",
        "(quality = 'ok' AND wind_speed_ms IS NOT NULL AND wind_speed_ms >= 0)"
        " OR (quality IN ('missing','malformed') AND wind_speed_ms IS NULL)"
        " OR quality = 'suspect'",
    )
    op.add_column(
        "ingest_runs",
        sa.Column("qc_missing", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "ingest_runs",
        sa.Column("qc_suspect", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "ingest_runs",
        sa.Column("qc_malformed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "ingest_runs",
        sa.Column("max_gap_hours", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingest_runs", "max_gap_hours")
    op.drop_column("ingest_runs", "qc_malformed")
    op.drop_column("ingest_runs", "qc_suspect")
    op.drop_column("ingest_runs", "qc_missing")
    op.drop_constraint("measurements_qc_values", "measurements")
    op.drop_column("measurements", "timestamp_raw")
