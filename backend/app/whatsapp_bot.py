"""
whatsapp_bot.py

WhatsApp Bot Controller for WeatherGPT.

Handles Twilio WhatsApp webhooks:
  - Text messages  → Body
  - Voice notes    → MediaUrl0 (audio)

Pipeline:
  1. Parse incoming Twilio form data
  2. STT (if audio) via all_india_voice / voice_service
  3. Run ai_engine.generate_weather_advisory
  4. Optionally synthesize TTS audio
  5. Reply with TwiML (text + optional media link)
"""

from __future__ import annotations


import logging
import os
from typing import Optional
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from backend.app.ai_engine import generate_weather_advisory
from backend.app.language_manager import normalize_lang_code, get_bhashini_code

try:
    from all_India_voice import speech_to_text, text_to_speech
except ImportError:
    speech_to_text = None
    text_to_speech = None
from backend.app.voice_service import get_voice_service

logger = logging.getLogger("whatsapp_bot")

router = APIRouter(prefix="/api/v1/whatsapp", tags=["WhatsApp"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
# Public base URL where this service is reachable (for media replies)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://your-weathergpt-domain.com").rstrip("/")

# Default location used when the user has not shared GPS / pincode
DEFAULT_LAT = float(os.getenv("DEFAULT_LAT", "28.61"))   # New Delhi
DEFAULT_LON = float(os.getenv("DEFAULT_LON", "77.21"))

# Default language when Twilio does not supply a language hint
DEFAULT_LANG = os.getenv("DEFAULT_WHATSAPP_LANG", "hi")

# Directory (or object-storage prefix) where generated TTS files are stored
MEDIA_DIR = os.getenv("MEDIA_DIR", "/tmp/weathergpt_media")
os.makedirs(MEDIA_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_twilio_request(request: Request, form_data: dict) -> None:
    """
    Optional but recommended: validate that the webhook really came from Twilio.
    Skipped when TWILIO_AUTH_TOKEN is not configured (local dev).
    """
    if not TWILIO_AUTH_TOKEN:
        return
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    url = str(request.url)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(url, form_data, signature):
        logger.warning("Twilio signature validation failed")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")


async def _download_media(url: str) -> bytes:
    """
    Download an audio attachment from Twilio.
    Twilio media URLs require Basic Auth with Account SID + Auth Token.
    """
    auth = None
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    async with httpx.AsyncClient(timeout=30.0, auth=auth) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def _guess_lang_from_twilio(from_number: str, body: str) -> str:
    """
    Very lightweight language heuristic.
    In production you would use a proper LID model or user profile.
    """
    # Twilio sometimes sends ProfileName / WaId – here we just fall back
    return DEFAULT_LANG


async def _process_text_query(
    text: str,
    lang: str,
    lat: float,
    lon: float,
) -> dict:
    """Run the full AI advisory pipeline on a text utterance."""
    return await generate_weather_advisory(
        user_text=text,
        source_lang=lang,
        lat=lat,
        lon=lon,
        target_lang=lang,
    )


async def _process_audio_query(
    audio_bytes: bytes,
    lang: str,
    lat: float,
    lon: float,
) -> dict:
    """
    STT → AI advisory.
    Prefers Bhashini via all_india_voice; falls back through voice_service.
    """
    try:
        transcript = await speech_to_text(audio_bytes, lang)
    except Exception:
        # Fallback stack
        voice = get_voice_service()
        transcript = await voice.speech_to_text(audio_bytes, lang)

    if not transcript.strip():
        transcript = "मौसम के बारे में बताओ"   # safe default

    return await _process_text_query(transcript, lang, lat, lon)


async def _synthesize_reply_audio(text: str, lang: str) -> Optional[str]:
    """
    Generate TTS audio and return a publicly reachable URL.
    Returns None when synthesis fails (caller will fall back to plain text).
    """
    try:
        audio_bytes = await text_to_speech(text, lang)
    except Exception:
        try:
            voice = get_voice_service()
            audio_bytes = await voice.text_to_speech(text, lang)
        except Exception as exc:
            logger.warning("TTS failed: %s", exc)
            return None

    if not audio_bytes:
        return None

    # Persist to a temporary file (in production push to S3 / GCS and return CDN URL)
    import uuid
    filename = f"tts_{uuid.uuid4().hex}.mp3"
    path = os.path.join(MEDIA_DIR, filename)
    with open(path, "wb") as f:
        f.write(audio_bytes)

    # Assume a static file route is mounted at /media
    return urljoin(PUBLIC_BASE_URL + "/", f"media/{filename}")


def _build_twiml_reply(
    advisory_text: str,
    audio_url: Optional[str] = None,
) -> str:
    """
    Build a TwiML MessagingResponse.
    WhatsApp supports both text and media (audio) in the same message.
    """
    resp = MessagingResponse()
    msg = resp.message()

    # Prefer a short text summary; full advisory can be long
    msg.body(advisory_text[:1500])   # WhatsApp practical limit

    if audio_url:
        msg.media(audio_url)

    return str(resp)


# ---------------------------------------------------------------------------
# Main webhook
# ---------------------------------------------------------------------------

@router.post(
    "/incoming",
    summary="Twilio WhatsApp incoming webhook",
    response_class=Response,
)
async def whatsapp_incoming(
    request: Request,
    Body: Optional[str] = Form(None),
    MediaUrl0: Optional[str] = Form(None),
    MediaContentType0: Optional[str] = Form(None),
    From: Optional[str] = Form(None),
    To: Optional[str] = Form(None),
    ProfileName: Optional[str] = Form(None),
    WaId: Optional[str] = Form(None),
    Latitude: Optional[float] = Form(None),
    Longitude: Optional[float] = Form(None),
):
    """
    Twilio posts application/x-www-form-urlencoded data.

    Supported payloads:
      - Text message          → Body
      - Voice note             → MediaUrl0 (audio/*)
      - Location share         → Latitude / Longitude
    """
    # Reconstruct form dict for signature validation
    form = await request.form()
    form_dict = {k: v for k, v in form.items()}
    _validate_twilio_request(request, form_dict)

    lang = _guess_lang_from_twilio(From or "", Body or "")
    lat = Latitude if Latitude is not None else DEFAULT_LAT
    lon = Longitude if Longitude is not None else DEFAULT_LON

    try:
        # ------------------------------------------------------------------
        # 1. Voice note
        # ------------------------------------------------------------------
        if MediaUrl0 and MediaContentType0 and MediaContentType0.startswith("audio"):
            logger.info("Incoming WhatsApp voice note from %s", From)
            audio_bytes = await _download_media(MediaUrl0)
            result = await _process_audio_query(audio_bytes, lang, lat, lon)

        # ------------------------------------------------------------------
        # 2. Text message
        # ------------------------------------------------------------------
        elif Body and Body.strip():
            logger.info("Incoming WhatsApp text from %s: %s", From, Body[:80])
            result = await _process_text_query(Body.strip(), lang, lat, lon)

        # ------------------------------------------------------------------
        # 3. Empty / unsupported
        # ------------------------------------------------------------------
        else:
            twiml = _build_twiml_reply(
                "कृपया अपना सवाल टेक्स्ट में लिखें या वॉइस नोट भेजें।\n"
                "Please type your question or send a voice note."
            )
            return Response(content=twiml, media_type="application/xml")

        # ------------------------------------------------------------------
        # Build reply
        # ------------------------------------------------------------------
        advisory = result.get("native_advisory") or result.get("english_advisory") or ""
        # Keep the reply reasonably short for WhatsApp
        if len(advisory) > 1200:
            advisory = advisory[:1197] + "…"

        audio_url = await _synthesize_reply_audio(advisory, lang)

        twiml = _build_twiml_reply(advisory, audio_url)
        return Response(content=twiml, media_type="application/xml")

    except Exception as exc:
        logger.exception("WhatsApp webhook failed")
        error_msg = (
            "क्षमा करें, अभी सेवा उपलब्ध नहीं है। कृपया थोड़ी देर बाद प्रयास करें।\n"
            "Sorry, the service is temporarily unavailable. Please try again later."
        )
        twiml = _build_twiml_reply(error_msg)
        return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------------
# Optional: static media serving helper (mount in main FastAPI app)
# ---------------------------------------------------------------------------

def mount_media_route(app) -> None:
    """
    Call from main.py:

        from backend.app.whatsapp_bot import mount_media_route
        mount_media_route(app)
    """
    from fastapi.staticfiles import StaticFiles
    app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


# ---------------------------------------------------------------------------
# Self-test (prints a sample TwiML reply)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(_build_twiml_reply(
        "आज दिल्ली में आंशिक बादल छाए रह सकते हैं। तापमान 28 से 34 डिग्री के बीच रहेगा।",
        audio_url="https://example.com/media/demo.mp3",
    ))
