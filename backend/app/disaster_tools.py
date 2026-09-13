"""
Disaster / hazard alert layer for the map feature.
=====================================================
Combines three real, free, no-API-key data sources into one unified feed
the map can render as colored/symbolic zones:

  - Earthquakes  -> USGS Earthquake Catalog (global, reliable, near-real-time)
  - Cyclone / Flood / Drought / Volcano -> GDACS (Global Disaster Alert and
    Coordination System — UN/EU-backed, free, covers India)
  - Thunderstorm / lightning RISK -> derived proxy from Open-Meteo's
    forecast (CAPE + weather code), since there is no free, public,
    real-time lightning-strike API. This is clearly labeled as a modeled
    risk zone, not a confirmed strike map — do not present it as one.
  - Tornado: NOT included. Tornadoes are rare in India and there is no
    reliable free real-time detection/alert source. If you need this,
    you'd be looking at a paid regional radar-derived product — flagging
    honestly rather than faking coverage.

Severity is normalized to IMD's own 4-level public alert convention
(green / yellow / orange / red), since that's the color language Indian
users already recognize from official weather bulletins — the map's
legend should use these same four colors for consistency.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger("weathergpt.disaster_tools")

USGS_QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
GDACS_SEARCH_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Rough India bounding box (mainland + islands), used to filter GDACS'
# global feed down to events relevant to this app.
INDIA_BBOX = {"min_lat": 6.0, "max_lat": 38.0, "min_lon": 68.0, "max_lon": 98.0}

SEVERITY_COLORS = {
    "green": "#2E9E5B",
    "yellow": "#E4B92F",
    "orange": "#E8720C",
    "red": "#D8402A",
}


def _within_bbox(lat: float, lon: float, bbox: dict) -> bool:
    return bbox["min_lat"] <= lat <= bbox["max_lat"] and bbox["min_lon"] <= lon <= bbox["max_lon"]


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    from math import radians, sin, cos, sqrt, atan2

    r = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


# ─────────────────────────────────────────────────────────────────────────
# Earthquakes — USGS
# ─────────────────────────────────────────────────────────────────────────

def _quake_severity(magnitude: float) -> str:
    if magnitude >= 6.5:
        return "red"
    if magnitude >= 5.5:
        return "orange"
    if magnitude >= 4.5:
        return "yellow"
    return "green"


async def _fetch_earthquakes(
    latitude: float, longitude: float, radius_km: float, min_magnitude: float, days: int
) -> list[dict]:
    params = {
        "format": "geojson",
        "latitude": latitude,
        "longitude": longitude,
        "maxradiuskm": radius_km,
        "minmagnitude": min_magnitude,
        "starttime": (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d"),
        "orderby": "time",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(USGS_QUERY_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    features = []
    for f in data.get("features", []):
        props = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates", [None, None, None])
        lon, lat, depth_km = coords[0], coords[1], coords[2]
        magnitude = props.get("mag")
        if lat is None or lon is None or magnitude is None:
            continue
        features.append(
            {
                "hazard_type": "earthquake",
                "severity": _quake_severity(magnitude),
                "title": f"M{magnitude:.1f} earthquake — {props.get('place', 'unknown location')}",
                "description": f"Depth {depth_km:.0f} km" if depth_km is not None else "",
                "latitude": lat,
                "longitude": lon,
                "geometry_type": "point",
                "magnitude": magnitude,
                "source": "USGS",
                "event_time": (
                    datetime.fromtimestamp(props["time"] / 1000, tz=timezone.utc).isoformat()
                    if props.get("time")
                    else None
                ),
                "url": props.get("url"),
            }
        )
    return features


# ─────────────────────────────────────────────────────────────────────────
# Cyclone / Flood / Drought / Volcano — GDACS
# ─────────────────────────────────────────────────────────────────────────

GDACS_TYPE_LABELS = {
    "TC": "cyclone",
    "FL": "flood",
    "DR": "drought",
    "VO": "volcano",
    "WF": "wildfire",
}

GDACS_ALERT_TO_SEVERITY = {"green": "green", "orange": "orange", "red": "red"}


async def _fetch_gdacs_events(days: int) -> list[dict]:
    params = {
        "eventlist": "TC;FL;DR;VO",
        "alertlevel": "green;orange;red",
        "fromdate": (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d"),
        "todate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(GDACS_SEARCH_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    raw_events = data.get("features", data if isinstance(data, list) else [])
    features = []
    for ev in raw_events:
        props = ev.get("properties", ev) if isinstance(ev, dict) else {}
        geom = ev.get("geometry", {}) if isinstance(ev, dict) else {}
        coords = geom.get("coordinates") if geom else None
        if not coords or len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]

        # Filter to India-relevant events only — GDACS is a global feed.
        if not _within_bbox(lat, lon, INDIA_BBOX):
            continue

        event_type = props.get("eventtype") or props.get("eventType")
        alert_level = str(props.get("alertlevel") or props.get("alertLevel") or "green").lower()

        features.append(
            {
                "hazard_type": GDACS_TYPE_LABELS.get(event_type, event_type or "unknown"),
                "severity": GDACS_ALERT_TO_SEVERITY.get(alert_level, "green"),
                "title": props.get("eventname") or props.get("name") or props.get("htmldescription", ""),
                "description": props.get("description", "") or "",
                "latitude": lat,
                "longitude": lon,
                "geometry_type": "point",  # GDACS also offers detailed polygons via a
                # separate getgeometry endpoint per event — fetch that per-event if
                # your map needs the actual affected-area outline, not just the centroid.
                "source": "GDACS",
                "event_time": props.get("todate") or props.get("fromdate"),
                "url": props.get("url", {}).get("report") if isinstance(props.get("url"), dict) else None,
            }
        )
    return features


# ─────────────────────────────────────────────────────────────────────────
# Thunderstorm / lightning RISK proxy — Open-Meteo (modeled, not observed)
# ─────────────────────────────────────────────────────────────────────────

# Open-Meteo WMO weather codes for thunderstorm conditions.
THUNDERSTORM_CODES = {95, 96, 99}


async def _fetch_thunderstorm_risk(latitude: float, longitude: float) -> list[dict]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "cape,weather_code,precipitation_probability",
        "forecast_days": 2,
        "timezone": "Asia/Kolkata",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(OPEN_METEO_FORECAST_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    hourly = data.get("hourly", {})
    codes = hourly.get("weather_code", [])
    capes = hourly.get("cape", [])
    times = hourly.get("time", [])

    max_cape = max(capes[:24], default=0) if capes else 0
    has_storm_code = any(c in THUNDERSTORM_CODES for c in codes[:24])

    if not has_storm_code and max_cape < 1000:
        return []  # low risk — don't clutter the map with a zone

    severity = "red" if (has_storm_code and max_cape >= 2000) else "orange" if has_storm_code else "yellow"

    return [
        {
            "hazard_type": "thunderstorm_risk",
            "severity": severity,
            "title": "Elevated thunderstorm / lightning risk (modeled, next 24h)",
            "description": (
                f"Peak CAPE ~{max_cape:.0f} J/kg in the next 24h. This is a MODELED risk "
                "zone from forecast instability, not a confirmed lightning strike map."
            ),
            "latitude": latitude,
            "longitude": longitude,
            "geometry_type": "point",
            "source": "Open-Meteo (derived)",
            "event_time": times[0] if times else None,
            "url": None,
        }
    ]


# ─────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────

TOOL_SCHEMA = {
    "name": "get_disaster_alerts",
    "description": (
        "Get active/recent disaster and hazard alerts (earthquakes, cyclones, "
        "floods, droughts, and modeled thunderstorm/lightning risk) within a "
        "radius of a latitude/longitude. Use this to answer questions about "
        "disasters happening elsewhere, or to populate a hazard map."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "radius_km": {
                "type": "number",
                "description": "Search radius in km for earthquakes specifically (GDACS events are filtered to the India region regardless). Default 300.",
            },
        },
        "required": ["latitude", "longitude"],
    },
}


async def get_disaster_alerts(
    latitude: float, longitude: float, radius_km: float = 300, days: int = 14
) -> dict:
    """
    Returns a unified list of hazard features, each with the fields the
    map needs: hazard_type, severity (green/yellow/orange/red), title,
    description, latitude, longitude, source, event_time, url.
    
    For earthquakes: fetches all India earthquakes (large radius)
    For GDACS: fetches all India events via bbox filter
    For thunderstorm: shows risk for the clicked location
    """
    results: list[dict] = []
    sources_ok, sources_failed = [], []

    try:
        # Fetch earthquakes for all India (2000km radius covers entire country)
        results += await _fetch_earthquakes(latitude, longitude, radius_km=2000, min_magnitude=3.0, days=days)
        sources_ok.append("USGS")
    except Exception as e:  # noqa: BLE001
        logger.warning("USGS fetch failed: %s", e)
        sources_failed.append("USGS")

    try:
        results += await _fetch_gdacs_events(days=days)
        sources_ok.append("GDACS")
    except Exception as e:  # noqa: BLE001
        logger.warning("GDACS fetch failed: %s", e)
        sources_failed.append("GDACS")

    try:
        # Thunderstorm risk for the selected location
        results += await _fetch_thunderstorm_risk(latitude, longitude)
        sources_ok.append("Open-Meteo")
    except Exception as e:  # noqa: BLE001
        logger.warning("Thunderstorm risk fetch failed: %s", e)
        sources_failed.append("Open-Meteo")

    for r in results:
        r["distance_km"] = round(_haversine_km(latitude, longitude, r["latitude"], r["longitude"]), 1)
        r["color"] = SEVERITY_COLORS[r["severity"]]

    results.sort(key=lambda r: r["distance_km"])

    return {
        "alerts": results,
        "sources_ok": sources_ok,
        "sources_failed": sources_failed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "thunderstorm_risk is a modeled forecast proxy, not confirmed lightning strikes. Tornado alerts are not covered — no reliable free real-time source exists for India.",
    }


async def execute_disaster_tool(name: str, tool_input: dict) -> dict:
    """Same dispatch contract as weather_tools.execute_tool."""
    if name != "get_disaster_alerts":
        return {"error": f"Unknown tool: {name}"}
    try:
        return await get_disaster_alerts(
            tool_input["latitude"], tool_input["longitude"], tool_input.get("radius_km", 300)
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"Disaster alert lookup failed: {str(e)}"}

