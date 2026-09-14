"""
voice_webhook.py

Twilio Programmable Voice webhooks:
  POST /voice/incoming  - first webhook Twilio hits on an inbound call
  POST /voice/gather    - handles the speech result of each turn
  POST /voice/ivr       - DTMF menu fallback (language / topic selection)
  POST /voice/whisper   - TwiML played to the human agent before bridging (warm transfer)

Flow:
  1. Caller dials the WeatherGPT number.
  2. TwiML <Gather input="speech" input="dtmf"> captures their query.
     - speech input is the primary path for callers whose language Twilio
       recognises well.
     - DTMF fallback lets callers press digits to pick a language or topic
       when Twilio's speech recognition is unreliable for their language
       (README.md section 3 notes that Twilio's ASR coverage is inconsistent
       across Indian languages; the DTMF menu covers Hindi, English, Bengali,
       Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam, Punjabi, Urdu,
       Odia, Assamese, Nepali — all 14 major Indian languages).
  3. We call CoreAgent.handle_turn(). If it decides to escalate, we place
     the caller into a hold conference and dial a human agent, whispering
     the handoff summary to the agent before merging the two legs.
  4. If not escalating, we speak the reply and <Gather> again.

Requires: pip install fastapi uvicorn twilio redis
Env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_NUMBER,
          HUMAN_AGENT_ROUTING (see routing_table below)
"""

import logging
import os

from fastapi import FastAPI, Request, Response
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import Dial, Gather, VoiceResponse

from core_agent import CoreAgent
from escalation_engine import Queue

logger = logging.getLogger("voice_webhook")

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
    except Exception as exc:
        logger.warning("Twilio client init failed: %s", exc)

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
    "te": "te-IN",
    "mr": "mr-IN",
    "gu": "gu-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "pa": "pa-IN",
    "ur": "ur-IN",
    "or": "or-IN",
    "as": "as-IN",
    "ne": "ne-IN",
}

# DTMF menu mapping for the IVR fallback.
# Callers press digits to select a language, then another digit to select a topic.
# This covers all 14 major Indian languages that Twilio's <Say> supports,
# and gives a reliable non-speech path for callers whose language Twilio
# doesn't recognise well via speech recognition.
DTMF_LANGUAGE_MENU = {
    "1": "hi",  # Hindi
    "2": "en",  # English
    "3": "bn",  # Bengali
    "4": "ta",  # Tamil
    "5": "te",  # Telugu
    "6": "mr",  # Marathi
    "7": "gu",  # Gujarati
    "8": "kn",  # Kannada
    "9": "ml",  # Malayalam
    "0": "pa",  # Punjabi
    "10": "ur",  # Urdu
    "11": "or",  # Odia
    "12": "as",  # Assamese
    "13": "ne",  # Nepali
}

# Topic menu for the second-level DTMF selection
DTMF_TOPIC_MENU = {
    "1": "weather",
    "2": "crops",
    "3": "emergency",
    "4": "market",
    "5": "general",
}


def _twiml(response: VoiceResponse) -> Response:
    return Response(content=str(response), media_type="application/xml")


@app.post("/voice/incoming")
async def voice_incoming(request: Request):
    """First webhook on an inbound call. Greets and starts listening."""
    vr = VoiceResponse()

    # Check if the caller used DTMF to request a language/topic menu.
    form = await request.form()
    digits = form.get("Digits")
    if digits and digits.strip(" *#") == "99":
        # Caller pressed 99 for the language menu
        return _twiml_ivr_language_menu()

    if digits and form.get("ivr_step") == "topic" and digits.strip(" *#") in DTMF_TOPIC_MENU:
        # Caller selected a topic from the menu; route to CoreAgent with context
        topic = DTMF_TOPIC_MENU[digits.strip(" *#")]
        lang = form.get("lang", "en")
        return await _handle_dtmf_topic_selection(digits.strip(" *#"), lang, topic)

    gather = Gather(
        input="speech dtmf",
        action=f"{PUBLIC_BASE_URL}/voice/gather?lang=en",
        method="POST",
        language=LANGUAGE_CODES["en"],
        speech_timeout="auto",
        num_digits="1",
        action_on_enumerate="true",
    )
    gather.say(
        "Welcome to WeatherGPT helpline. Please tell me your question about "
        "weather, crops, or a nearby emergency, after the beep. "
        "If you cannot speak, press 9 then 9 for the menu.",
        language="en-IN",
    )
    vr.append(gather)
    # If no speech detected, retry once before hanging up gracefully.
    vr.redirect(f"{PUBLIC_BASE_URL}/voice/incoming")
    return _twiml(vr)


