"""
webhooks.py

Broadcast Webhook Engine for WeatherGPT.

Exposes:
  POST /api/v1/webhooks/weather-alert

Accepts a structured weather-alert payload, filters active user sessions
whose last-known location falls inside the affected region, and dispatches
notifications via the configured channels (WhatsApp / SMS / push / log).
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from enum import Enum

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("webhooks")

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Simple shared secret so only trusted upstream systems (IMD, internal cron …)
# can trigger broadcasts.  Set WEBHOOK_SECRET in the environment.
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Maximum concurrent outbound messages per broadcast
MAX_DISPATCH_CONCURRENCY = int(os.getenv("MAX_DISPATCH_CONCURRENCY", "20"))


# ---------------------------------------------------------------------------
# Alert payload schema
# ---------------------------------------------------------------------------

class AlertSeverity(str, Enum):
    GREEN = "Green"
    YELLOW = "Yellow"
    ORANGE = "Orange"
    RED = "Red"


class GeoPoint(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class AffectedRegion(BaseModel):
    """
    Either a centre + radius (km) or an explicit bounding box.
    At least one representation must be provided.
    """
    centre: GeoPoint | None = None
    radius_km: float | None = Field(None, gt=0, le=2000)
    # Bounding box: [min_lon, min_lat, max_lon, max_lat]
    bbox: list[float] | None = None

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: list[float] | None) -> list[float] | None:
        if v is not None and len(v) != 4:
            raise ValueError("bbox must contain exactly 4 numbers: [min_lon, min_lat, max_lon, max_lat]")
        return v


class WeatherAlertPayload(BaseModel):
    """Incoming JSON body for POST /api/v1/webhooks/weather-alert."""
    secret: str | None = Field(None, description="Shared webhook secret")
    severity: AlertSeverity
    title: str = Field(..., min_length=3, max_length=200)
    message: str = Field(..., min_length=5, max_length=2000)
    region: AffectedRegion
    # Optional extra metadata
    source: str = Field("internal", description="Originating system (IMD, NDMA, …)")
    valid_from: str | None = None
    valid_until: str | None = None
    language_hints: list[str] = Field(default_factory=lambda: ["hi", "en"])


class DispatchResult(BaseModel):
    user_id: str
    channel: str
    success: bool
    detail: str | None = None


class BroadcastResponse(BaseModel):
    alert_id: str
    severity: AlertSeverity
    matched_users: int
    dispatched: int
    failed: int
    results: list[DispatchResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# In-memory session / user store (replace with Redis / Postgres in production)
# ---------------------------------------------------------------------------

class UserSession(BaseModel):
    user_id: str
    channel: str          # "whatsapp" | "sms" | "push" | "voice"
    address: str          # phone number, FCM token, etc.
    lat: float
    lon: float
    language: str = "hi"
    last_seen: float = Field(default_factory=time.time)
    active: bool = True


# Process-wide registry – in production this would be a database
_SESSIONS: dict[str, UserSession] = {}


def register_session(session: UserSession) -> None:
    """Helper for other modules (WhatsApp / telephony) to register a user."""
    _SESSIONS[session.user_id] = session


def get_active_sessions() -> list[UserSession]:
    return [s for s in _SESSIONS.values() if s.active]


# ---------------------------------------------------------------------------
# Geospatial helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _point_in_region(lat: float, lon: float, region: AffectedRegion) -> bool:
    """Return True if (lat, lon) lies inside the described region."""
    if region.bbox is not None:
        min_lon, min_lat, max_lon, max_lat = region.bbox
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
            return True

    if region.centre is not None and region.radius_km is not None:
        dist = _haversine_km(lat, lon, region.centre.lat, region.centre.lon)
        if dist <= region.radius_km:
            return True

    return False


def filter_sessions_by_region(region: AffectedRegion) -> list[UserSession]:
    return [
        s for s in get_active_sessions()
        if _point_in_region(s.lat, s.lon, region)
    ]


# ---------------------------------------------------------------------------
# Notification dispatchers (pluggable)
# ---------------------------------------------------------------------------

async def _dispatch_whatsapp(session: UserSession, alert: WeatherAlertPayload) -> DispatchResult:
    """
    Send a WhatsApp message via Meta Cloud API.
    This is a lightweight placeholder – wire it to whatsapp_webhook.send_whatsapp_message in production.
    """
    try:
        # Example: call the Meta Cloud API helper
        # from whatsapp_webhook import send_whatsapp_message
        # await send_whatsapp_message(session.address, f"{alert.title}\n\n{alert.message}")
        logger.info(
            "WhatsApp → %s | %s | %s",
            session.address, alert.severity, alert.title,
        )
        return DispatchResult(
            user_id=session.user_id,
            channel="whatsapp",
            success=True,
        )
    except Exception as exc:
        logger.exception("WhatsApp dispatch failed for %s", session.user_id)
        return DispatchResult(
            user_id=session.user_id,
            channel="whatsapp",
            success=False,
            detail=str(exc),
        )


async def _dispatch_sms(session: UserSession, alert: WeatherAlertPayload) -> DispatchResult:
    try:
        logger.info("SMS → %s | %s", session.address, alert.title)
        return DispatchResult(user_id=session.user_id, channel="sms", success=True)
    except Exception as exc:
        return DispatchResult(
            user_id=session.user_id, channel="sms", success=False, detail=str(exc)
        )


async def _dispatch_push(session: UserSession, alert: WeatherAlertPayload) -> DispatchResult:
    try:
        logger.info("Push → %s | %s", session.address, alert.title)
        return DispatchResult(user_id=session.user_id, channel="push", success=True)
    except Exception as exc:
        return DispatchResult(
            user_id=session.user_id, channel="push", success=False, detail=str(exc)
        )


async def _dispatch_one(session: UserSession, alert: WeatherAlertPayload) -> DispatchResult:
    if session.channel == "whatsapp":
        return await _dispatch_whatsapp(session, alert)
    if session.channel == "sms":
        return await _dispatch_sms(session, alert)
    if session.channel == "push":
        return await _dispatch_push(session, alert)
    # Unknown channel – just log
    logger.warning("No dispatcher for channel=%s user=%s", session.channel, session.user_id)
    return DispatchResult(
        user_id=session.user_id,
        channel=session.channel,
        success=False,
        detail="unsupported channel",
    )


async def broadcast_alert(alert: WeatherAlertPayload) -> BroadcastResponse:
    """
    Core broadcast logic:
      1. Filter sessions by geographic region
      2. Fan-out notifications with bounded concurrency
    """
    import uuid
    alert_id = str(uuid.uuid4())

    matched = filter_sessions_by_region(alert.region)
    logger.info(
        "Alert %s (%s) matched %d users",
        alert_id, alert.severity, len(matched),
    )

    if not matched:
        return BroadcastResponse(
            alert_id=alert_id,
            severity=alert.severity,
            matched_users=0,
            dispatched=0,
            failed=0,
        )

    semaphore = asyncio.Semaphore(MAX_DISPATCH_CONCURRENCY)

    async def _guarded(session: UserSession) -> DispatchResult:
        async with semaphore:
            return await _dispatch_one(session, alert)

    results = await asyncio.gather(*[_guarded(s) for s in matched])
    success_count = sum(1 for r in results if r.success)
    fail_count = len(results) - success_count

    return BroadcastResponse(
        alert_id=alert_id,
        severity=alert.severity,
        matched_users=len(matched),
        dispatched=success_count,
        failed=fail_count,
        results=list(results),
    )


# ---------------------------------------------------------------------------
# FastAPI route
# ---------------------------------------------------------------------------

@router.post(
    "/weather-alert",
    response_model=BroadcastResponse,
    summary="Ingest a weather alert and broadcast to affected users",
)
async def weather_alert_webhook(
    payload: WeatherAlertPayload,
    background_tasks: BackgroundTasks,
):
    """
    Accept a JSON weather-alert payload, filter active user sessions whose
    last-known coordinates fall inside the affected region, and dispatch
    notifications on the users' preferred channels.
    """
    # Optional shared-secret check
    if WEBHOOK_SECRET and payload.secret != WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )

    # Run the (potentially slow) fan-out in the background so the caller
    # receives a quick acknowledgement.  For strict synchronous behaviour
    # simply `return await broadcast_alert(payload)`.
    result = await broadcast_alert(payload)
    return result


# ---------------------------------------------------------------------------
# Convenience: seed a few demo sessions (useful for local testing)
# ---------------------------------------------------------------------------

def seed_demo_sessions() -> None:
    demos = [
        UserSession(
            user_id="u1", channel="whatsapp", address="+919876543210",
            lat=28.61, lon=77.21, language="hi",
        ),
        UserSession(
            user_id="u2", channel="whatsapp", address="+919811122233",
            lat=19.07, lon=72.87, language="mr",
        ),
        UserSession(
            user_id="u3", channel="sms", address="+919700011122",
            lat=13.08, lon=80.27, language="ta",
        ),
        UserSession(
            user_id="u4", channel="push", address="fcm-token-xyz",
            lat=22.57, lon=88.36, language="bn",
        ),
    ]
    for s in demos:
        register_session(s)
    logger.info("Seeded %d demo sessions", len(demos))


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_demo_sessions()

    async def demo() -> None:
        # Alert covering the Delhi region
        payload = WeatherAlertPayload(
            severity=AlertSeverity.ORANGE,
            title="Heavy Rainfall Warning – Delhi NCR",
            message=(
                "Indian Meteorological Department has issued an Orange alert "
                "for heavy rainfall in Delhi NCR over the next 24 hours. "
                "Residents are advised to avoid low-lying areas."
            ),
            region=AffectedRegion(
                centre=GeoPoint(lat=28.61, lon=77.21),
                radius_km=50,
            ),
            source="IMD",
        )
        result = await broadcast_alert(payload)
        print(result.model_dump_json(indent=2))

    asyncio.run(demo())