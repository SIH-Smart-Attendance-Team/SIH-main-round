"""
weather_service.py

Asynchronous weather service using httpx and the free Open-Meteo APIs.
Provides current weather, 7-day forecasts, agricultural metrics, and marine data.
Includes in-memory TTL cache (15 min) and exponential-backoff retries.

Persistence layer (Layer 2):
- PostgreSQL + PostGIS: forecast_snapshots table
- TimescaleDB: forecast_observations hypertable
- Graceful degradation: if DBs are down, continue with live API calls only
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Persistence imports (lazy-loaded to avoid hard dependency at import time)
# ---------------------------------------------------------------------------
try:
    from db.postgres import get_postgres_manager
    from db.timescale import get_timescale_manager
    _PERSISTENCE_AVAILABLE = True
except ImportError:
    _PERSISTENCE_AVAILABLE = False

logger = logging.getLogger("weathergpt.weather_service")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
MAX_RETRIES = 4
BASE_BACKOFF = 0.5  # seconds


# ---------------------------------------------------------------------------
# Pydantic / dataclass response models
# ---------------------------------------------------------------------------

class CurrentWeather(BaseModel):
    temperature: Optional[float] = None
    relative_humidity: Optional[float] = None
    apparent_temperature: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    wind_gusts: Optional[float] = None
    weather_code: Optional[int] = None
    pressure_msl: Optional[float] = None
    cloud_cover: Optional[float] = None
    visibility: Optional[float] = None
    dew_point_2m: Optional[float] = None
    uv_index: Optional[float] = None
    is_day: Optional[int] = None
    time: Optional[str] = None


class DailyForecastDay(BaseModel):
    date: str
    temperature_max: Optional[float] = None
    temperature_min: Optional[float] = None
    precipitation_sum: Optional[float] = None
    precipitation_probability_max: Optional[float] = None
    weather_code: Optional[int] = None


class HourlyForecastPoint(BaseModel):
    time: str
    temperature: Optional[float] = None
    precipitation: Optional[float] = None
    precipitation_probability: Optional[float] = None
    weather_code: Optional[int] = None


class ForecastResponse(BaseModel):
    latitude: float
    longitude: float
    timezone: Optional[str] = None
    current: Optional[CurrentWeather] = None
    daily: List[DailyForecastDay] = Field(default_factory=list)
    hourly: List[HourlyForecastPoint] = Field(default_factory=list)


class AgriculturalMetrics(BaseModel):
    et0_fao_evapotranspiration: Optional[float] = None
    soil_temperature_0_to_7cm: Optional[float] = None
    soil_temperature_7_to_28cm: Optional[float] = None
    soil_moisture_0_to_7cm: Optional[float] = None
    soil_moisture_7_to_28cm: Optional[float] = None
    leaf_wetness_probability: Optional[float] = None
    time: Optional[str] = None


class MarineMetrics(BaseModel):
    wave_height: Optional[float] = None
    wave_direction: Optional[float] = None
    swell_wave_height: Optional[float] = None
    swell_wave_direction: Optional[float] = None
    sea_surface_temperature: Optional[float] = None
    wind_gusts: Optional[float] = None
    time: Optional[str] = None


# ---------------------------------------------------------------------------
# Simple async in-memory TTL cache
# ---------------------------------------------------------------------------

@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class AsyncTTLCache:
    def __init__(self, ttl: float = CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl
        self._store: Dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                return None
            return entry.value

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._store[key] = _CacheEntry(
                value=value,
                expires_at=time.monotonic() + self._ttl,
            )

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()


# ---------------------------------------------------------------------------
# WeatherService
# ---------------------------------------------------------------------------

class WeatherService:
    """
    Asynchronous Open-Meteo client with caching and retries.
    Compatible with FastAPI (inject as a dependency or singleton).
    """

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        cache_ttl: float = CACHE_TTL_SECONDS,
        timeout: float = 15.0,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self._cache = AsyncTTLCache(ttl=cache_ttl)
        self._pg_manager = None
        self._ts_manager = None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "WeatherService":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Persistence helpers (graceful degradation)
    # ------------------------------------------------------------------

    async def _get_pg_manager(self):
        """Get Postgres manager with lazy initialization and error handling."""
        if not _PERSISTENCE_AVAILABLE:
            return None
        if self._pg_manager is None:
            try:
                self._pg_manager = get_postgres_manager()
                await self._pg_manager.initialize()
            except Exception as exc:
                logger.warning("PostgreSQL unavailable, continuing without persistence: %s", exc)
                self._pg_manager = None
        return self._pg_manager

    async def _get_ts_manager(self):
        """Get TimescaleDB manager with lazy initialization and error handling."""
        if not _PERSISTENCE_AVAILABLE:
            return None
        if self._ts_manager is None:
            try:
                self._ts_manager = get_timescale_manager()
                await self._ts_manager.initialize()
            except Exception as exc:
                logger.warning("TimescaleDB unavailable, continuing without persistence: %s", exc)
                self._ts_manager = None
        return self._ts_manager

    async def _persist_current_weather(
        self, lat: float, lon: float, data: Dict[str, Any]
    ) -> None:
        """Persist current weather to PostgreSQL and TimescaleDB (fire-and-forget)."""
        pg = await self._get_pg_manager()
        ts = await self._get_ts_manager()
        if not pg and not ts:
            return

        location_name = f"{lat:.4f},{lon:.4f}"
        try:
            if pg:
                location = await pg.upsert_location(location_name, lat, lon)
                current = data.get("current", {})
                await pg.add_forecast_snapshot(
                    location_id=location.id,
                    raw_json=data,
                    temp=current.get("temperature_2m"),
                    precip=current.get("precipitation"),
                    wind=current.get("wind_speed_10m"),
                    source="open-meteo",
                )
            if ts:
                current = data.get("current", {})
                await ts.insert_observation(
                    time=datetime.fromisoformat(current.get("time").replace("Z", "+00:00"))
                    if current.get("time")
                    else datetime.now(timezone.utc),
                    lat=lat,
                    lon=lon,
                    temperature=current.get("temperature_2m"),
                    relative_humidity=current.get("relative_humidity_2m"),
                    precipitation=current.get("precipitation"),
                    wind_speed=current.get("wind_speed_10m"),
                    wind_direction=current.get("wind_direction_10m"),
                    pressure=current.get("pressure_msl"),
                    weather_code=current.get("weather_code"),
                    source="open-meteo",
                    raw_json=data,
                    location_id=location.id if pg else None,
                )
        except Exception as exc:
            logger.warning("Failed to persist current weather: %s", exc)

    async def _persist_forecast(
        self, lat: float, lon: float, data: Dict[str, Any]
    ) -> None:
        """Persist forecast data to PostgreSQL and TimescaleDB (fire-and-forget)."""
        pg = await self._get_pg_manager()
        ts = await self._get_ts_manager()
        if not pg and not ts:
            return

        location_name = f"{lat:.4f},{lon:.4f}"
        try:
            if pg:
                location = await pg.upsert_location(location_name, lat, lon)
                await pg.add_forecast_snapshot(
                    location_id=location.id,
                    raw_json=data,
                    source="open-meteo",
                )
            if ts:
                # Insert hourly observations into TimescaleDB
                hourly_raw = data.get("hourly", {})
                h_times = hourly_raw.get("time", [])
                observations = []
                for i, t in enumerate(h_times):
                    observations.append({
                        "time": datetime.fromisoformat(t.replace("Z", "+00:00")) if t else datetime.now(timezone.utc),
                        "lat": lat,
                        "lon": lon,
                        "temperature": _safe_index(hourly_raw.get("temperature_2m"), i),
                        "precipitation": _safe_index(hourly_raw.get("precipitation"), i),
                        "relative_humidity": None,  # Not in hourly by default
                        "wind_speed": None,
                        "wind_direction": None,
                        "pressure": None,
                        "weather_code": _safe_index(hourly_raw.get("weather_code"), i),
                        "source": "open-meteo",
                        "raw_json": data,
                        "location_id": location.id if pg else None,
                    })
                if observations:
                    await ts.insert_observations_batch(observations)
        except Exception as exc:
            logger.warning("Failed to persist forecast: %s", exc)

    async def _persist_agri_metrics(
        self, lat: float, lon: float, data: Dict[str, Any]
    ) -> None:
        """Persist agricultural metrics to PostgreSQL (fire-and-forget)."""
        pg = await self._get_pg_manager()
        if not pg:
            return

        location_name = f"{lat:.4f},{lon:.4f}"
        try:
            location = await pg.upsert_location(location_name, lat, lon)
            current = data.get("current", {})
            await pg.add_forecast_snapshot(
                location_id=location.id,
                raw_json=data,
                temp=current.get("soil_temperature_0_to_7cm"),
                precip=current.get("soil_moisture_0_to_7cm"),
                wind=None,
                source="open-meteo-agri",
            )
        except Exception as exc:
            logger.warning("Failed to persist agri metrics: %s", exc)

    async def _persist_marine_metrics(
        self, lat: float, lon: float, data: Dict[str, Any]
    ) -> None:
        """Persist marine metrics to PostgreSQL (fire-and-forget)."""
        pg = await self._get_pg_manager()
        if not pg:
            return

        location_name = f"{lat:.4f},{lon:.4f}"
        try:
            location = await pg.upsert_location(location_name, lat, lon)
            current = data.get("current", {})
            await pg.add_forecast_snapshot(
                location_id=location.id,
                raw_json=data,
                temp=current.get("sea_surface_temperature"),
                precip=None,
                wind=current.get("wind_gusts_10m"),
                source="open-meteo-marine",
            )
        except Exception as exc:
            logger.warning("Failed to persist marine metrics: %s", exc)

    # ------------------------------------------------------------------
    # Low-level request helper with exponential backoff
    # ------------------------------------------------------------------

    async def _request(
        self,
        url: str,
        params: Dict[str, Any],
        *,
        cache_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        if cache_key:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        last_exc: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await self._client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if cache_key:
                    await self._cache.set(cache_key, data)
                return data
            except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
                last_exc = exc
                if attempt == MAX_RETRIES - 1:
                    break
                delay = BASE_BACKOFF * (2 ** attempt)
                await asyncio.sleep(delay)

        raise RuntimeError(
            f"Open-Meteo request failed after {MAX_RETRIES} attempts: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # Public helper methods required by the specification
    # ------------------------------------------------------------------

    async def get_current_weather(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Returns temperature, relative humidity, wind speed, pressure,
        weather code, UV index, visibility, dew point, cloud cover,
        wind gusts and feels-like temperature for the given coordinates.
        """
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "precipitation",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "wind_gusts_10m",
                    "weather_code",
                    "pressure_msl",
                    "cloud_cover",
                    "visibility",
                    "dew_point_2m",
                    "uv_index",
                    "is_day",
                ]
            ),
            "timezone": "auto",
        }
        cache_key = f"current:{lat:.4f}:{lon:.4f}"
        data = await self._request(FORECAST_URL, params, cache_key=cache_key)

        current = data.get("current", {})
        result = {
            "temperature": current.get("temperature_2m"),
            "relative_humidity": current.get("relative_humidity_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "precipitation": current.get("precipitation"),
            "wind_speed": current.get("wind_speed_10m"),
            "wind_direction": current.get("wind_direction_10m"),
            "wind_gusts": current.get("wind_gusts_10m"),
            "weather_code": current.get("weather_code"),
            "pressure": current.get("pressure_msl"),
            "cloud_cover": current.get("cloud_cover"),
            "visibility": current.get("visibility"),
            "dew_point_2m": current.get("dew_point_2m"),
            "uv_index": current.get("uv_index"),
            "is_day": current.get("is_day"),
            "time": current.get("time"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "timezone": data.get("timezone"),
        }

        # Persist to database (fire-and-forget, don't block on failure)
        asyncio.create_task(self._persist_current_weather(lat, lon, data))

        return result

    async def get_agricultural_metrics(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Fetches evapotranspiration, soil temperature, soil moisture,
        and leaf wetness probability.
        """
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ",".join(
                [
                    "et0_fao_evapotranspiration",
                    "soil_temperature_0_to_7cm",
                    "soil_temperature_7_to_28cm",
                    "soil_moisture_0_to_7cm",
                    "soil_moisture_7_to_28cm",
                    "leaf_wetness_probability",
                ]
            ),
            "timezone": "auto",
        }
        cache_key = f"agri:{lat:.4f}:{lon:.4f}"
        data = await self._request(FORECAST_URL, params, cache_key=cache_key)

        current = data.get("current", {})
        result = {
            "et0_fao_evapotranspiration": current.get("et0_fao_evapotranspiration"),
            "soil_temperature_0_to_7cm": current.get("soil_temperature_0_to_7cm"),
            "soil_temperature_7_to_28cm": current.get("soil_temperature_7_to_28cm"),
            "soil_moisture_0_to_7cm": current.get("soil_moisture_0_to_7cm"),
            "soil_moisture_7_to_28cm": current.get("soil_moisture_7_to_28cm"),
            "leaf_wetness_probability": current.get("leaf_wetness_probability"),
            "time": current.get("time"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
        }

        # Persist to database (fire-and-forget, don't block on failure)
        asyncio.create_task(self._persist_agri_metrics(lat, lon, data))

        return result

    async def get_marine_metrics(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Fetches wave height, wave direction, swell, ocean surface temperature,
        and wind gusts via Open-Meteo Marine API. Optionally enriches with
        Storm Glass data if STORMGLASS_API_KEY is set.
        """
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ",".join(
                [
                    "wave_height",
                    "wave_direction",
                    "swell_wave_height",
                    "swell_wave_direction",
                    "sea_surface_temperature",
                    "wave_period",
                    "wave_peak_period",
                ]
            ),
            "timezone": "auto",
        }
        cache_key = f"marine:{lat:.4f}:{lon:.4f}"
        data = await self._request(MARINE_URL, params, cache_key=cache_key)

        current = data.get("current", {})

        # Optionally enrich with wind gusts from the main forecast API
        try:
            wind_params = {
                "latitude": lat,
                "longitude": lon,
                "current": "wind_gusts_10m",
                "timezone": "auto",
            }
            wind_data = await self._request(
                FORECAST_URL,
                wind_params,
                cache_key=f"gusts:{lat:.4f}:{lon:.4f}",
            )
            gusts = wind_data.get("current", {}).get("wind_gusts_10m")
        except Exception:
            gusts = None

        # Optionally enrich with Storm Glass data if API key is available
        stormglass_data = None
        stormglass_key = os.getenv("STORMGLASS_API_KEY")
        if stormglass_key:
            try:
                stormglass_data = await self._fetch_stormglass_marine(lat, lon, stormglass_key)
            except Exception:
                stormglass_data = None

        result = {
            "wave_height": current.get("wave_height"),
            "wave_direction": current.get("wave_direction"),
            "swell_wave_height": current.get("swell_wave_height"),
            "swell_wave_direction": current.get("swell_wave_direction"),
            "sea_surface_temperature": current.get("sea_surface_temperature"),
            "wave_period": current.get("wave_period"),
            "wave_peak_period": current.get("wave_peak_period"),
            "wind_gusts": gusts,
            "time": current.get("time"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
        }

        # Merge Storm Glass data if available
        if stormglass_data:
            for key in ["wave_height", "wave_direction", "swell_wave_height", "sea_surface_temperature"]:
                if result.get(key) is None and stormglass_data.get(key) is not None:
                    result[key] = stormglass_data[key]
            for key in ["wave_period", "wave_peak_period", "ocean_current", "water_temperature"]:
                if stormglass_data.get(key) is not None:
                    result[key] = stormglass_data[key]

        # Persist to database (fire-and-forget, don't block on failure)
        asyncio.create_task(self._persist_marine_metrics(lat, lon, data))

        return result

    async def _fetch_stormglass_marine(
        self, lat: float, lon: float, api_key: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch marine data from Storm Glass API (free tier available)."""
        url = "https://api.stormglass.io/v2/weather/point"
        params = {
            "lat": lat,
            "lng": lon,
            "params": "waveHeight,waveDirection,wavePeriod,swellHeight,waterTemperature,currentSpeed,currentDirection",
            "source": "sg",
        }
        headers = {"Authorization": api_key}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    hours = data.get("hours", [{}])[0]
                    return {
                        "wave_height": hours.get("waveHeight", {}).get("sg"),
                        "wave_direction": hours.get("waveDirection", {}).get("sg"),
                        "wave_period": hours.get("wavePeriod", {}).get("sg"),
                        "swell_wave_height": hours.get("swellHeight", {}).get("sg"),
                        "water_temperature": hours.get("waterTemperature", {}).get("sg"),
                        "ocean_current": hours.get("currentSpeed", {}).get("sg"),
                    }
        except Exception:
            pass
        return None

    async def geocode(self, query: str, count: int = 5) -> List[Dict[str, Any]]:
        """
        Convert a city/place name into coordinates using Open-Meteo Geocoding.
        Returns list of {name, country, admin1, latitude, longitude}.
        """
        params = {"name": query, "count": count, "language": "en"}
        cache_key = f"geocode:{query.lower()}:{count}"
        data = await self._request(GEOCODING_URL, params, cache_key=cache_key)
        results = []
        for item in data.get("results", []):
            results.append(
                {
                    "name": item.get("name"),
                    "country": item.get("country"),
                    "admin1": item.get("admin1"),
                    "latitude": item.get("latitude"),
                    "longitude": item.get("longitude"),
                }
            )
        return results
    # ------------------------------------------------------------------
    # Full forecast (current + hourly + daily for 7 days)
    # ------------------------------------------------------------------

    async def get_forecast(
        self,
        lat: float,
        lon: float,
        days: int = 7,
    ) -> ForecastResponse:
        """
        Fetch current conditions together with hourly and daily forecasts
        for the next `days` (default 7).
        """
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "precipitation",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "wind_gusts_10m",
                    "weather_code",
                    "pressure_msl",
                    "cloud_cover",
                    "visibility",
                    "dew_point_2m",
                    "uv_index",
                    "is_day",
                ]
            ),
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "precipitation",
                    "precipitation_probability",
                    "weather_code",
                ]
            ),
            "daily": ",".join(
                [
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_sum",
                    "precipitation_probability_max",
                    "weather_code",
                ]
            ),
            "forecast_days": min(max(days, 1), 16),
            "timezone": "auto",
        }
        cache_key = f"forecast:{lat:.4f}:{lon:.4f}:{days}"
        data = await self._request(FORECAST_URL, params, cache_key=cache_key)

        # Current
        cur = data.get("current", {})
        current = CurrentWeather(
            temperature=cur.get("temperature_2m"),
            relative_humidity=cur.get("relative_humidity_2m"),
            apparent_temperature=cur.get("apparent_temperature"),
            precipitation=cur.get("precipitation"),
            wind_speed=cur.get("wind_speed_10m"),
            wind_direction=cur.get("wind_direction_10m"),
            wind_gusts=cur.get("wind_gusts_10m"),
            weather_code=cur.get("weather_code"),
            pressure_msl=cur.get("pressure_msl"),
            cloud_cover=cur.get("cloud_cover"),
            visibility=cur.get("visibility"),
            dew_point_2m=cur.get("dew_point_2m"),
            uv_index=cur.get("uv_index"),
            is_day=cur.get("is_day"),
            time=cur.get("time"),
        )

        # Daily
        daily_raw = data.get("daily", {})
        times = daily_raw.get("time", [])
        daily: List[DailyForecastDay] = []
        for i, date in enumerate(times):
            daily.append(
                DailyForecastDay(
                    date=date,
                    temperature_max=_safe_index(daily_raw.get("temperature_2m_max"), i),
                    temperature_min=_safe_index(daily_raw.get("temperature_2m_min"), i),
                    precipitation_sum=_safe_index(daily_raw.get("precipitation_sum"), i),
                    precipitation_probability_max=_safe_index(
                        daily_raw.get("precipitation_probability_max"), i
                    ),
                    weather_code=_safe_index(daily_raw.get("weather_code"), i),
                )
            )

        # Hourly
        hourly_raw = data.get("hourly", {})
        h_times = hourly_raw.get("time", [])
        hourly: List[HourlyForecastPoint] = []
        for i, t in enumerate(h_times):
            hourly.append(
                HourlyForecastPoint(
                    time=t,
                    temperature=_safe_index(hourly_raw.get("temperature_2m"), i),
                    precipitation=_safe_index(hourly_raw.get("precipitation"), i),
                    precipitation_probability=_safe_index(
                        hourly_raw.get("precipitation_probability"), i
                    ),
                    weather_code=_safe_index(hourly_raw.get("weather_code"), i),
                )
            )

        result = ForecastResponse(
            latitude=data.get("latitude", lat),
            longitude=data.get("longitude", lon),
            timezone=data.get("timezone"),
            current=current,
            daily=daily,
            hourly=hourly,
        )

        # Persist to database (fire-and-forget, don't block on failure)
        asyncio.create_task(self._persist_forecast(lat, lon, data))

        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_index(seq: Optional[List[Any]], idx: int) -> Any:
    if seq is None or idx >= len(seq):
        return None
    return seq[idx]


# ---------------------------------------------------------------------------
# Convenience factory for FastAPI dependency injection
# ---------------------------------------------------------------------------

_default_service: Optional[WeatherService] = None


def get_weather_service() -> WeatherService:
    """
    FastAPI-compatible dependency that returns a shared WeatherService instance.
    """
    global _default_service
    if _default_service is None:
        _default_service = WeatherService()
    return _default_service


# ---------------------------------------------------------------------------
# Example usage (run with: python weather_service.py)
# ---------------------------------------------------------------------------

async def _demo() -> None:
    async with WeatherService() as svc:
        # Berlin coordinates
        lat, lon = 52.52, 13.41

        print("=== Current Weather ===")
        current = await svc.get_current_weather(lat, lon)
        print(current)

        print("\n=== Agricultural Metrics ===")
        agri = await svc.get_agricultural_metrics(lat, lon)
        print(agri)

        print("\n=== Marine Metrics (example coastal) ===")
        # Use a coastal point (e.g. near Lisbon)
        marine = await svc.get_marine_metrics(38.72, -9.14)
        print(marine)

        print("\n=== 7-day Forecast (summary) ===")
        forecast = await svc.get_forecast(lat, lon, days=7)
        print(f"Timezone: {forecast.timezone}")
        if forecast.current:
            print(f"Current temp: {forecast.current.temperature} °C")
        print(f"Daily days returned: {len(forecast.daily)}")
        print(f"Hourly points returned: {len(forecast.hourly)}")


if __name__ == "__main__":
    asyncio.run(_demo())
