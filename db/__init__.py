"""
Database package for WeatherGPT persistent storage layer.

Provides three storage backends:
- PostgreSQL + PostGIS: structured geo-tagged data (locations, forecasts, disasters)
- MongoDB: semi-structured advisories and bulletins
- TimescaleDB: dense time-series for forecast/observation history
"""

from db.mongo import (
    MongoManager,
    close_mongo_manager,
    get_mongo_manager,
)
from db.postgres import (
    PostgresManager,
    close_postgres_manager,
    get_postgres_manager,
)
from db.timescale import (
    TimescaleManager,
    close_timescale_manager,
    get_timescale_manager,
)

__all__ = [
    "MongoManager",
    "PostgresManager",
    "TimescaleManager",
    "close_mongo_manager",
    "close_postgres_manager",
    "close_timescale_manager",
    "get_mongo_manager",
    "get_postgres_manager",
    "get_timescale_manager",
]