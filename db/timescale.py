"""
TimescaleDB connection manager for dense time-series data.

Uses async SQLAlchemy with asyncpg driver. TimescaleDB runs as a PostgreSQL extension,
so this can share the same Postgres instance or use a separate one.

Hypertable: forecast_observations
- time (timestamptz, partition key)
- location_id (int)
- lat, lon (float)
- temperature, humidity, precipitation, wind_speed, wind_direction, pressure, weather_code (float/int)
- source (text)
- raw_json (jsonb)
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    select,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger("weathergpt.db.timescale")


class TimescaleBase(DeclarativeBase):
    pass


class ForecastObservation(TimescaleBase):
    __tablename__ = "forecast_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    time: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    weather_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="open-meteo", nullable=False)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        Index("ix_forecast_observations_time", "time"),
        Index("ix_forecast_observations_location_time", "location_id", "time"),
        Index("ix_forecast_observations_lat_lon_time", "lat", "lon", "time"),
    )


class TimescaleManager:
    """Async TimescaleDB connection manager with hypertable support."""

    def __init__(
        self,
        url: str | None = None,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: float = 30.0,
        pool_recycle: int = 3600,
        echo: bool = False,
    ):
        self._url = url or os.getenv("TIMESCALE_URL")
        if not self._url:
            # Fallback to POSTGRES_URL if TIMESCALE_URL not set
            self._url = os.getenv("POSTGRES_URL")
        if not self._url:
            raise ValueError("TIMESCALE_URL or POSTGRES_URL environment variable not set")

        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._pool_timeout = pool_timeout
        self._pool_recycle = pool_recycle
        self._echo = echo
        self._healthy = False
        self._hypertable_created = False

    async def initialize(self) -> None:
        """Create engine, session factory, and ensure TimescaleDB extension + hypertable."""
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

        # Ensure TimescaleDB extension and create hypertable
        async with self._engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            await conn.run_sync(TimescaleBase.metadata.create_all)
            await self._create_hypertable(conn)

        self._healthy = True
        logger.info("TimescaleDB initialized successfully")

    async def _create_hypertable(self, conn) -> None:
        """Create hypertable for forecast_observations if not exists."""
        try:
            # Check if hypertable already exists
            result = await conn.execute(
                text("""
                    SELECT 1 FROM timescaledb_information.hypertables
                    WHERE hypertable_name = 'forecast_observations'
                """)
            )
            if result.scalar_one_or_none():
                self._hypertable_created = True
                return

            # Create hypertable partitioned by time
            await conn.execute(text("""
                SELECT create_hypertable(
                    'forecast_observations',
                    'time',
                    chunk_time_interval => INTERVAL '1 day',
                    if_not_exists => TRUE
                )
            """))
            # Add compression policy for older chunks
            await conn.execute(text("""
                ALTER TABLE forecast_observations SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'location_id'
                )
            """))
            await conn.execute(text("""
                SELECT add_compression_policy('forecast_observations', INTERVAL '7 days')
            """))
            self._hypertable_created = True
            logger.info("TimescaleDB hypertable created successfully")
        except Exception as exc:
            logger.warning("Could not create hypertable (may already exist): %s", exc)
            self._hypertable_created = True  # Don't block on this

    async def close(self) -> None:
        """Close the engine and all connections."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._healthy = False
            logger.info("TimescaleDB connection closed")

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
        """Check TimescaleDB connectivity and extension availability."""
        if not self._engine:
            return False
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                await conn.execute(text("SELECT timescaledb_version()"))
            self._healthy = True
            return True
        except Exception as exc:
            logger.warning("TimescaleDB health check failed: %s", exc)
            self._healthy = False
            return False

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    # -----------------------------------------------------------------------
    # High-level data access methods
    # -----------------------------------------------------------------------

    async def insert_observations_batch(
        self, observations: list[dict]
    ) -> int:
        """Bulk insert forecast observations. Returns count inserted."""
        if not observations:
            return 0

        async with self.session() as session:
            session.add_all([ForecastObservation(**obs) for obs in observations])
            await session.flush()
            return len(observations)

    async def insert_observation(
        self,
        time: dt.datetime,
        lat: float,
        lon: float,
        temperature: float | None = None,
        relative_humidity: float | None = None,
        precipitation: float | None = None,
        wind_speed: float | None = None,
        wind_direction: float | None = None,
        pressure: float | None = None,
        weather_code: int | None = None,
        source: str = "open-meteo",
        raw_json: dict | None = None,
        location_id: int | None = None,
    ) -> ForecastObservation:
        """Insert a single forecast observation."""
        obs = ForecastObservation(
            time=time,
            location_id=location_id,
            lat=lat,
            lon=lon,
            temperature=temperature,
            relative_humidity=relative_humidity,
            precipitation=precipitation,
            wind_speed=wind_speed,
            wind_direction=wind_direction,
            pressure=pressure,
            weather_code=weather_code,
            source=source,
            raw_json=raw_json or {},
        )
        async with self.session() as session:
            session.add(obs)
            await session.flush()
            await session.refresh(obs)
            return obs

    async def get_observations(
        self,
        lat: float,
        lon: float,
        since: dt.datetime | None = None,
        until: dt.datetime | None = None,
        limit: int = 1000,
    ) -> list[ForecastObservation]:
        """Get observations for a location within a time range."""
        lat_delta = 0.01
        lon_delta = 0.01
        async with self.session() as session:
            stmt = (
                select(ForecastObservation)
                .where(
                    ForecastObservation.lat.between(lat - lat_delta, lat + lat_delta),
                    ForecastObservation.lon.between(lon - lon_delta, lon + lon_delta),
                )
                .order_by(ForecastObservation.time.desc())
                .limit(limit)
            )
            if since:
                stmt = stmt.where(ForecastObservation.time >= since)
            if until:
                stmt = stmt.where(ForecastObservation.time <= until)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_observations_by_location_id(
        self,
        location_id: int,
        since: dt.datetime | None = None,
        until: dt.datetime | None = None,
        limit: int = 1000,
    ) -> list[ForecastObservation]:
        """Get observations for a location_id within a time range."""
        async with self.session() as session:
            stmt = (
                select(ForecastObservation)
                .where(ForecastObservation.location_id == location_id)
                .order_by(ForecastObservation.time.desc())
                .limit(limit)
            )
            if since:
                stmt = stmt.where(ForecastObservation.time >= since)
            if until:
                stmt = stmt.where(ForecastObservation.time <= until)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_latest_observation(
        self, lat: float, lon: float
    ) -> ForecastObservation | None:
        """Get the most recent observation for a location."""
        lat_delta = 0.01
        lon_delta = 0.01
        async with self.session() as session:
            result = await session.execute(
                select(ForecastObservation)
                .where(
                    ForecastObservation.lat.between(lat - lat_delta, lat + lat_delta),
                    ForecastObservation.lon.between(lon - lon_delta, lon + lon_delta),
                )
                .order_by(ForecastObservation.time.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_time_bucketed_stats(
        self,
        lat: float,
        lon: float,
        bucket_interval: str = "1 hour",
        since: dt.datetime | None = None,
        until: dt.datetime | None = None,
    ) -> list[dict]:
        """Get time-bucketed statistics using TimescaleDB's time_bucket."""
        lat_delta = 0.01
        lon_delta = 0.01
        async with self.session() as session:
            where_clauses = [
                f"lat BETWEEN {lat - lat_delta} AND {lat + lat_delta}",
                f"lon BETWEEN {lon - lon_delta} AND {lon + lon_delta}",
            ]
            if since:
                where_clauses.append(f"time >= '{since.isoformat()}'")
            if until:
                where_clauses.append(f"time <= '{until.isoformat()}'")
            where_sql = " AND ".join(where_clauses)

            query = text(f"""
                SELECT
                    time_bucket('{bucket_interval}', time) AS bucket,
                    AVG(temperature) AS avg_temp,
                    MAX(temperature) AS max_temp,
                    MIN(temperature) AS min_temp,
                    AVG(relative_humidity) AS avg_humidity,
                    AVG(precipitation) AS avg_precip,
                    MAX(precipitation) AS max_precip,
                    AVG(wind_speed) AS avg_wind,
                    MAX(wind_speed) AS max_wind,
                    COUNT(*) as sample_count
                FROM forecast_observations
                WHERE {where_sql}
                GROUP BY bucket
                ORDER BY bucket DESC
            """)
            result = await session.execute(query)
            return [dict(row._mapping) for row in result.fetchall()]


_timescale_manager: TimescaleManager | None = None


def get_timescale_manager() -> TimescaleManager:
    """Get or create the global TimescaleManager instance."""
    global _timescale_manager
    if _timescale_manager is None:
        _timescale_manager = TimescaleManager()
    return _timescale_manager


async def close_timescale_manager() -> None:
    """Close the global TimescaleManager instance."""
    global _timescale_manager
    if _timescale_manager:
        await _timescale_manager.close()
        _timescale_manager = None