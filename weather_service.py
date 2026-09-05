"""
weather_service.py

Asynchronous weather service using httpx and the free Open-Meteo APIs.
Provides current weather, 7-day forecasts, agricultural metrics, and marine data.
Includes in-memory TTL cache (15 min) and exponential-backoff retries.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
MAX_RETRIES = 4
BASE_BACKOFF = 0.5  # seconds


# ---------------------------------------------------------------------------
# Pydantic / dataclass response models
# ---------------------------------------------------------------------------

class CurrentWeather(BaseModel):
    temperature: Optional[float] = None
    relative_humidity: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    weather_code: Optional[int] = None
    pressure_msl: Optional[float] = None
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

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "WeatherService":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

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
        and weather code for the given coordinates.
        """
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "precipitation",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "weather_code",
                    "pressure_msl",
                ]
            ),
            "timezone": "auto",
        }
        cache_key = f"current:{lat:.4f}:{lon:.4f}"
        data = await self._request(FORECAST_URL, params, cache_key=cache_key)

        current = data.get("current", {})
        return {
            "temperature": current.get("temperature_2m"),
            "relative_humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "wind_speed": current.get("wind_speed_10m"),
            "wind_direction": current.get("wind_direction_10m"),
            "weather_code": current.get("weather_code"),
            "pressure": current.get("pressure_msl"),
            "time": current.get("time"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "timezone": data.get("timezone"),
        }

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
        return {
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

    async def get_marine_metrics(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Fetches wave height, wave direction, swell, ocean surface temperature,
        and wind gusts via the Marine API.
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
                ]
            ),
            # Wind gusts come from the regular forecast endpoint; we request
            # them together for convenience when possible.
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

        return {
            "wave_height": current.get("wave_height"),
            "wave_direction": current.get("wave_direction"),
            "swell_wave_height": current.get("swell_wave_height"),
            "swell_wave_direction": current.get("swell_wave_direction"),
            "sea_surface_temperature": current.get("sea_surface_temperature"),
            "wind_gusts": gusts,
            "time": current.get("time"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
        }

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
                    "precipitation",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "weather_code",
                    "pressure_msl",
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
            precipitation=cur.get("precipitation"),
            wind_speed=cur.get("wind_speed_10m"),
            wind_direction=cur.get("wind_direction_10m"),
            weather_code=cur.get("weather_code"),
            pressure_msl=cur.get("pressure_msl"),
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

        return ForecastResponse(
            latitude=data.get("latitude", lat),
            longitude=data.get("longitude", lon),
            timezone=data.get("timezone"),
            current=current,
            daily=daily,
            hourly=hourly,
        )


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