"""
WeatherGPT — Tool Calling Layer
================================
Defines the Claude tool schemas + the actual async implementations that
fetch live data to ground WeatherGPT's answers.

Grounding source used here: Open-Meteo (free, no API key, good India
coverage, includes a marine API). Swap `_call_open_meteo` /
`_call_open_meteo_marine` for IMD/ECMWF/private feeds in production —
the tool schema and calling contract stay identical.
"""

import httpx

from disaster_tools import TOOL_SCHEMA as DISASTER_TOOL_SCHEMA
from disaster_tools import execute_disaster_tool

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


# ─────────────────────────────────────────────────────────────────────────
# Tool schemas (passed to the Anthropic API `tools` parameter)
# ─────────────────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "get_weather_data",
        "description": (
            "Get current conditions and a multi-day forecast (temperature, "
            "precipitation, humidity, wind, soil moisture) for a specific "
            "latitude/longitude. Use this for farmer and general-citizen "
            "questions about land-based weather, rainfall, heat, or "
            "irrigation/spraying windows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Decimal latitude"},
                "longitude": {"type": "number", "description": "Decimal longitude"},
                "days": {
                    "type": "integer",
                    "description": "Forecast horizon in days (1-7). Default 3.",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_marine_data",
        "description": (
            "Get marine forecast (wave height, swell period/direction, wind "
            "wave height, sea surface temperature where available) for a "
            "coastal latitude/longitude. Use this for sailor/fisherman "
            "questions about sea state and navigation safety."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Decimal latitude of the coastal point"},
                "longitude": {"type": "number", "description": "Decimal longitude of the coastal point"},
                "days": {
                    "type": "integer",
                    "description": "Forecast horizon in days (1-5). Default 3.",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_air_quality",
        "description": (
            "Get current Air Quality Index (AQI) and UV index for a "
            "latitude/longitude. Use for citizen health/travel advisories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "geocode_location",
        "description": (
            "Resolve a place name (village, town, district, harbour name) "
            "typed by the user into latitude/longitude, when GPS "
            "coordinates were not supplied by the client."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "place_name": {"type": "string", "description": "Free-text place name, e.g. 'Sundarbans' or 'Veraval harbour'"},
            },
            "required": ["place_name"],
        },
    },
    DISASTER_TOOL_SCHEMA,
]


# ─────────────────────────────────────────────────────────────────────────
# Implementations
# ─────────────────────────────────────────────────────────────────────────

async def _call_open_meteo(latitude: float, longitude: float, days: int = 3) -> dict:
    days = max(1, min(days, 7))
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m,weather_code",
        "hourly": "temperature_2m,precipitation_probability,soil_moisture_0_to_1cm,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
        "forecast_days": days,
        "timezone": "Asia/Kolkata",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(OPEN_METEO_FORECAST_URL, params=params)
        resp.raise_for_status()
        return resp.json()


async def _call_open_meteo_marine(latitude: float, longitude: float, days: int = 3) -> dict:
    days = max(1, min(days, 5))
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "wave_height,wave_direction,wave_period,wind_wave_height,swell_wave_height,swell_wave_period,swell_wave_direction",
        "daily": "wave_height_max,wind_wave_height_max,swell_wave_height_max",
        "forecast_days": days,
        "timezone": "Asia/Kolkata",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(OPEN_METEO_MARINE_URL, params=params)
        resp.raise_for_status()
        return resp.json()


async def _call_air_quality(latitude: float, longitude: float) -> dict:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "us_aqi,pm2_5,pm10,uv_index",
        "timezone": "Asia/Kolkata",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(OPEN_METEO_AIR_QUALITY_URL, params=params)
        resp.raise_for_status()
        return resp.json()


async def _call_geocode(place_name: str) -> dict:
    params = {"name": place_name, "count": 3, "language": "en", "format": "json", "countryCode": "IN"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(OPEN_METEO_GEOCODE_URL, params=params)
        resp.raise_for_status()
        return resp.json()


async def execute_tool(name: str, tool_input: dict) -> dict:
    """
    Dispatch a Claude tool_use block to the matching implementation.
    Always returns a JSON-serializable dict — errors are returned as a
    dict with an "error" key rather than raised, so the model can react
    gracefully (e.g. tell the user live data is unavailable) instead of
    the whole request failing.
    """
    try:
        if name == "get_weather_data":
            return await _call_open_meteo(
                tool_input["latitude"], tool_input["longitude"], tool_input.get("days", 3)
            )
        if name == "get_marine_data":
            return await _call_open_meteo_marine(
                tool_input["latitude"], tool_input["longitude"], tool_input.get("days", 3)
            )
        if name == "get_air_quality":
            return await _call_air_quality(tool_input["latitude"], tool_input["longitude"])
        if name == "geocode_location":
            return await _call_geocode(tool_input["place_name"])
        if name == "get_disaster_alerts":
            return await execute_disaster_tool(name, tool_input)
        return {"error": f"Unknown tool: {name}"}
    except httpx.HTTPStatusError as e:
        return {"error": f"Upstream weather API returned {e.response.status_code}"}
    except httpx.RequestError as e:
        return {"error": f"Could not reach upstream weather API: {e!s}"}
    except Exception as e:  # noqa: BLE001 - surfaced to the model as data, not a crash
        return {"error": f"Tool execution failed: {e!s}"}
