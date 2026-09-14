"""
conftest.py — Shared pytest fixtures for WeatherGPT tests.

Provides mocked dependencies so unit/integration tests run without
external services (Redis, PostgreSQL, MongoDB, TimescaleDB, Open-Meteo, etc.).
"""

import sys
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from fastapi.testclient import TestClient

# Ensure the project root is on sys.path
sys.path.insert(0, "/workspaces/SIH-main-round")


# ---------------------------------------------------------------------------
# Mock Redis / SessionStore (used by CoreAgent and escalation_engine)
# ---------------------------------------------------------------------------
class MockRedis:
    """In-memory Redis-like store for testing."""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._ttls: dict[str, float] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._data[key] = value
        if ex:
            import time
            self._ttls[key] = time.time() + ex
        return True

    def get(self, key: str) -> str | None:
        if key in self._ttls:
            import time
            if time.time() > self._ttls[key]:
                self._data.pop(key, None)
                self._ttls.pop(key, None)
                return None
        return self._data.get(key)

    def exists(self, key: str) -> int:
        val = self.get(key)
        return 1 if val is not None else 0

    def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self._data:
                self._data.pop(k, None)
                self._ttls.pop(k, None)
                count += 1
        return count

    def incr(self, key: str) -> int:
        val = int(self.get(key) or 0) + 1
        self.set(key, str(val))
        return val

    def expire(self, key: str, seconds: int) -> bool:
        if key in self._data:
            import time
            self._ttls[key] = time.time() + seconds
            return True
        return False


@pytest.fixture
def mock_redis() -> MockRedis:
    """Provides a fresh MockRedis instance per test."""
    return MockRedis()


# ---------------------------------------------------------------------------
# Mock CoreAgent and related components
# ---------------------------------------------------------------------------
class MockEscalation:
    """Mock escalation decision."""
    def __init__(self, escalate: bool = False, queue: str = "general", priority: str = "low", reason: str = "test", handoff_summary: str = "test"):
        self.escalate = escalate
        self.queue = MagicMock(value=queue)
        self.priority = MagicMock(value=priority)
        self.reason = reason
        self.handoff_summary = handoff_summary


class MockCoreAgentReply:
    """Mock reply from CoreAgent.handle_turn()."""
    def __init__(self, text: str = "Mock advisory response", escalate: bool = False):
        self.text = text
        self.escalation = MockEscalation(escalate=escalate)


@pytest.fixture
def mock_core_agent():
    """Provides a mocked CoreAgent with configurable handle_turn."""
    with patch("core_agent.CoreAgent") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.handle_turn = AsyncMock(return_value=MockCoreAgentReply())
        mock_instance.sessions = MagicMock()
        mock_instance.sessions._r = MockRedis()
        mock_cls.return_value = mock_instance
        yield mock_instance


# ---------------------------------------------------------------------------
# Mock DB Managers (PostgreSQL, MongoDB, TimescaleDB)
# ---------------------------------------------------------------------------
class MockPostgresManager:
    def __init__(self):
        self._healthy = True
        self._events: list[dict] = []

    async def initialize(self):
        pass

    async def close(self):
        pass

    async def health_check(self) -> bool:
        return self._healthy

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    async def add_disaster_event(self, **kwargs) -> MagicMock:
        event = MagicMock()
        for k, v in kwargs.items():
            setattr(event, k, v)
        event.id = len(self._events) + 1
        event.fetched_at = datetime.now(timezone.utc)
        self._events.append(event)
        return event

    async def get_disaster_events(self, limit: int = 100, **filters) -> list:
        return self._events[-limit:]


class MockMongoManager:
    def __init__(self):
        self._healthy = True
        self._advisories: list[dict] = []
        self._bulletins: list[dict] = []
        self._alerts: list[dict] = []

    async def initialize(self):
        pass

    async def close(self):
        pass

    async def health_check(self) -> bool:
        return self._healthy

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def advisories(self):
        return self

    @property
    def bulletins(self):
        return self

    @property
    def alerts(self):
        return self

    async def insert_one(self, doc: dict):
        from bson import ObjectId
        doc["_id"] = ObjectId()
        if "created_at" not in doc:
            doc["created_at"] = datetime.now(timezone.utc)
        return MagicMock(inserted_id=doc["_id"])

    async def find_one(self, query: dict, sort=None):
        for doc in reversed(self._advisories + self._bulletins + self._alerts):
            match = True
            for k, v in query.items():
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                return doc
        return None

    def find(self, query: dict):
        return MockCursor(self._advisories + self._bulletins + self._alerts, query)

    async def update_one(self, query: dict, update: dict):
        return MagicMock(modified_count=1)


class MockCursor:
    def __init__(self, docs: list[dict], query: dict):
        self._docs = [d for d in docs if all(d.get(k) == v for k, v in query.items())]

    def sort(self, *args, **kwargs):
        return self

    def limit(self, n: int):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: int):
        return self._docs[:length]


@pytest.fixture
def mock_postgres_manager():
    """Provides a mocked PostgresManager."""
    with patch("db.postgres.get_postgres_manager") as mock_get:
        manager = MockPostgresManager()
        mock_get.return_value = manager
        yield manager


@pytest.fixture
def mock_mongo_manager():
    """Provides a mocked MongoManager."""
    with patch("db.mongo.get_mongo_manager") as mock_get:
        manager = MockMongoManager()
        mock_get.return_value = manager
        yield manager


