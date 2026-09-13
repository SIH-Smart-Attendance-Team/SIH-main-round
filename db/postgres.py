"""
PostgreSQL + PostGIS connection manager for WeatherGPT.

Uses async SQLAlchemy with asyncpg driver for async operations.
Implements connection pooling, health checks, and graceful degradation.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base, DisasterEvent, ForecastSnapshot, Location

logger = logging.getLogger("weathergpt.db.postgres")


class PostgresManager:
    """Async PostgreSQL + PostGIS connection manager with pooling."""

    def __init__(
        self,
        url: str | None = None,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: float = 30.0,
        pool_recycle: int = 3600,
        echo: bool = False,
    ):
        self._url = url or os.getenv("POSTGRES_URL")
        if not self._url:
            raise ValueError("POSTGRES_URL environment variable not set")

        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._pool_timeout = pool_timeout
        self._pool_recycle = pool_recycle
        self._echo = echo
        self._healthy = False

    async def initialize(self) -> None:
        """Create engine, session factory, and ensure PostGIS extension."""
        if self._engine is not None:
            return

        self._engine = create_async_engine(
            self._url,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_timeout=self._pool_timeout,
            pool_recycle=self._pool_recycle,
            echo=self._echo,
            future=True,
        )

        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Ensure PostGIS extension exists
        async with self._engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis_topology"))
            await conn.run_sync(Base.metadata.create_all)

        self._healthy = True
        logger.info("PostgreSQL + PostGIS initialized successfully")

    async def close(self) -> None:
        """Close the engine and all connections."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._healthy = False
            logger.info("PostgreSQL connection closed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session with automatic commit/rollback."""
        if not self._session_factory:
            await self.initialize()

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def health_check(self) -> bool:
        """Check database connectivity and PostGIS availability."""
        if not self._engine:
            return False
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                await conn.execute(text("SELECT postgis_version()"))
            self._healthy = True
            return True
        except Exception as exc:
            logger.warning("PostgreSQL health check failed: %s", exc)
            self._healthy = False
            return False

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    # -----------------------------------------------------------------------
    # High-level data access methods
    # -----------------------------------------------------------------------

    async def upsert_location(
        self, name: str, lat: float, lon: float
    ) -> Location:
        """Insert or update a location, returning the Location object."""
        from sqlalchemy.dialects.postgresql import insert

        geom_wkt = f"SRID=4326;POINT({lon} {lat})"

        async with self.session() as session:
            stmt = insert(Location).values(
                name=name,
                lat=lat,
                lon=lon,
                geom=geom_wkt,
            ).on_conflict_do_update(
                index_elements=["name"],
                set_={"lat": lat, "lon": lon, "geom": geom_wkt, "updated_at": func.now()},
            ).returning(Location)
            result = await session.execute(stmt)
            return result.scalar_one()

    async def get_location_by_name(self, name: str) -> Location | None:
        """Get location by name."""
        from sqlalchemy import select
        async with self.session() as session:
            result = await session.execute(select(Location).where(Location.name == name))
            return result.scalar_one_or_none()

    async def get_location_by_id(self, location_id: int) -> Location | None:
        """Get location by ID."""
        from sqlalchemy import select
        async with self.session() as session:
            result = await session.execute(select(Location).where(Location.id == location_id))
            return result.scalar_one_or_none()

    async def add_forecast_snapshot(
        self,
        location_id: int,
        raw_json: dict,
        temp: float | None = None,
        precip: float | None = None,
        wind: float | None = None,
        source: str = "open-meteo",
    ) -> ForecastSnapshot:
        """Insert a forecast snapshot."""
        snapshot = ForecastSnapshot(
            location_id=location_id,
            raw_json=raw_json,
            temp=temp,
            precip=precip,
            wind=wind,
            source=source,
        )
        async with self.session() as session:
            session.add(snapshot)
            await session.flush()
            await session.refresh(snapshot)
            return snapshot

    async def get_latest_forecast_snapshot(
        self, location_id: int
    ) -> ForecastSnapshot | None:
        """Get the most recent forecast snapshot for a location."""
        from sqlalchemy import select
        async with self.session() as session:
            result = await session.execute(
                select(ForecastSnapshot)
                .where(ForecastSnapshot.location_id == location_id)
                .order_by(ForecastSnapshot.fetched_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def add_disaster_event(
        self,
        type_: str,
        severity: str,
        lat: float,
        lon: float,
        source: str,
        raw_json: dict,
        location_id: int | None = None,
    ) -> DisasterEvent:
        """Insert a disaster event."""
        geom_wkt = f"SRID=4326;POINT({lon} {lat})"
        event = DisasterEvent(
            type=type_,
            severity=severity,
            geom=geom_wkt,
            source=source,
            raw_json=raw_json,
            location_id=location_id,
        )
        async with self.session() as session:
            session.add(event)
            await session.flush()
            await session.refresh(event)
            return event

    async def get_disaster_events(
        self,
        type_: str | None = None,
        severity: str | None = None,
        since: dt.datetime | None = None,
        limit: int = 100,
    ) -> list[DisasterEvent]:
        """Query disaster events with optional filters."""
        from sqlalchemy import select
        async with self.session() as session:
            stmt = select(DisasterEvent).order_by(DisasterEvent.fetched_at.desc()).limit(limit)
            if type_:
                stmt = stmt.where(DisasterEvent.type == type_)
            if severity:
                stmt = stmt.where(DisasterEvent.severity == severity)
            if since:
                stmt = stmt.where(DisasterEvent.fetched_at >= since)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_disaster_events_in_bbox(
        self,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        since: dt.datetime | None = None,
        limit: int = 100,
    ) -> list[DisasterEvent]:
        """Get disaster events within a bounding box using PostGIS."""
        from sqlalchemy import select, text
        bbox_wkt = f"SRID=4326;POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, {max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}))"
        async with self.session() as session:
            stmt = (
                select(DisasterEvent)
                .where(
                    text("ST_Intersects(geom, ST_GeogFromText(:bbox))").bindparams(bbox=bbox_wkt)
                )
                .order_by(DisasterEvent.fetched_at.desc())
                .limit(limit)
            )
            if since:
                stmt = stmt.where(DisasterEvent.fetched_at >= since)
            result = await session.execute(stmt)
            return list(result.scalars().all())


_postgres_manager: PostgresManager | None = None


def get_postgres_manager() -> PostgresManager:
    """Get or create the global PostgresManager instance."""
    global _postgres_manager
    if _postgres_manager is None:
        _postgres_manager = PostgresManager()
    return _postgres_manager


async def close_postgres_manager() -> None:
    """Close the global PostgresManager instance."""
    global _postgres_manager
    if _postgres_manager:
        await _postgres_manager.close()
        _postgres_manager = None