"""
PostgreSQL + PostGIS models for structured geo-tagged data.

Tables:
- locations: id, name, lat, lon, geom (PostGIS point)
- forecast_snapshots: location_id, fetched_at, raw_json, temp, precip, wind, source
- disaster_events: id, type, severity, geom, fetched_at, source, raw_json
"""

from __future__ import annotations

import datetime as dt

from geoalchemy2 import Geography
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    geom: Mapped[str] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    forecast_snapshots: Mapped[list[ForecastSnapshot]] = relationship(
        back_populates="location", cascade="all, delete-orphan"
    )
    disaster_events: Mapped[list[DisasterEvent]] = relationship(
        back_populates="location", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_locations_name", "name"),
        Index("ix_locations_created_at", "created_at"),
    )


class ForecastSnapshot(Base):
    __tablename__ = "forecast_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    precip: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="open-meteo", nullable=False)

    location: Mapped[Location] = relationship(back_populates="forecast_snapshots")

    __table_args__ = (
        Index("ix_forecast_snapshots_location_fetched", "location_id", "fetched_at"),
        Index("ix_forecast_snapshots_fetched_at", "fetched_at"),
    )


class DisasterEvent(Base):
    __tablename__ = "disaster_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    geom: Mapped[str] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False,
    )
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )

    location: Mapped[Location | None] = relationship(back_populates="disaster_events")

    __table_args__ = (
        Index("ix_disaster_events_type_severity", "type", "severity"),
        Index("ix_disaster_events_fetched_at", "fetched_at"),
        Index("ix_disaster_events_source", "source"),
    )