@pytest.fixture
def mock_timescale_manager():
    """Provides a mocked TimescaleManager."""
    with patch("db.timescale.get_timescale_manager") as mock_get:
        manager = MagicMock()
        manager.initialize = AsyncMock()
        manager.close = AsyncMock()
        manager.health_check = AsyncMock(return_value=True)
        manager.is_healthy = True
        mock_get.return_value = manager
        yield manager


# ---------------------------------------------------------------------------
# Mock external HTTP calls (Open-Meteo, USGS, GDACS, etc.)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_external_apis():
    """Mock all external API calls via respx."""
    with respx.mock(assert_all_called=False) as respx_mock:
        # Open-Meteo current weather (matches the fields requested by WeatherService.get_current_weather)
        respx_mock.get("https://api.open-meteo.com/v1/forecast").respond(
            200,
            json={
                "current": {
                    "temperature_2m": 25.0,
                    "relative_humidity_2m": 60,
                    "apparent_temperature": 26.0,
                    "precipitation": 0.0,
                    "wind_speed_10m": 10.0,
                    "wind_direction_10m": 180,
                    "wind_gusts_10m": 15.0,
                    "weather_code": 0,
                    "pressure_msl": 1013.0,
                    "cloud_cover": 20,
                    "visibility": 10000,
                    "dew_point_2m": 15.0,
                    "uv_index": 5.0,
                    "is_day": 1,
                    "time": "2024-01-01T12:00",
                },
                "latitude": 28.61,
                "longitude": 77.21,
                "timezone": "Asia/Kolkata",
                "hourly": {
                    "time": ["2024-01-01T12:00"],
                    "temperature_2m": [25.0],
                    "relative_humidity_2m": [60],
                    "precipitation": [0.0],
                    "wind_speed_10m": [10.0],
                    "wind_direction_10m": [180],
                },
                "daily": {
                    "time": ["2024-01-01"],
                    "temperature_2m_max": [30.0],
                    "temperature_2m_min": [20.0],
                    "precipitation_sum": [0.0],
                    "precipitation_probability_max": [0],
                    "weathercode": [0],
                },
            }
        )

        # USGS Earthquake
        respx_mock.get("https://earthquake.usgs.gov/fdsnws/event/1/query").respond(
            200, json={"features": []}
        )

        # GDACS
        respx_mock.get("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH").respond(
            200, json={"features": []}
        )

        # Open-Meteo Marine API
        respx_mock.get("https://marine-api.open-meteo.com/v1/marine").respond(
            200,
            json={
                "current": {
                    "wave_height": 1.5,
                    "wave_direction": 200,
                    "swell_wave_height": 1.0,
                    "swell_wave_direction": 180,
                    "sea_surface_temperature": 28.0,
                    "wave_period": 8.0,
                    "wave_peak_period": 10.0,
                    "time": "2024-01-01T12:00",
                },
                "latitude": 19.07,
                "longitude": 72.87,
                "timezone": "Asia/Kolkata",
            }
        )

        # Bhashini (if used)
        respx_mock.post("https://bhashini-api.example.com").respond(
            200, json={"output": "translated text"}
        )

        # Meta WhatsApp Graph API
        respx_mock.post("https://graph.facebook.com/v20.0/.*/messages").respond(
            200, json={"messages": [{"id": "msg_123"}]}
        )
        respx_mock.get("https://graph.facebook.com/v20.0/.*").respond(
            200, json={"url": "https://cdn.example.com/media.mp3"}
        )

        # Twilio
        respx_mock.post("https://api.twilio.com/2010-04-01/Accounts/.*/Messages.json").respond(
            200, json={"sid": "SM123", "status": "queued"}
        )

        yield respx_mock


# ---------------------------------------------------------------------------
# FastAPI TestClient fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def test_client(mock_redis, mock_core_agent, mock_postgres_manager, mock_mongo_manager, mock_timescale_manager, mock_external_apis):
    """Create a TestClient with all dependencies mocked."""
    # Import after mocks are in place
    from backend_app_factory import create_app

    app = create_app(enable_docs=False)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_disaster_event() -> dict[str, Any]:
    """A sample disaster event for testing."""
    return {
        "id": "evt_123",
        "source": "GDACS",
        "hazard_type": "cyclone",
        "severity": "orange",
        "title": "Cyclone Warning - Bay of Bengal",
        "description": "Severe cyclonic storm expected to make landfall in 24 hours",
        "latitude": 19.07,
        "longitude": 88.36,
        "event_time": "2024-01-01T12:00:00Z",
    }


@pytest.fixture
def sample_alert_draft() -> dict[str, Any]:
    """A sample alert draft document."""
    return {
        "_id": "507f1f77bcf86cd799439011",
        "event_id": "evt_123",
        "event_fingerprint": "abc123",
        "language": "hindi",
        "script_text": "चक्रवात चेतावनी: बंगाल की खाड़ी में गंभीर चक्रवाती तूफान",
        "severity": "orange",
        "hazard_type": "cyclone",
        "title": "Cyclone Warning",
        "description": "Severe cyclonic storm",
        "latitude": 19.07,
        "longitude": 88.36,
        "source": "GDACS",
        "event_time": datetime.now(timezone.utc).isoformat(),
        "change_type": "new",
        "delivery_status": "draft",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit_log": [{"action": "drafted", "actor": "alert_generator", "timestamp": datetime.now(timezone.utc).isoformat()}],
    }