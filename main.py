"""
main.py – Production-ready FastAPI application for WeatherGPT.

Exposes REST endpoints backed by weather_service.py (Open-Meteo).
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, confloat

from weather_service import WeatherService, get_weather_service
from auth_db import init_db, create_user, get_user_by_email, get_user_by_id

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger("weathergpt.main")

# ---------------------------------------------------------------------------
# Auth (JWT)
# ---------------------------------------------------------------------------

import hashlib
import os
import secrets

import jwt

JWT_SECRET = os.getenv("JWT_SECRET", "weathergpt-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

init_db()


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${hashed.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    salt, hashed = stored.split("$")
    computed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return computed.hex() == hashed


def _create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc).timestamp() + JWT_EXPIRY_HOURS * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


class SignUpRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=4)
    name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str] = None

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="WeatherGPT API",
    description=(
        "Production REST API providing real-time weather, agricultural, "
        "marine and NDMA-style colour-coded alerts powered by Open-Meteo."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Pydantic v2 models – request / response
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp")
    service: str = Field(default="WeatherGPT")


class CurrentWeatherResponse(BaseModel):
    temperature: Optional[float] = Field(None, description="°C")
    relative_humidity: Optional[float] = Field(None, description="%")
    apparent_temperature: Optional[float] = Field(None, description="Feels-like °C")
    precipitation: Optional[float] = Field(None, description="mm")
    wind_speed: Optional[float] = Field(None, description="km/h")
    wind_direction: Optional[float] = Field(None, description="degrees")
    wind_gusts: Optional[float] = Field(None, description="km/h")
    weather_code: Optional[int] = None
    pressure: Optional[float] = Field(None, description="hPa")
    cloud_cover: Optional[float] = Field(None, description="%")
    visibility: Optional[float] = Field(None, description="m")
    dew_point_2m: Optional[float] = Field(None, description="°C")
    uv_index: Optional[float] = Field(None, description="0-11+")
    is_day: Optional[int] = Field(None, description="1=day, 0=night")
    time: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None


class AgriMetricsResponse(BaseModel):
    et0_fao_evapotranspiration: Optional[float] = Field(None, description="mm")
    soil_temperature_0_to_7cm: Optional[float] = Field(None, description="°C")
    soil_temperature_7_to_28cm: Optional[float] = Field(None, description="°C")
    soil_moisture_0_to_7cm: Optional[float] = Field(None, description="m³/m³")
    soil_moisture_7_to_28cm: Optional[float] = Field(None, description="m³/m³")
    leaf_wetness_probability: Optional[float] = Field(None, description="%")
    time: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class MarineMetricsResponse(BaseModel):
    wave_height: Optional[float] = Field(None, description="m")
    wave_direction: Optional[float] = Field(None, description="degrees")
    swell_wave_height: Optional[float] = Field(None, description="m")
    swell_wave_direction: Optional[float] = Field(None, description="degrees")
    sea_surface_temperature: Optional[float] = Field(None, description="°C")
    wind_gusts: Optional[float] = Field(None, description="km/h")
    time: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class DailyForecastItem(BaseModel):
    date: str
    temperature_max: Optional[float] = None
    temperature_min: Optional[float] = None
    precipitation_sum: Optional[float] = None
    precipitation_probability_max: Optional[float] = None
    weather_code: Optional[int] = None


class HourlyForecastItem(BaseModel):
    time: str
    temperature: Optional[float] = None
    precipitation: Optional[float] = None
    precipitation_probability: Optional[float] = None
    weather_code: Optional[int] = None


class ForecastResponse(BaseModel):
    latitude: float
    longitude: float
    timezone: Optional[str] = None
    current: Optional[CurrentWeatherResponse] = None
    daily: List[DailyForecastItem] = Field(default_factory=list)
    hourly: List[HourlyForecastItem] = Field(default_factory=list)


class AlertLevel(str, Enum):
    GREEN = "Green"
    YELLOW = "Yellow"
    ORANGE = "Orange"
    RED = "Red"


class AlertItem(BaseModel):
    level: AlertLevel
    color: str
    title: str
    description: str
    wind_speed_kmh: Optional[float] = None
    precipitation_mm: Optional[float] = None
    issued_at: str


class AlertsResponse(BaseModel):
    latitude: float
    longitude: float
    active_alerts: List[AlertItem]
    overall_level: AlertLevel
    timestamp: str


# ---------------------------------------------------------------------------
# Drafted alert request / response models (human approval workflow)
# ---------------------------------------------------------------------------

class AlertDraftResponse(BaseModel):
    id: str
    event_id: str
    event_fingerprint: str
    language: str
    script_text: str
    severity: str
    hazard_type: str
    title: str
    description: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: str
    event_time: Optional[str] = None
    change_type: str
    delivery_status: str
    generated_at: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    audit_log: list = Field(default_factory=list, description="Audit trail of draft actions")


class AlertApprovalRequest(BaseModel):
    approved_by: str = Field(..., min_length=1, description="Human reviewer identity")


class AlertRejectionRequest(BaseModel):
    rejected_by: str = Field(..., min_length=1, description="Human reviewer identity")
    reason: Optional[str] = Field(None, description="Optional rejection reason")


# ---------------------------------------------------------------------------
# Alert logic (simple NDMA-style thresholds)
# ---------------------------------------------------------------------------

def _evaluate_alerts(
    lat: float,
    lon: float,
    wind_speed: Optional[float],
    precipitation: Optional[float],
) -> AlertsResponse:
    """
    Derive colour-coded alerts from current wind and precipitation.
    Thresholds are indicative and can be tuned for production.
    """
    now = datetime.now(timezone.utc).isoformat()
    alerts: List[AlertItem] = []

    wind = wind_speed or 0.0
    precip = precipitation or 0.0

    # Wind-based alerts
    if wind >= 80:
        alerts.append(
            AlertItem(
                level=AlertLevel.RED,
                color="#FF0000",
                title="Severe Wind Warning",
                description="Extremely strong winds. Avoid outdoor activity and coastal areas.",
                wind_speed_kmh=wind,
                precipitation_mm=precip,
                issued_at=now,
            )
        )
    elif wind >= 60:
        alerts.append(
            AlertItem(
                level=AlertLevel.ORANGE,
                color="#FFA500",
                title="High Wind Alert",
                description="Strong winds expected. Secure loose objects.",
                wind_speed_kmh=wind,
                precipitation_mm=precip,
                issued_at=now,
            )
        )
    elif wind >= 40:
        alerts.append(
            AlertItem(
                level=AlertLevel.YELLOW,
                color="#FFFF00",
                title="Moderate Wind Advisory",
                description="Elevated wind speeds. Exercise caution.",
                wind_speed_kmh=wind,
                precipitation_mm=precip,
                issued_at=now,
            )
        )

    # Precipitation-based alerts
    if precip >= 50:
        alerts.append(
            AlertItem(
                level=AlertLevel.RED,
                color="#FF0000",
                title="Extremely Heavy Rainfall",
                description="Very heavy rain. High risk of flooding and waterlogging.",
                wind_speed_kmh=wind,
                precipitation_mm=precip,
                issued_at=now,
            )
        )
    elif precip >= 25:
        alerts.append(
            AlertItem(
                level=AlertLevel.ORANGE,
                color="#FFA500",
                title="Heavy Rainfall Warning",
                description="Heavy rain likely. Possible localised flooding.",
                wind_speed_kmh=wind,
                precipitation_mm=precip,
                issued_at=now,
            )
        )
    elif precip >= 10:
        alerts.append(
            AlertItem(
                level=AlertLevel.YELLOW,
                color="#FFFF00",
                title="Moderate Rainfall Advisory",
                description="Moderate rainfall expected. Carry umbrella / plan travel accordingly.",
                wind_speed_kmh=wind,
                precipitation_mm=precip,
                issued_at=now,
            )
        )

    if not alerts:
        alerts.append(
            AlertItem(
                level=AlertLevel.GREEN,
                color="#00AA00",
                title="No Active Weather Alerts",
                description="Current conditions are within normal range.",
                wind_speed_kmh=wind,
                precipitation_mm=precip,
                issued_at=now,
            )
        )

    # Overall level = highest severity present
    severity_order = {
        AlertLevel.GREEN: 0,
        AlertLevel.YELLOW: 1,
        AlertLevel.ORANGE: 2,
        AlertLevel.RED: 3,
    }
    overall = max(alerts, key=lambda a: severity_order[a.level]).level

    return AlertsResponse(
        latitude=lat,
        longitude=lon,
        active_alerts=alerts,
        overall_level=overall,
        timestamp=now,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.post(
    "/api/v1/auth/signup",
    response_model=TokenResponse,
    tags=["Auth"],
    summary="Register a new user (form-encoded)",
)
async def signup(
    email: str = Form(..., min_length=3),
    password: str = Form(..., min_length=4),
    name: Optional[str] = Form(None),
) -> TokenResponse:
    """Create a new user account and return a JWT token."""
    existing = get_user_by_email(email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    user_id = secrets.token_hex(8)
    password_hash = _hash_password(password)
    if not create_user(user_id, email, password_hash, name or ""):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    return TokenResponse(access_token=_create_token(user_id, email))


@app.post(
    "/api/v1/auth/login",
    response_model=TokenResponse,
    tags=["Auth"],
    summary="Log in and receive a JWT token (form-encoded)",
)
async def login(
    email: str = Form(...),
    password: str = Form(...),
) -> TokenResponse:
    """Authenticate a user and return a JWT token."""
    udata = get_user_by_email(email)
    if udata is not None and _verify_password(password, udata["password_hash"]):
        return TokenResponse(access_token=_create_token(udata["id"], email))
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
    )


@app.get(
    "/api/v1/auth/me",
    response_model=UserResponse,
    tags=["Auth"],
    summary="Get current user info",
)
async def get_current_user(request: Request) -> UserResponse:
    """Return the current user's information based on the JWT token."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )
    token = auth_header[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user_id = payload.get("sub", "")
    udata = get_user_by_id(user_id)
    if udata is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return UserResponse(
        id=user_id,
        email=udata["email"],
        name=udata.get("name") or None,
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health check",
)
async def health() -> HealthResponse:
    """Return service status and current UTC timestamp."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        service="WeatherGPT",
    )


@app.get(
    "/api/v1/weather/current",
    response_model=CurrentWeatherResponse,
    tags=["Weather"],
    summary="Current weather conditions",
)
async def get_current_weather(
    lat: Annotated[float, Field(ge=-90, le=90)] = Query(..., description="Latitude"),
    lon: Annotated[float, Field(ge=-180, le=180)] = Query(..., description="Longitude"),
    svc: WeatherService = Depends(get_weather_service),
) -> CurrentWeatherResponse:
    """
    Return current temperature, humidity, wind, precipitation,
    pressure and weather code for the given coordinates.
    """
    try:
        data = await svc.get_current_weather(float(lat), float(lon))
        return CurrentWeatherResponse(**data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream weather service error: {exc}",
        ) from exc


@app.get(
    "/api/v1/weather/agri",
    response_model=AgriMetricsResponse,
    tags=["Weather"],
    summary="Agricultural metrics",
)
async def get_agricultural_metrics(
    lat: Annotated[float, Field(ge=-90, le=90)] = Query(..., description="Latitude"),
    lon: Annotated[float, Field(ge=-180, le=180)] = Query(..., description="Longitude"),
    svc: WeatherService = Depends(get_weather_service),
) -> AgriMetricsResponse:
    """
    Return evapotranspiration, soil temperature / moisture and
    leaf-wetness probability.
    """
    try:
        data = await svc.get_agricultural_metrics(float(lat), float(lon))
        return AgriMetricsResponse(**data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream weather service error: {exc}",
        ) from exc


@app.get(
    "/api/v1/weather/marine",
    response_model=MarineMetricsResponse,
    tags=["Weather"],
    summary="Marine / coastal metrics",
)
async def get_marine_metrics(
    lat: Annotated[float, Field(ge=-90, le=90)] = Query(..., description="Latitude"),
    lon: Annotated[float, Field(ge=-180, le=180)] = Query(..., description="Longitude"),
    svc: WeatherService = Depends(get_weather_service),
) -> MarineMetricsResponse:
    """
    Return wave height, direction, swell, sea-surface temperature
    and wind gusts (coastal / marine locations).
    """
    try:
        data = await svc.get_marine_metrics(float(lat), float(lon))
        return MarineMetricsResponse(**data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream marine service error: {exc}",
        ) from exc


@app.get(
    "/api/v1/weather/forecast",
    response_model=ForecastResponse,
    tags=["Weather"],
    summary="7-day forecast (hourly + daily)",
)
async def get_forecast(
    lat: Annotated[float, Field(ge=-90, le=90)] = Query(..., description="Latitude"),
    lon: Annotated[float, Field(ge=-180, le=180)] = Query(..., description="Longitude"),
    days: int = Query(7, ge=1, le=16, description="Number of forecast days"),
    svc: WeatherService = Depends(get_weather_service),
) -> ForecastResponse:
    """
    Return current conditions together with hourly and daily forecasts
    for the requested number of days (default 7).
    """
    try:
        forecast = await svc.get_forecast(float(lat), float(lon), days=days)
        # Convert internal models to response models
        current = None
        if forecast.current:
            current = CurrentWeatherResponse(
                temperature=forecast.current.temperature,
                relative_humidity=forecast.current.relative_humidity,
                apparent_temperature=forecast.current.apparent_temperature,
                precipitation=forecast.current.precipitation,
                wind_speed=forecast.current.wind_speed,
                wind_direction=forecast.current.wind_direction,
                wind_gusts=forecast.current.wind_gusts,
                weather_code=forecast.current.weather_code,
                pressure=forecast.current.pressure_msl,
                cloud_cover=forecast.current.cloud_cover,
                visibility=forecast.current.visibility,
                dew_point_2m=forecast.current.dew_point_2m,
                uv_index=forecast.current.uv_index,
                is_day=forecast.current.is_day,
                time=forecast.current.time,
            )
        daily = [
            DailyForecastItem(
                date=d.date,
                temperature_max=d.temperature_max,
                temperature_min=d.temperature_min,
                precipitation_sum=d.precipitation_sum,
                precipitation_probability_max=d.precipitation_probability_max,
                weather_code=d.weather_code,
            )
            for d in forecast.daily
        ]
        hourly = [
            HourlyForecastItem(
                time=h.time,
                temperature=h.temperature,
                precipitation=h.precipitation,
                precipitation_probability=h.precipitation_probability,
                weather_code=h.weather_code,
            )
            for h in forecast.hourly
        ]
        return ForecastResponse(
            latitude=forecast.latitude,
            longitude=forecast.longitude,
            timezone=forecast.timezone,
            current=current,
            daily=daily,
            hourly=hourly,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream weather service error: {exc}",
        ) from exc


@app.get(
    "/api/v1/coastal",
    response_model=MarineMetricsResponse,
    tags=["Weather"],
    summary="Coastal / marine conditions (alias)",
)
async def get_coastal(
    lat: Annotated[float, Field(ge=-90, le=90)] = Query(..., description="Latitude"),
    lon: Annotated[float, Field(ge=-180, le=180)] = Query(..., description="Longitude"),
    svc: WeatherService = Depends(get_weather_service),
) -> MarineMetricsResponse:
    """Alias for marine metrics – convenient for coastal dashboards."""
    return await get_marine_metrics(lat=lat, lon=lon, svc=svc)


@app.get(
    "/api/v1/alerts/active",
    response_model=AlertsResponse,
    tags=["Alerts"],
    summary="Active NDMA-style colour-coded alerts",
)
async def get_active_alerts(
    lat: Annotated[float, Field(ge=-90, le=90)] = Query(..., description="Latitude"),
    lon: Annotated[float, Field(ge=-180, le=180)] = Query(..., description="Longitude"),
    svc: WeatherService = Depends(get_weather_service),
) -> AlertsResponse:
    """
    Return structured colour-coded alerts (Green / Yellow / Orange / Red)
    derived from current wind speed and precipitation thresholds.
    """
    try:
        current = await svc.get_current_weather(float(lat), float(lon))
        return _evaluate_alerts(
            lat=float(lat),
            lon=float(lon),
            wind_speed=current.get("wind_speed"),
            precipitation=current.get("precipitation"),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unable to evaluate alerts: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Legacy path aliases (optional compatibility)
# ---------------------------------------------------------------------------

@app.get("/api/weather/current", include_in_schema=False)
async def legacy_current(
    lat: float = Query(...),
    lon: float = Query(...),
    svc: WeatherService = Depends(get_weather_service),
):
    return await get_current_weather(lat=lat, lon=lon, svc=svc)


@app.get("/api/weather/forecast", include_in_schema=False)
async def legacy_forecast(
    lat: float = Query(...),
    lon: float = Query(...),
    svc: WeatherService = Depends(get_weather_service),
):
    return await get_forecast(lat=lat, lon=lon, svc=svc)


@app.get("/api/coastal", include_in_schema=False)
async def legacy_coastal(
    lat: float = Query(...),
    lon: float = Query(...),
    svc: WeatherService = Depends(get_weather_service),
):
    return await get_marine_metrics(lat=lat, lon=lon, svc=svc)


@app.get("/api/alerts/active", include_in_schema=False)
async def legacy_alerts(
    lat: float = Query(...),
    lon: float = Query(...),
    svc: WeatherService = Depends(get_weather_service),
):
    return await get_active_alerts(lat=lat, lon=lon, svc=svc)


@app.get("/api/v1/weather/search")
async def search_location(
    q: str = Query(..., min_length=1),
    count: int = Query(5, ge=1, le=10),
    svc: WeatherService = Depends(get_weather_service),
):
    results = await svc.geocode(q, count=count)
    return {"query": q, "results": results}


@app.get("/api/v1/disaster/alerts")
async def disaster_alerts(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(300.0),
    days: int = Query(14, ge=1, le=30),
):
    """
    Get disaster/hazard alerts near a location.

    Sources:
    - USGS earthquakes
    - GDACS cyclones/floods/droughts/volcanoes
    - Open-Meteo thunderstorm risk (modeled)

    Returns GeoJSON-like features with severity colors.
    """
    from disaster_tools import get_disaster_alerts
    return await get_disaster_alerts(latitude=lat, longitude=lon, radius_km=radius_km, days=days)


# ---------------------------------------------------------------------------
# Drafted alert endpoints (human approval required before delivery)
# ---------------------------------------------------------------------------

@app.get(
    "/api/v1/alerts/drafted",
    response_model=List[AlertDraftResponse],
    tags=["Alerts"],
    summary="List drafted disaster warning alerts pending human review",
)
async def list_draft_alerts(
    delivery_status: Optional[str] = Query(None, description="draft | approved | rejected"),
    severity: Optional[str] = Query(None, description="green | yellow | orange | red"),
    language: Optional[str] = Query(None, description="Target language"),
    event_id: Optional[str] = Query(None, description="Filter by source event ID"),
    limit: int = Query(100, ge=1, le=500),
):
    """
    List drafted disaster warning alerts.

    Nothing is auto-sent. Every draft requires human approval before Layer 4
    delivery channels may dispatch it.
    """
    try:
        from db.mongo import get_mongo_manager

        mongo = get_mongo_manager()
        await mongo.initialize()
        alerts = await mongo.get_draft_alerts(
            delivery_status=delivery_status,
            severity=severity,
            language=language,
            event_id=event_id,
            limit=limit,
        )
        return [_serialize_alert_doc(a) for a in alerts]
    except Exception as exc:
        logger.warning("Failed to list drafted alerts: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Alert store unavailable: {exc}",
        ) from exc


@app.post(
    "/api/v1/alerts/{alert_id}/approve",
    response_model=AlertDraftResponse,
    tags=["Alerts"],
    summary="Approve a drafted alert for delivery",
)
async def approve_alert(
    alert_id: str,
    payload: AlertApprovalRequest,
):
    """
    Human approval step for a drafted alert.

    Marks the alert as approved and records who approved it and when.
    Layer 4 delivery channels should only dispatch alerts with
    delivery_status == 'approved'.
    """
    try:
        from db.mongo import get_mongo_manager

        mongo = get_mongo_manager()
        await mongo.initialize()
        alert = await mongo.approve_alert(alert_id, payload.approved_by)
        if alert is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert not found",
            )
        logger.info(
            "Alert %s approved by %s (event_id=%s)",
            alert_id,
            payload.approved_by,
            alert.get("event_id"),
        )
        return _serialize_alert_doc(alert)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to approve alert %s: %s", alert_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Alert store unavailable: {exc}",
        ) from exc


@app.post(
    "/api/v1/alerts/{alert_id}/reject",
    response_model=AlertDraftResponse,
    tags=["Alerts"],
    summary="Reject a drafted alert",
)
async def reject_alert(
    alert_id: str,
    payload: AlertRejectionRequest,
):
    """
    Human rejection step for a drafted alert.

    Marks the alert as rejected, records who rejected it, when, and why.
    Rejected alerts must never be delivered by Layer 4.
    """
    try:
        from db.mongo import get_mongo_manager

        mongo = get_mongo_manager()
        await mongo.initialize()
        alert = await mongo.reject_alert(alert_id, payload.rejected_by, payload.reason)
        if alert is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert not found",
            )
        logger.info(
            "Alert %s rejected by %s (event_id=%s, reason=%s)",
            alert_id,
            payload.rejected_by,
            alert.get("event_id"),
            payload.reason or "-",
        )
        return _serialize_alert_doc(alert)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to reject alert %s: %s", alert_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Alert store unavailable: {exc}",
        ) from exc


def _serialize_alert_doc(alert: dict) -> dict:
    """Convert a Mongo alert document to the API response shape."""
    def _iso(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    return {
        "id": str(alert.get("_id", "")),
        "event_id": alert.get("event_id", ""),
        "event_fingerprint": alert.get("event_fingerprint", ""),
        "language": alert.get("language", ""),
        "script_text": alert.get("script_text", ""),
        "severity": alert.get("severity", ""),
        "hazard_type": alert.get("hazard_type", ""),
        "title": alert.get("title", ""),
        "description": alert.get("description", ""),
        "latitude": alert.get("latitude"),
        "longitude": alert.get("longitude"),
        "source": alert.get("source", ""),
        "event_time": _iso(alert.get("event_time")),
        "change_type": alert.get("change_type", "new"),
        "delivery_status": alert.get("delivery_status", "draft"),
        "generated_at": _iso(alert.get("generated_at")),
        "approved_by": alert.get("approved_by"),
        "approved_at": _iso(alert.get("approved_at")),
        "rejected_by": alert.get("rejected_by"),
        "rejected_at": _iso(alert.get("rejected_at")),
        "rejection_reason": alert.get("rejection_reason"),
        "audit_log": alert.get("audit_log", []),
    }


# ---------------------------------------------------------------------------
# Startup / shutdown (optional lifecycle hooks)
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    # Ensure the shared service is created
    get_weather_service()


@app.on_event("shutdown")
async def shutdown() -> None:
    svc = get_weather_service()
    await svc.aclose()

 

@app.post("/api/v1/voice/advisory")
async def get_voice_advisory(
    lat: str = Form(...),
    lon: str = Form(...),
    lang: str = Form(...),
    persona: str = Form(...),
    audio: UploadFile = File(...)
    
):
    """
    Process a voice query end-to-end:
      1. Read audio bytes from the multipart upload
      2. Speech-to-text via VoiceService (Bhashini → Whisper fallback)
      3. Generate advisory via AI_engine (Gemini → deterministic fallback)
      4. Text-to-speech via VoiceService (Bhashini → gTTS fallback)
      5. Return JSON with native/English advisory text + base64 audio
    """
    from voice_service import get_voice_service
    from AI_engine import generate_weather_advisory

    audio_bytes = await audio.read()

    voice_svc = get_voice_service()
    lat_f = float(lat)
    lon_f = float(lon)

    # 1. STT
    try:
        transcript = await voice_svc.speech_to_text(audio_bytes, lang)
    except Exception as exc:
        logger.warning("STT failed for voice advisory: %s", exc)
        transcript = ""

    if not transcript.strip():
        transcript = "मौसम के बारे में बताएं" if lang != "en" else "Please tell me about the weather."

    # 2. AI advisory generation
    try:
        result = await generate_weather_advisory(
            user_text=transcript,
            source_lang=lang,
            lat=lat_f,
            lon=lon_f,
            target_lang=lang,
        )
    except Exception as exc:
        logger.error("AI advisory generation failed: %s", exc)
        result = {
            "english_advisory": "Unable to generate advisory at this time. Please check official IMD sources.",
            "native_advisory": "अभी में परामर्श उत्पन्न नहीं कर सकते। कृपया आधिकारिक IMD स्रोतों की जाँच करें।",
        }

    native_advisory = result.get("native_advisory") or result.get("english_advisory") or ""
    english_advisory = result.get("english_advisory") or ""

    # 3. TTS
    audio_b64 = ""
    try:
        tts_bytes = await voice_svc.text_to_speech(native_advisory, lang)
        if tts_bytes:
            audio_b64 = base64.b64encode(tts_bytes).decode("ascii")
    except Exception as exc:
        logger.warning("TTS failed: %s", exc)

    return JSONResponse(content={
        "transcript": transcript,
        "native_advisory": native_advisory,
        "english_advisory": english_advisory,
        "advisory": native_advisory,
        "audio_url": "",
        "audio_base64": audio_b64,
    })


@app.post("/api/v1/advisory/text")
async def get_text_advisory(
    lat: float = Form(...),
    lon: float = Form(...),
    lang: str = Form(...),
    persona: str = Form(...),
    query: str = Form(...),
):
    """
    Generate a weather advisory from a text query (no audio required).

    Uses the AI engine pipeline: detect/clean language → translate →
    fetch weather context → generate advisory → translate back.
    """
    from AI_engine import generate_weather_advisory
    from voice_service import get_voice_service

    voice_svc = get_voice_service()

    try:
        result = await generate_weather_advisory(
            user_text=query,
            source_lang=lang,
            lat=lat,
            lon=lon,
            target_lang=lang,
        )
    except Exception as exc:
        logger.error("AI advisory generation failed: %s", exc)
        result = {
            "english_advisory": "Unable to generate advisory at this time.",
            "native_advisory": "अभी में परामर्श उत्पन्न नहीं कर सकते।",
        }

    native_advisory = result.get("native_advisory") or result.get("english_advisory") or ""
    english_advisory = result.get("english_advisory") or ""

    audio_b64 = ""
    try:
        tts_bytes = await voice_svc.text_to_speech(native_advisory, lang)
        if tts_bytes:
            audio_b64 = base64.b64encode(tts_bytes).decode("ascii")
    except Exception as exc:
        logger.warning("TTS failed: %s", exc)

    return JSONResponse(content={
        "native_advisory": native_advisory,
        "english_advisory": english_advisory,
        "advisory": native_advisory,
        "audio_url": "",
        "audio_base64": audio_b64,
    })


# ---------------------------------------------------------------------------
# Unified WeatherGPT Expert (replaces fragmented agent code)
# ---------------------------------------------------------------------------

try:
    from weathergpt_expert import WeatherGPTExpert, get_expert

    _expert = get_expert()

    @app.get("/api/v1/expert/status", tags=["AI Expert"])
    async def expert_status():
        """Return expert agent health and capabilities."""
        return _expert.status()

    @app.post("/api/v1/expert/chat", tags=["AI Expert"])
    async def expert_chat(
        lat: float = Form(...),
        lon: float = Form(...),
        persona: str = Form("general"),
        lang: str = Form("en"),
        query: str = Form(...),
        history_json: Optional[str] = Form(None),
        location_name: Optional[str] = Form(None),
    ):
        """
        Text chat with the WeatherGPT expert.

        Supports:
        - Conversation history
        - Multi-language queries and replies
        - Persona-aware responses (farmer, fisherman, urban_commuter, general)
        - Live weather context
        """
        try:
            history = json.loads(history_json) if history_json else []
            result = await _expert.chat(
                message=query,
                history=history,
                persona=persona,
                language=lang,
                latitude=lat,
                longitude=lon,
                location_name=location_name,
            )
            return JSONResponse(content={
                "reply": result.get("reply", ""),
                "history": result.get("history", []),
                "language": result.get("language", lang),
                "weather_available": result.get("weather_available", False),
                "persona": result.get("persona", persona),
            })
        except Exception as exc:
            logger.error("Expert chat failed: %s", exc)
            return JSONResponse(
                status_code=500,
                content={"error": True, "detail": f"Expert unavailable: {exc}"},
            )

    @app.post("/api/v1/expert/chat/stream", tags=["AI Expert"])
    async def expert_chat_stream(
        lat: float = Form(...),
        lon: float = Form(...),
        persona: str = Form("general"),
        lang: str = Form("en"),
        query: str = Form(...),
        history_json: Optional[str] = Form(None),
        location_name: Optional[str] = Form(None),
    ):
        """
        Streaming text chat with the WeatherGPT expert.
        Returns Server-Sent Events with token chunks.
        """
        async def event_generator():
            try:
                history = json.loads(history_json) if history_json else []
                async for chunk in _expert.chat_stream(
                    message=query,
                    history=history,
                    persona=persona,
                    language=lang,
                    latitude=lat,
                    longitude=lon,
                    location_name=location_name,
                ):
                    yield f"data: {json.dumps(chunk)}\n\n"
            except Exception as exc:
                logger.error("Expert stream failed: %s", exc)
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            finally:
                yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/api/v1/expert/voice", tags=["AI Expert"])
    async def expert_voice(
        lat: float = Form(...),
        lon: float = Form(...),
        persona: str = Form("general"),
        lang: str = Form("en"),
        audio: UploadFile = File(...),
        history_json: Optional[str] = Form(None),
        location_name: Optional[str] = Form(None),
    ):
        """
        Voice chat with the WeatherGPT expert.

        Pipeline: audio upload → ASR → text chat → TTS → audio response

        Returns:
        - transcript: What the user said
        - reply: Expert's text response
        - reply_audio: Base64-encoded TTS audio
        """
        try:
            audio_bytes = await audio.read()
            history = json.loads(history_json) if history_json else []
            result = await _expert.voice_chat(
                audio_bytes=audio_bytes,
                audio_format=audio.content_type or "wav",
                history=history,
                persona=persona,
                language=lang,
                latitude=lat,
                longitude=lon,
                location_name=location_name,
            )
            return JSONResponse(content={
                "transcript": result.get("transcript", ""),
                "reply": result.get("reply", ""),
                "reply_audio": base64.b64encode(result.get("reply_audio", b"")).decode("ascii") if result.get("reply_audio") else "",
                "history": result.get("history", []),
                "language": result.get("language", lang),
                "persona": result.get("persona", persona),
                "weather_available": result.get("weather_available", False),
            })
        except Exception as exc:
            logger.error("Expert voice chat failed: %s", exc)
            return JSONResponse(
                status_code=500,
                content={"error": True, "detail": f"Voice chat failed: {exc}"},
            )

    @app.post("/api/v1/expert/analyze", tags=["AI Expert"])
    async def expert_analyze(
        lat: float = Form(...),
        lon: float = Form(...),
        persona: str = Form("general"),
        lang: str = Form("en"),
        file: UploadFile = File(...),
        prompt: Optional[str] = Form(None),
        history_json: Optional[str] = Form(None),
    ):
        """
        Analyze uploaded files (images, PDFs, CSVs) with the WeatherGPT expert.

        Supports:
        - Images: crop photos, weather radar, satellite imagery
        - PDFs: weather reports, advisories
        - CSVs: weather data logs

        Returns expert analysis with weather context.
        """
        try:
            file_bytes = await file.read()
            content_type = file.content_type or "application/octet-stream"
            history = json.loads(history_json) if history_json else []
            result = await _expert.analyze_file(
                file_bytes=file_bytes,
                content_type=content_type,
                filename=file.filename,
                prompt=prompt,
                persona=persona,
                language=lang,
                latitude=lat,
                longitude=lon,
                history=history,
            )
            return JSONResponse(content={
                "reply": result.get("reply", ""),
                "filename": file.filename,
                "content_type": content_type,
                "history": result.get("history", []),
                "language": result.get("language", lang),
                "weather_available": result.get("weather_available", False),
            })
        except Exception as exc:
            logger.error("Expert file analysis failed: %s", exc)
            return JSONResponse(
                status_code=500,
                content={"error": True, "detail": f"File analysis failed: {exc}"},
            )

except ImportError:
    logger.info("weathergpt_expert not available – expert endpoints disabled")