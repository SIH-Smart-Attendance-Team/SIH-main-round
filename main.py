"""
main.py – Production-ready FastAPI application for WeatherGPT.

Exposes REST endpoints backed by weather_service.py (Open-Meteo).
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, confloat

from weather_service import WeatherService, get_weather_service
from auth_db import init_db, create_user, get_user_by_email, get_user_by_id

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
    precipitation: Optional[float] = Field(None, description="mm")
    wind_speed: Optional[float] = Field(None, description="km/h")
    wind_direction: Optional[float] = Field(None, description="degrees")
    weather_code: Optional[int] = None
    pressure: Optional[float] = Field(None, description="hPa")
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
                precipitation=forecast.current.precipitation,
                wind_speed=forecast.current.wind_speed,
                wind_direction=forecast.current.wind_direction,
                weather_code=forecast.current.weather_code,
                pressure=forecast.current.pressure_msl,
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