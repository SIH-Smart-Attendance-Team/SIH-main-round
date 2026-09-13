"""
whatsapp_webhook.py

Meta WhatsApp Business (Cloud API) webhook — single source of truth for WhatsApp.

  GET  /whatsapp/webhook  - verification handshake Meta requires on setup
  POST /whatsapp/webhook  - inbound message events (text + voice notes)

Uses the SAME CoreAgent + EscalationEngine as voice_webhook.py. The only
channel-specific behavior is:
  - session_id = the sender's WhatsApp number (wa_id)
  - "warm transfer" doesn't exist for text -> instead we mark the thread
    pending_human, notify the on-call agent (e.g. via internal Slack/CRM
    webhook), and suppress bot auto-replies on that thread until a human
    resolves it.

Requires: pip install fastapi uvicorn httpx redis
Env vars: WHATSAPP_VERIFY_TOKEN, WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID,
          AGENT_NOTIFY_WEBHOOK_URL
"""

import logging
import os

import httpx
from fastapi import FastAPI, Query, Request, Response

from core_agent import CoreAgent
from voice_service import get_voice_service

logger = logging.getLogger("weathergpt.whatsapp_webhook")

app = FastAPI()
agent = CoreAgent()

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
AGENT_NOTIFY_WEBHOOK_URL = os.environ.get("AGENT_NOTIFY_WEBHOOK_URL")

GRAPH_API_BASE = "https://graph.facebook.com/v20.0"


@app.get("/whatsapp/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta's one-time subscription verification handshake."""
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)


@app.post("/whatsapp/webhook")
async def receive_message(request: Request):
    payload = await request.json()

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        if "messages" not in change:
            # Could be a status update (delivered/read) — ack and ignore.
            return Response(status_code=200)

        message = change["messages"][0]
        wa_id = message["from"]  # sender's WhatsApp number, our session_id
        msg_type = message.get("type")

        # Handle voice notes (audio)
        if msg_type == "audio":
            user_text = await _process_audio_message(message, wa_id)
            if not user_text:
                await send_whatsapp_message(wa_id, "I couldn't understand the voice note. Please try again or type your question.")
                return Response(status_code=200)
        elif msg_type == "text":
            user_text = message["text"]["body"]
        else:
            await send_whatsapp_message(wa_id, "I can currently only understand text and voice messages.")
            return Response(status_code=200)

    except (KeyError, IndexError):
        return Response(status_code=200)  # malformed/irrelevant event, ack anyway

    if await _is_pending_human(wa_id):
        # A human has already taken this thread over — don't let the bot
        # jump back in and talk over them.
        return Response(status_code=200)

    reply = await agent.handle_turn(
        session_id=wa_id,
        channel="whatsapp",
        user_text=user_text,
        language=_guess_language(user_text),  # replace with real language ID
        location=None,
    )

    await send_whatsapp_message(wa_id, reply.text)

    if reply.escalation.escalate:
        await _mark_pending_human(wa_id)
        await _notify_human_agent(wa_id, reply.escalation)

    return Response(status_code=200)


# ---------------------------------------------------------------------------
# WhatsApp send helper (public — used by alert_dispatcher.py)
# ---------------------------------------------------------------------------

async def send_whatsapp_message(to: str, body: str) -> bool:
    """
    Send a WhatsApp text message via Meta Cloud API (Graph API).

    Args:
        to: Recipient WhatsApp number in international format (wa_id)
        body: Message text (max 4096 chars for WhatsApp)

    Returns:
        True on success, False on failure (logs error, never raises)
    """
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("Meta WhatsApp credentials not configured — cannot send message")
        return False

    url = f"{GRAPH_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body[:4096]},
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("WhatsApp send failed to %s: %s", to, exc)
        return False


# ---------------------------------------------------------------------------
# Voice note processing (merged from former Whatsapp_bot.py)
# ---------------------------------------------------------------------------

async def _process_audio_message(message: dict, wa_id: str) -> str:
    """Download and transcribe a WhatsApp voice note. Returns transcript or empty string."""
    audio_id = message.get("audio", {}).get("id")
    mime_type = message.get("audio", {}).get("mime_type", "")
    if not audio_id or not mime_type.startswith("audio"):
        return ""

    # Step 1: Get media URL from Meta Graph API
    media_url = await _get_media_url(audio_id)
    if not media_url:
        return ""

    # Step 2: Download audio bytes
    audio_bytes = await _download_media(media_url)
    if not audio_bytes:
        return ""

    # Step 3: Speech-to-text via voice_service (Bhashini -> Whisper fallback)
    voice_svc = get_voice_service()
    lang = _guess_language("")  # Default, could be improved with user profile
    try:
        transcript = await voice_svc.speech_to_text(audio_bytes, lang)
        return transcript.strip()
    except Exception as exc:
        logger.warning("STT failed for voice note from %s: %s", wa_id, exc)
        return ""


async def _get_media_url(media_id: str) -> str:
    """Query Meta Graph API for the media URL given a media ID."""
    url = f"{GRAPH_API_BASE}/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return data.get("url", "")
    except Exception as exc:
        logger.warning("Failed to get media URL for %s: %s", media_id, exc)
        return ""


async def _download_media(url: str) -> bytes:
    """Download media from Meta's CDN (requires Bearer token)."""
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.content
    except Exception as exc:
        logger.warning("Media download failed from %s: %s", url, exc)
        return b""


# ---------------------------------------------------------------------------
# Human handoff state + notification
# ---------------------------------------------------------------------------

async def _mark_pending_human(wa_id: str) -> None:
    # Reuse the same Redis instance CoreAgent's SessionStore uses; a simple
    # dedicated flag keeps this concern separate from ConversationState.
    agent.sessions._r.set(f"weathergpt:pending_human:{wa_id}", "1", ex=60 * 60 * 6)


async def _is_pending_human(wa_id: str) -> bool:
    return agent.sessions._r.exists(f"weathergpt:pending_human:{wa_id}") == 1


async def _notify_human_agent(wa_id: str, escalation) -> None:
    """Push the escalation into your agent dashboard / CRM / Slack channel
    so a human picks it up and replies via the same WhatsApp number."""
    if not AGENT_NOTIFY_WEBHOOK_URL:
        return
    async with httpx.AsyncClient() as client:
        await client.post(
            AGENT_NOTIFY_WEBHOOK_URL,
            json={
                "channel": "whatsapp",
                "contact": wa_id,
                "queue": escalation.queue.value,
                "priority": escalation.priority.value,
                "reason": escalation.reason,
                "summary": escalation.handoff_summary,
            },
            timeout=10,
        )


def _guess_language(text: str) -> str:
    """Placeholder — replace with a real language-ID model/library
    (e.g. fastText lid.176, or a call to your NLU service)."""
    return "en"
