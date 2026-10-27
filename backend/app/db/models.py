from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Mast(Base):
    __tablename__ = "mast"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float] = mapped_column(Double, nullable=False)
    longitude: Mapped[float] = mapped_column(Double, nullable=False)
    measurement_height_m: Mapped[float] = mapped_column(Double, nullable=False)
    operator: Mapped[str] = mapped_column(Text, nullable=False)
    commissioned_at: Mapped[date] = mapped_column(Date, nullable=False)


class Turbine(Base):
    __tablename__ = "turbine"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    rated_power_kw: Mapped[float] = mapped_column(Double, nullable=False)
    hub_height_m: Mapped[float] = mapped_column(Double, nullable=False)
    rotor_diameter_m: Mapped[float] = mapped_column(Double, nullable=False)
    cut_in_wind_speed_ms: Mapped[float] = mapped_column(Double, nullable=False)
    cut_out_wind_speed_ms: Mapped[float] = mapped_column(Double, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class PowerCurvePoint(Base):
    __tablename__ = "power_curve_points"

    turbine_id: Mapped[str] = mapped_column(
        ForeignKey("turbine.id", ondelete="CASCADE"), primary_key=True
    )
    wind_speed_ms: Mapped[float] = mapped_column(Double, primary_key=True)
    power_kw: Mapped[float] = mapped_column(Double, nullable=False)


class Site(Base):
    __tablename__ = "site"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    mast_id: Mapped[str] = mapped_column(
        ForeignKey("mast.id"), nullable=False
    )
    shear_exponent: Mapped[float] = mapped_column(Double, nullable=False)
    availability_loss: Mapped[float] = mapped_column(Double, nullable=False)
    electrical_loss: Mapped[float] = mapped_column(Double, nullable=False)
    wake_loss: Mapped[float] = mapped_column(Double, nullable=False)
    uncertainty: Mapped[float] = mapped_column(Double, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        Index("ix_measurements_updated_at", "updated_at"),
    )

    mast_id: Mapped[str] = mapped_column(
        ForeignKey("mast.id"), primary_key=True
    )
    # UTC, start of the measurement hour
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    # Canonical m/s. The ingest pipeline guarantees every stored row has a
    # usable value: hours that arrive defective are filled by interpolation.
    wind_speed_ms: Mapped[float] = mapped_column(Double, nullable=False)
    # Original value as received (audit). For an interpolated hour this is
    # the rejected raw value (e.g. "-999.0"), "" if the API never delivered.
    wind_speed_raw: Mapped[str] = mapped_column(Text, nullable=False)
    # Original timestamp string incl. timezone suffix (suffix evidence)
    timestamp_raw: Mapped[str] = mapped_column(Text, nullable=False)
    wind_dir_deg: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Why this hour was interpolated (qc.py REASONS); NULL = measured ok.
    qc_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frame_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    frame_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Ingest QA: hours this run could not store and filled by interpolation
    interpolated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # largest data hole (h) inside the fetched frame
    max_gap_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
