"""
voice_webhook.py

Twilio Programmable Voice webhooks:
  POST /voice/incoming  - first webhook Twilio hits on an inbound call
  POST /voice/gather    - handles the speech result of each turn
  POST /voice/whisper   - TwiML played to the human agent before bridging (warm transfer)

Flow:
  1. Caller dials the WeatherGPT number.
  2. TwiML <Gather input="speech"> captures their query (language auto-
     detected or pre-selected via IVR menu — omitted here for brevity).
  3. We call CoreAgent.handle_turn(). If it decides to escalate, we place
     the caller into a hold conference and dial a human agent, whispering
     the handoff summary to the agent before merging the two legs.
  4. If not escalating, we speak the reply and <Gather> again.

Requires: pip install fastapi uvicorn twilio redis
Env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_NUMBER,
          HUMAN_AGENT_ROUTING (see routing_table below)
"""

import os
from fastapi import FastAPI, Request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather, Dial
from twilio.rest import Client as TwilioClient

from core_agent import CoreAgent
from escalation_engine import Queue

app = FastAPI()
agent = CoreAgent()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://helpline.weathergpt.example.com")

_twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        _twilio_client = twilio_client
    except Exception:
        pass

# Static routing table for MVP; replace with Twilio TaskRouter or a real
# on-call/skills-based queue for production (availability, shift, language).
HUMAN_AGENT_ROUTING = {
    Queue.DISASTER_RESPONSE: "+91XXXXXXXXXX",
    Queue.AGRI_EXPERT: "+91XXXXXXXXXX",
    Queue.GENERAL_SUPPORT: "+91XXXXXXXXXX",
}

# language -> Twilio <Gather> speech recognition language code
LANGUAGE_CODES = {
    "en": "en-IN",
    "hi": "hi-IN",
    "bn": "bn-IN",
    "ta": "ta-IN",
}


def _twiml(response: VoiceResponse) -> Response:
    return Response(content=str(response), media_type="application/xml")


@app.post("/voice/incoming")
async def voice_incoming(request: Request):
    """First webhook on an inbound call. Greets and starts listening."""
    vr = VoiceResponse()
    gather = Gather(
        input="speech",
        action=f"{PUBLIC_BASE_URL}/voice/gather?lang=en",
        method="POST",
        language=LANGUAGE_CODES["en"],
        speech_timeout="auto",
    )
    gather.say(
        "Welcome to WeatherGPT helpline. Please tell me your question about "
        "weather, crops, or a nearby emergency, after the beep.",
        language="en-IN",
    )
    vr.append(gather)
    # If no speech detected, retry once before hanging up gracefully.
    vr.redirect(f"{PUBLIC_BASE_URL}/voice/incoming")
    return _twiml(vr)


@app.post("/voice/gather")
async def voice_gather(request: Request, lang: str = "en"):
    """Handles the caller's spoken query for this turn."""
    form = await request.form()
    call_sid = form.get("CallSid")
    speech_result = form.get("SpeechResult", "")
    caller_number = form.get("From")

    reply = await agent.handle_turn(
        session_id=call_sid,
        channel="voice",
        user_text=speech_result,
        language=lang,
        location=None,  # resolve via caller ID -> registered farm location lookup
    )

    vr = VoiceResponse()

    if reply.escalation.escalate:
        vr.say(reply.text, language=_say_lang(lang))
        vr.redirect(
            f"{PUBLIC_BASE_URL}/voice/transfer"
            f"?queue={reply.escalation.queue.value}"
            f"&reason={reply.escalation.reason}"
        )
        return _twiml(vr)

    gather = Gather(
        input="speech",
        action=f"{PUBLIC_BASE_URL}/voice/gather?lang={lang}",
        method="POST",
        language=LANGUAGE_CODES.get(lang, "en-IN"),
        speech_timeout="auto",
    )
    gather.say(reply.text, language=_say_lang(lang))
    vr.append(gather)
    vr.redirect(f"{PUBLIC_BASE_URL}/voice/incoming")
    return _twiml(vr)


@app.post("/voice/transfer")
async def voice_transfer(request: Request, queue: str, reason: str = ""):
    """
    Warm transfer: put the caller in a named conference, then place an
    outbound call to the human agent that whispers context before joining
    them to the same conference.
    """
    form = await request.form()
    call_sid = form.get("CallSid")
    conference_name = f"handoff-{call_sid}"

    human_number = HUMAN_AGENT_ROUTING.get(Queue(queue), HUMAN_AGENT_ROUTING[Queue.GENERAL_SUPPORT])

    # Put the caller on hold in a conference, with hold music, waiting for the agent.
    vr = VoiceResponse()
    dial = Dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=False,  # caller waits until agent joins
        end_conference_on_exit=True,
        wait_url=f"{PUBLIC_BASE_URL}/voice/hold-music",
    )
    vr.append(dial)

    # Kick off the outbound leg to the human agent in parallel.
    twilio_client.calls.create(
        to=human_number,
        from_=os.environ["TWILIO_NUMBER"],
        url=(
            f"{PUBLIC_BASE_URL}/voice/whisper"
            f"?conference={conference_name}&reason={reason}"
        ),
    )

    return _twiml(vr)


@app.post("/voice/whisper")
async def voice_whisper(request: Request, conference: str, reason: str = ""):
    """
    Played only to the human agent before they're bridged to the caller —
    this is the "warm" part of the transfer: the agent hears context first.
    """
    vr = VoiceResponse()
    vr.say(
        f"Incoming WeatherGPT escalation. Reason: {reason.replace('_', ' ')}. "
        f"Connecting you to the caller now.",
        language="en-IN",
    )
    dial = Dial()
    dial.conference(conference, start_conference_on_enter=True, end_conference_on_exit=True)
    vr.append(dial)
    return _twiml(vr)


@app.post("/voice/hold-music")
async def voice_hold_music(request: Request):
    vr = VoiceResponse()
    vr.play("https://helpline.weathergpt.example.com/static/hold-music.mp3")
    return _twiml(vr)


def _say_lang(lang: str) -> str:
    return {"en": "en-IN", "hi": "hi-IN", "bn": "bn-IN", "ta": "ta-IN"}.get(lang, "en-IN")
