"""
Database package for WeatherGPT persistent storage layer.

Provides three storage backends:
- PostgreSQL + PostGIS: structured geo-tagged data (locations, forecasts, disasters)
- MongoDB: semi-structured advisories and bulletins
- TimescaleDB: dense time-series for forecast/observation history
"""

from db.postgres import (
    PostgresManager,
    get_postgres_manager,
    close_postgres_manager,
)
from db.mongo import (
    MongoManager,
    get_mongo_manager,
    close_mongo_manager,
)
from db.timescale import (
    TimescaleManager,
    get_timescale_manager,
    close_timescale_manager,
)

__all__ = [
    "PostgresManager",
    "get_postgres_manager",
    "close_postgres_manager",
    "MongoManager",
    "get_mongo_manager",
    "close_mongo_manager",
    "TimescaleManager",
    "get_timescale_manager",
    "close_timescale_manager",
]