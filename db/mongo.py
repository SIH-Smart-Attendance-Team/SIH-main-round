"""
MongoDB connection manager for semi-structured advisories and bulletins.

Uses motor (async MongoDB driver) for async operations.
Collections:
- advisories: generated AI advisories keyed by location + timestamp
- bulletins: free-text disaster bulletins (GDACS descriptions)
- alerts: drafted disaster warning alerts pending human approval
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional, Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import PyMongoError

logger = logging.getLogger("weathergpt.db.mongo")


class MongoManager:
    """Async MongoDB connection manager with connection pooling."""

    def __init__(
        self,
        url: Optional[str] = None,
        database: str = "weathergpt",
        max_pool_size: int = 50,
        min_pool_size: int = 10,
        server_selection_timeout_ms: int = 5000,
    ):
        self._url = url or os.getenv("MONGO_URL")
        if not self._url:
            raise ValueError("MONGO_URL environment variable not set")

        self._database_name = database
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._max_pool_size = max_pool_size
        self._min_pool_size = min_pool_size
        self._server_selection_timeout_ms = server_selection_timeout_ms
        self._healthy = False

    async def initialize(self) -> None:
        """Create client, database, and ensure indexes."""
        if self._client is not None:
            return

        self._client = AsyncIOMotorClient(
            self._url,
            maxPoolSize=self._max_pool_size,
            minPoolSize=self._min_pool_size,
            serverSelectionTimeoutMS=self._server_selection_timeout_ms,
        )
        self._db = self._client[self._database_name]

        # Create indexes
        await self._ensure_indexes()

        # Test connection
        await self._client.admin.command("ping")
        self._healthy = True
        logger.info("MongoDB initialized successfully")

    async def _ensure_indexes(self) -> None:
        """Create required indexes for advisories, bulletins, and alerts collections."""
        advisories: AsyncIOMotorCollection = self._db.advisories
        bulletins: AsyncIOMotorCollection = self._db.bulletins
        alerts: AsyncIOMotorCollection = self._db.alerts

        await advisories.create_indexes([
            IndexModel([("location_id", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("lat", ASCENDING), ("lon", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("source_lang", ASCENDING), ("target_lang", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ])

        await bulletins.create_indexes([
            IndexModel([("source", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("location_id", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("type", ASCENDING), ("severity", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ])

        await alerts.create_indexes([
            IndexModel([("event_id", ASCENDING), ("language", ASCENDING)]),
            IndexModel([("delivery_status", ASCENDING), ("generated_at", DESCENDING)]),
            IndexModel([("severity", ASCENDING), ("generated_at", DESCENDING)]),
            IndexModel([("generated_at", DESCENDING)]),
        ])

    async def close(self) -> None:
        """Close the MongoDB client."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._healthy = False
            logger.info("MongoDB connection closed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[Any, None]:
        """Get a MongoDB session for transactions (optional)."""
        if not self._client:
            await self.initialize()
        async with await self._client.start_session() as session:
            yield session

    async def health_check(self) -> bool:
        """Check MongoDB connectivity."""
        if not self._client:
            return False
        try:
            await self._client.admin.command("ping")
            self._healthy = True
            return True
        except PyMongoError as exc:
            logger.warning("MongoDB health check failed: %s", exc)
            self._healthy = False
            return False

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    async def _ensure_initialized(self) -> None:
        """Ensure the database is initialized."""
        if not self._db:
            await self.initialize()

    @property
    def database(self) -> AsyncIOMotorDatabase:
        if not self._db:
            raise RuntimeError("MongoDB not initialized. Call initialize() first.")
        return self._db

    @property
    def advisories(self) -> AsyncIOMotorCollection:
        if not self._db:
            raise RuntimeError("MongoDB not initialized. Call initialize() first.")
        return self._db.advisories

    @property
    def bulletins(self) -> AsyncIOMotorCollection:
        if not self._db:
            raise RuntimeError("MongoDB not initialized. Call initialize() first.")
        return self._db.bulletins

    @property
    def alerts(self) -> AsyncIOMotorCollection:
        if not self._db:
            raise RuntimeError("MongoDB not initialized. Call initialize() first.")
        return self._db.alerts

    # -----------------------------------------------------------------------
    # Advisory operations
    # -----------------------------------------------------------------------

    async def store_advisory(
        self,
        location_id: Optional[int],
        lat: float,
        lon: float,
        source_lang: str,
        target_lang: str,
        user_query: str,
        english_query: str,
        weather_context: str,
        english_advisory: str,
        native_advisory: str,
        raw_result: dict,
    ) -> str:
        """Store a generated advisory. Returns the inserted document ID."""
        doc = {
            "location_id": location_id,
            "lat": lat,
            "lon": lon,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "user_query": user_query,
            "english_query": english_query,
            "weather_context": weather_context,
            "english_advisory": english_advisory,
            "native_advisory": native_advisory,
            "raw_result": raw_result,
            "created_at": datetime.now(timezone.utc),
            "timestamp": datetime.now(timezone.utc),
        }
        result = await self.advisories.insert_one(doc)
        return str(result.inserted_id)

    async def find_recent_advisory(
        self,
        lat: float,
        lon: float,
        source_lang: str,
        target_lang: str,
        max_age_minutes: int = 60,
    ) -> Optional[dict]:
        """Find a recent advisory for the same location and languages within max_age_minutes."""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        # Use a small radius (~1km) for location matching
        lat_delta = 0.01
        lon_delta = 0.01
        query = {
            "lat": {"$gte": lat - lat_delta, "$lte": lat + lat_delta},
            "lon": {"$gte": lon - lon_delta, "$lte": lon + lon_delta},
            "source_lang": source_lang,
            "target_lang": target_lang,
            "created_at": {"$gte": cutoff},
        }
        return await self.advisories.find_one(query, sort=[("created_at", DESCENDING)])

    async def get_advisories_by_location(
        self, location_id: int, limit: int = 50
    ) -> list[dict]:
        """Get advisories for a specific location."""
        cursor = self.advisories.find({"location_id": location_id}).sort("created_at", DESCENDING).limit(limit)
        return await cursor.to_list(length=limit)

    # -----------------------------------------------------------------------
    # Bulletin operations (GDACS, etc.)
    # -----------------------------------------------------------------------

    async def store_bulletin(
        self,
        source: str,
        type_: str,
        severity: str,
        title: str,
        description: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        location_id: Optional[int] = None,
        raw_json: Optional[dict] = None,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """Store a disaster bulletin. Returns the inserted document ID."""
        doc = {
            "source": source,
            "type": type_,
            "severity": severity,
            "title": title,
            "description": description,
            "lat": lat,
            "lon": lon,
            "location_id": location_id,
            "raw_json": raw_json or {},
            "timestamp": timestamp or datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
        }
        result = await self.bulletins.insert_one(doc)
        return str(result.inserted_id)

    async def get_bulletins(
        self,
        source: Optional[str] = None,
        type_: Optional[str] = None,
        severity: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query bulletins with optional filters."""
        query = {}
        if source:
            query["source"] = source
        if type_:
            query["type"] = type_
        if severity:
            query["severity"] = severity
        if since:
            query["timestamp"] = {"$gte": since}
        cursor = self.bulletins.find(query).sort("timestamp", DESCENDING).limit(limit)
        return await cursor.to_list(length=limit)

    # -----------------------------------------------------------------------
    # Drafted alert operations (human approval required before delivery)
    # -----------------------------------------------------------------------

    async def store_alert_draft(
        self,
        event_id: str,
        event_fingerprint: str,
        language: str,
        script_text: str,
        severity: str,
        hazard_type: str,
        title: str,
        description: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        source: str = "disaster_tools",
        event_time: Optional[datetime] = None,
        raw_event: Optional[dict] = None,
        change_type: str = "new",
    ) -> str:
        """Store a drafted alert pending human approval. Returns document ID."""
        now = datetime.now(timezone.utc)
        doc = {
            "event_id": event_id,
            "event_fingerprint": event_fingerprint,
            "language": language,
            "script_text": script_text,
            "severity": severity,
            "hazard_type": hazard_type,
            "title": title,
            "description": description,
            "latitude": latitude,
            "longitude": longitude,
            "source": source,
            "event_time": event_time,
            "raw_event": raw_event or {},
            "change_type": change_type,
            "delivery_status": "draft",
            "generated_at": now,
            "created_at": now,
            "updated_at": now,
            "approved_by": None,
            "approved_at": None,
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
            "audit_log": [
                {
                    "action": "drafted",
                    "actor": "alert_generator",
                    "timestamp": now,
                    "event_id": event_id,
                }
            ],
        }
        result = await self.alerts.insert_one(doc)
        return str(result.inserted_id)

    async def get_draft_alerts(
        self,
        *,
        delivery_status: Optional[str] = None,
        severity: Optional[str] = None,
        language: Optional[str] = None,
        event_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query drafted alerts with optional filters."""
        query = {}
        if delivery_status:
            query["delivery_status"] = delivery_status
        if severity:
            query["severity"] = severity
        if language:
            query["language"] = language
        if event_id:
            query["event_id"] = event_id
        if since:
            query["generated_at"] = {"$gte": since}
        cursor = self.alerts.find(query).sort("generated_at", DESCENDING).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_alert_by_id(self, alert_id: str) -> Optional[dict]:
        """Get a single drafted alert by Mongo object ID."""
        from bson import ObjectId

        try:
            oid = ObjectId(alert_id)
        except Exception:
            return None
        return await self.alerts.find_one({"_id": oid})

    async def approve_alert(
        self,
        alert_id: str,
        approved_by: str,
    ) -> Optional[dict]:
        """Mark a drafted alert as approved by a human reviewer."""
        from bson import ObjectId

        now = datetime.now(timezone.utc)
        try:
            oid = ObjectId(alert_id)
        except Exception:
            return None

        result = await self.alerts.update_one(
            {"_id": oid, "delivery_status": "draft"},
            {
                "$set": {
                    "delivery_status": "approved",
                    "approved_by": approved_by,
                    "approved_at": now,
                    "updated_at": now,
                },
                "$push": {
                    "audit_log": {
                        "action": "approved",
                        "actor": approved_by,
                        "timestamp": now,
                    }
                },
            },
        )
        if result.modified_count == 0:
            return await self.get_alert_by_id(alert_id)
        return await self.get_alert_by_id(alert_id)

    async def reject_alert(
        self,
        alert_id: str,
        rejected_by: str,
        reason: Optional[str] = None,
    ) -> Optional[dict]:
        """Mark a drafted alert as rejected by a human reviewer."""
        from bson import ObjectId

        now = datetime.now(timezone.utc)
        try:
            oid = ObjectId(alert_id)
        except Exception:
            return None

        result = await self.alerts.update_one(
            {"_id": oid, "delivery_status": "draft"},
            {
                "$set": {
                    "delivery_status": "rejected",
                    "rejected_by": rejected_by,
                    "rejected_at": now,
                    "rejection_reason": reason,
                    "updated_at": now,
                },
                "$push": {
                    "audit_log": {
                        "action": "rejected",
                        "actor": rejected_by,
                        "reason": reason,
                        "timestamp": now,
                    }
                },
            },
        )
        if result.modified_count == 0:
            return await self.get_alert_by_id(alert_id)
        return await self.get_alert_by_id(alert_id)


_mongo_manager: Optional[MongoManager] = None


def get_mongo_manager() -> MongoManager:
    """Get or create the global MongoManager instance."""
    global _mongo_manager
    if _mongo_manager is None:
        _mongo_manager = MongoManager()
    return _mongo_manager


async def close_mongo_manager() -> None:
    """Close the global MongoManager instance."""
    global _mongo_manager
    if _mongo_manager:
        await _mongo_manager.close()
        _mongo_manager = None