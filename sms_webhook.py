"""
sms_webhook.py — Twilio Programmable SMS webhook for feature-phone users (Layer 4).

  POST /sms/incoming  - receives inbound SMS, routes through CoreAgent.handle_turn()
  POST /sms/send      - internal helper to send outbound SMS (used by alert_dispatcher.py)

Uses the SAME CoreAgent + EscalationEngine as voice_webhook.py and
whatsapp_webhook.py — the only channel-specific code is TwiML generation
and phone-number parsing. This guarantees escalation criteria can't drift
across channels (see README.md section 2: "why one core agent, three adapters").

Requires: pip install fastapi uvicorn twilio redis
Env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_SMS_NUMBER (the
          Twilio phone number used as the sender / webhook endpoint)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request, Response, status
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from core_agent import CoreAgent

logger = logging.getLogger("sms_webhook")

app = FastAPI()
agent = CoreAgent()

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_SMS_NUMBER = os.getenv("TWILIO_SMS_NUMBER", os.getenv("TWILIO_NUMBER", ""))

_twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        from twilio.rest import Client as TwilioClient

        _twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        logger.info("Twilio SMS client initialized for number %s", TWILIO_SMS_NUMBER)
    except Exception:
        logger.warning("Failed to initialise Twilio SMS client")


def _validate_twilio_request(request: Request, form_data: dict) -> None:
    """
    Validate that this webhook really came from Twilio.
    Uses the same RequestValidator pattern as whatsapp_webhook.py.
    Skipped when TWILIO_AUTH_TOKEN is not configured (local dev).
    """
    if not TWILIO_AUTH_TOKEN:
        return
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    url = str(request.url)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(form_data, url, signature):
        logger.warning("Twilio SMS signature validation failed")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")


async def send_sms(to: str, body: str) -> bool:
    """
    Send an outbound SMS via Twilio Programmable SMS.

    Called by alert_dispatcher.py when broadcasting approved alerts to
    feature-phone users whose preferred channel is SMS.

    Returns True on success, False on failure.
    """
    if not _twilio_client:
        logger.warning("Twilio client not configured — cannot send SMS")
        return False
    try:
        message = _twilio_client.messages.create(
            body=body[:1600],  # SMS practical length limit
            from_=TWILIO_SMS_NUMBER,
            to=to,
        )
        logger.info("SMS sent to %s (sid=%s)", to, message.sid)
        return True
    except Exception as exc:
        logger.warning("SMS send failed to %s: %s", to, exc)
        return False


def _normalize_phone(raw: str) -> str:
    """
    Ensure the phone number is in E.164 format for Twilio.
    Accepts +91XXXXXXXXXX, 91XXXXXXXXXX, or XXXXXXXXXX.
    """
    import re

    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) == 12:
        return "+" + digits
    if len(digits) == 10:
        return "+91" + digits
    return raw if raw.startswith("+") else "+" + digits


# ---------------------------------------------------------------------------
# Inbound webhook
# ---------------------------------------------------------------------------

@app.post("/sms/incoming", response_class=Response)
async def sms_incoming(
    request: Request,
    From: Optional[str] = Form(None),
    Body: Optional[str] = Form(None),
    SmsStatus: Optional[str] = Form(None),
) -> Response:
    """
    Twilio posts application/x-www-form-urlencoded data when an SMS arrives.
    The message body is routed through CoreAgent.handle_turn() — identical
    NLU/escalation path used by WhatsApp and voice channels.
    """
    form = await request.form()
    form_dict = {k: v for k, v in form.items()}
    _validate_twilio_request(request, form_dict)

    caller = From or ""
    text = (Body or "").strip()

    if not text:
        return _twiml_reply("कृपया अपना सवाल टेक्स्ट में भेजें।\nPlease send your question as a text message.")

    # Normalise the caller number — use the E.164 form as the unique session ID
    session_id = _normalize_phone(caller)
    logger.info("Incoming SMS from %s: %s", caller, text[:80])

    try:
        reply = await agent.handle_turn(
            session_id=session_id,
            channel="sms",
            user_text=text,
            language="hi",  # default; CoreAgent detects/translates as needed
            location=None,
        )

        # If escalation triggered, the warm-transfer is a human callback
        # (SMS can't bridge a live call), so we notify the agent queue.
        if reply.escalation.escalate:
            # Mark the thread so the human agent sees it was escalated
            agent.sessions._set_session_meta(session_id, "escalated", True)
            logger.info("SMS escalation for %s: queue=%s, reason=%s",
                        caller, reply.escalation.queue.value, reply.escalation.reason)

        return _twiml_reply(reply.text)

    except Exception as exc:
        logger.exception("SMS webhook handling failed for %s", caller)
        error_msg = (
            "क्षमा करें, अभी एऋो सेवा उपलब्ध नहीं है। कृपया थोड़ी देर बाद प्रयास करें।\n"
            "Sorry, the service is temporarily unavailable. Please try again later."
        )
        return _twiml_reply(error_msg)


def _twiml_reply(text: str) -> Response:
    """Build a TwiML MessagingResponse for SMS."""
    resp = MessagingResponse()
    resp.message(text)
    return Response(content=str(resp), media_type="application/xml")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(_twiml_reply(
        "आज दिल्ली में आंशिक बादल छाए सकते हैं। तापमान 28 से 34 डिग्री के बीच रहेगा।"
    ))