def _twiml_ivr_language_menu() -> Response:
    """
    Present the DTMF language selection menu.

    Callers press 1-0, then 10-13 (using * as a separator, or entering the
    full number) to pick their language. After language selection they are
    prompted for a topic.
    """
    vr = VoiceResponse()
    gather = Gather(
        input="dtmf",
        action=f"{PUBLIC_BASE_URL}/voice/ivr?step=language",
        method="POST",
        num_digits=2,  # allows 01-13
        finish_on_key="#",
    )
    gather.say(
        "कृपया अपनी भाषा चुनें। Please select your language. "
        "Press 1 for Hindi, 2 for English, 3 for Bengali, 4 for Tamil, "
        "5 for Telugu, 6 for Marathi, 7 for Gujarati, 8 for Kannada, "
        "9 for Malayalam, 0 then 1 for Punjabi, 0 then 2 for Urdu, "
        "0 then 3 for Odia, 0 then 4 for Assamese, 0 then 5 for Nepali. "
        "Press the # key when done.",
        language="hi-IN",
    )
    vr.append(gather)
    vr.redirect(f"{PUBLIC_BASE_URL}/voice/incoming")
    return _twiml(vr)


@app.post("/voice/ivr")
async def voice_ivr(request: Request, step: str = "language"):
    """
    Handle DTMF menu navigation for callers who cannot use speech recognition.

    step=language: caller selected a language from DTMF_LANGUAGE_MENU
    step=topic: caller selected a topic from DTMF_TOPIC_MENU
    """
    form = await request.form()
    digits = form.get("Digits", "").strip(" *#")

    if step == "language":
        lang = DTMF_LANGUAGE_MENU.get(digits)
        if not lang:
            vr = VoiceResponse()
            gather = Gather(
                input="dtmf",
                action=f"{PUBLIC_BASE_URL}/voice/ivr?step=language",
                method="POST",
                num_digits=2,
                finish_on_key="#",
            )
            gather.say("Invalid selection. Please try again.", language="en-IN")
            vr.append(gather)
            return _twiml(vr)

        # Proceed to topic selection
        vr = VoiceResponse()
        gather = Gather(
            input="dtmf",
            action=f"{PUBLIC_BASE_URL}/voice/ivr?step=topic&lang={lang}",
            method="POST",
            num_digits=1,
        )
        gather.say(
            f"भाषा चुनी गई: {lang}. Please select a topic. "
            "Press 1 for weather, 2 for crops, 3 for emergency, "
            "4 for market prices, 5 for general help.",
            language=LANGUAGE_CODES.get(lang, "en-IN"),
        )
        vr.append(gather)
        return _twiml(vr)

    if step == "topic":
        lang = form.get("lang", "en")
        topic = DTMF_TOPIC_MENU.get(digits)
        if not topic:
            vr = VoiceResponse()
            gather = Gather(
                input="dtmf",
                action=f"{PUBLIC_BASE_URL}/voice/ivr?step=topic&lang={lang}",
                method="POST",
                num_digits=1,
            )
            gather.say("Invalid topic selection. Please try again.",
                       language=LANGUAGE_CODES.get(lang, "en-IN"))
            vr.append(gather)
            return _twiml(vr)

        return await _handle_dtmf_topic_selection(digits, lang, topic)

    # Unknown step — fall back to normal speech gather
    vr = VoiceResponse()
    gather = Gather(
        input="speech dtmf",
        action=f"{PUBLIC_BASE_URL}/voice/gather?lang={form.get('lang', 'en')}",
        method="POST",
        language=LANGUAGE_CODES.get(form.get("lang", "en"), "en-IN"),
        speech_timeout="auto",
        num_digits=1,
    )
    gather.say("Please speak your question after the beep.", language="en-IN")
    vr.append(gather)
    return _twiml(vr)


async def _handle_dtmf_topic_selection(digit: str, lang: str, topic: str) -> Response:
    """
    Route a DTMF-selected topic to the CoreAgent, then either speak the
    reply or escalate to a human agent.

    DTMF callers can't be asked for a free-form utterance like speech callers,
    so we synthesize a natural-language query from the topic and route it
    through the exact same CoreAgent.handle_turn() path.
    """
    # Map DTMF topics to a simple query string in the selected language
    # (CoreAgent will detect/translate from these)
    topic_queries = {
        "weather": "मौसम किस है" if lang == "hi" else "What is the weather?",
        "crops": "फसल के बारे में सल्ला" if lang == "hi" else "Crop advice?",
        "emergency": "आपातकालीन सहायता" if lang == "hi" else "Emergency help!",
        "market": "मंडी भाव कितना है" if lang == "hi" else "Market prices?",
        "general": "मदद चाहिए" if lang == "hi" else "I need help.",
    }

    user_text = topic_queries.get(topic, topic)
    _call_sid = ""  # not available in DTMF context; use a generated session
    session_id = f"sms-dtmf-{lang}-{topic}"

    try:
        reply = await agent.handle_turn(
            session_id=session_id,
            channel="voice",
            user_text=user_text,
            language=lang,
            location=None,
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

        # For DTMF callers, we need a new Gather with both speech and dtmf
        # so they can continue either by speaking or pressing digits
        gather = Gather(
            input="speech dtmf",
            action=f"{PUBLIC_BASE_URL}/voice/gather?lang={lang}",
            method="POST",
            language=LANGUAGE_CODES.get(lang, "en-IN"),
            speech_timeout="auto",
            num_digits=1,
        )
        gather.say(reply.text, language=_say_lang(lang))
        vr.append(gather)
        vr.redirect(f"{PUBLIC_BASE_URL}/voice/incoming?lang={lang}")
        return _twiml(vr)

    except Exception as _exc:
        logger.exception("DTMF topic handling failed")
        vr = VoiceResponse()
        vr.say(
            "क्षमा करें, अभी सेवा उपलब्ध नहीं है। कृपया बाद में प्रयास करें।",
            language=_say_lang(lang),
        )
        return _twiml(vr)


@app.post("/voice/gather")
async def voice_gather(request: Request, lang: str = "en"):
    """Handles the caller's spoken query (or DTMF fallback) for this turn."""
    form = await request.form()
    call_sid = form.get("CallSid")
    speech_result = form.get("SpeechResult", "")
    digits = form.get("Digits", "")
    _caller_number = form.get("From")

    # If the caller pressed digits instead of speaking, route to CoreAgent
    # with a synthesized query
    if digits and not speech_result:
        digit = digits.strip(" *#")
        if digit in DTMF_TOPIC_MENU:
            return await _handle_dtmf_topic_selection(digit, lang, DTMF_TOPIC_MENU[digit])
        # Unrecognised DTMF — re-prompt
        vr = VoiceResponse()
        gather = Gather(
            input="speech dtmf",
            action=f"{PUBLIC_BASE_URL}/voice/gather?lang={lang}",
            method="POST",
            language=LANGUAGE_CODES.get(lang, "en-IN"),
            speech_timeout="auto",
            num_digits=1,
        )
        gather.say("Invalid selection. Please try again.", language=_say_lang(lang))
        vr.append(gather)
        vr.redirect(f"{PUBLIC_BASE_URL}/voice/gather?lang={lang}")
        return _twiml(vr)

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

    # Include dtmf in the Gather so callers can fall back to digits
    gather = Gather(
        input="speech dtmf",
        action=f"{PUBLIC_BASE_URL}/voice/gather?lang={lang}",
        method="POST",
        language=LANGUAGE_CODES.get(lang, "en-IN"),
        speech_timeout="auto",
        num_digits=1,
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
