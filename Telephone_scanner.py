"""
backend/app/core/telephony_service.py

Twilio TwiML builders that power interactive voice response (IVR) calls
for WeatherGPT users who do not have smartphones.

Typical call flow
-----------------
1. Welcome + language selection (DTMF or speech)
2. Capture / confirm location (pincode or pre-registered)
3. Ask for the weather question (speech)
4. Run the AI pipeline (STT → advisory → TTS)
5. Play the advisory and offer repeat / new query / hang-up

All public methods return a Twilio `VoiceResponse` object that can be
returned directly from a FastAPI / Flask webhook.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from twilio.twiml.voice_response import (
    VoiceResponse,
    Gather,
    Say,
    Play,
    Redirect,
    Hangup,
    Pause,
)

logger = logging.getLogger("telephony_service")

# ---------------------------------------------------------------------------
# Configuration (override with environment variables)
# ---------------------------------------------------------------------------

# Base URL of this backend – used to build absolute action callbacks
BASE_URL = os.getenv("TELEPHONY_BASE_URL", "https://your-weathergpt-domain.com").rstrip("/")

# Twilio voice / language defaults
DEFAULT_VOICE = os.getenv("TWILIO_VOICE", "Polly.Aditi")          # Indian English female
DEFAULT_LANGUAGE = os.getenv("TWILIO_LANGUAGE", "hi-IN")

# Supported IVR languages (DTMF digit → Bhashini / internal code)
IVR_LANGUAGE_MAP: Dict[str, str] = {
    "1": "hi",   # Hindi
    "2": "en",   # English
    "3": "bn",   # Bengali
    "4": "ta",   # Tamil
    "5": "te",   # Telugu
    "6": "mr",   # Marathi
    "7": "gu",   # Gujarati
    "8": "kn",   # Kannada
    "9": "ml",   # Malayalam
}

# Human-readable prompts (keep short for telephony)
PROMPTS = {
    "welcome": {
        "hi": "नमस्ते। वेदर जीपीटी में आपका स्वागत है।",
        "en": "Welcome to WeatherGPT.",
        "bn": "নমস্কার। ওয়েদার জিপিটিতে স্বাগতম।",
        "ta": "வணக்கம். வெதர் ஜிபிடிக்கு வரவேற்கிறோம்.",
        "te": "నమస్కారం. వెదర్ జీపీటీకి స్వాగతం.",
        "mr": "नमस्कार. वेदर जीपीटी मध्ये आपले स्वागत आहे.",
        "gu": "નમસ્તે. વેધર જીપીટીમાં આપનું સ્વાગત છે.",
        "kn": "ನಮಸ್ಕಾರ. ವೆದರ್ ಜಿಪಿಟಿಗೆ ಸುಸ್ವಾಗತ.",
        "ml": "നമസ്കാരം. വെതർ ജിപിടിയിലേക്ക് സ്വാഗതം.",
    },
    "select_language": {
        "en": (
            "Press 1 for Hindi, 2 for English, 3 for Bengali, "
            "4 for Tamil, 5 for Telugu, 6 for Marathi, "
            "7 for Gujarati, 8 for Kannada, 9 for Malayalam."
        ),
        "hi": (
            "हिंदी के लिए 1 दबाएं, अंग्रेजी के लिए 2, "
            "बंगाली के लिए 3, तमिल के लिए 4, तेलुगु के लिए 5, "
            "मराठी के लिए 6, गुजराती के लिए 7, कन्नड़ के लिए 8, "
            "मलयालम के लिए 9।"
        ),
    },
    "ask_pincode": {
        "hi": "कृपया अपना छह अंकों का पिनकोड दर्ज करें और फिर हैश दबाएं।",
        "en": "Please enter your six-digit pincode followed by the hash key.",
    },
    "ask_query": {
        "hi": "अपना मौसम संबंधी सवाल बोलें। बोलने के बाद चुप रहें।",
        "en": "Please speak your weather question. Stay silent when finished.",
    },
    "processing": {
        "hi": "कृपया प्रतीक्षा करें, हम आपकी जानकारी प्राप्त कर रहे हैं।",
        "en": "Please wait while we fetch the latest information for you.",
    },
    "repeat_or_new": {
        "hi": "दोबारा सुनने के लिए 1 दबाएं। नया सवाल पूछने के लिए 2 दबाएं। कॉल समाप्त करने के लिए 3 दबाएं।",
        "en": "Press 1 to repeat. Press 2 for a new question. Press 3 to hang up.",
    },
    "goodbye": {
        "hi": "धन्यवाद। वेदर जीपीटी का उपयोग करने के लिए धन्यवाद। नमस्ते।",
        "en": "Thank you for using WeatherGPT. Goodbye.",
    },
    "error": {
        "hi": "क्षमा करें, एक त्रुटि हुई। कृपया बाद में पुनः प्रयास करें।",
        "en": "Sorry, an error occurred. Please try again later.",
    },
}


def _t(key: str, lang: str = "en") -> str:
    """Fetch a prompt in the requested language, falling back to English."""
    block = PROMPTS.get(key, {})
    return block.get(lang) or block.get("en") or ""


# ---------------------------------------------------------------------------
# TwiML builders
# ---------------------------------------------------------------------------

class TelephonyService:
    """
    Collection of static helpers that produce ready-to-return TwiML.
    """

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    @staticmethod
    def welcome(lang: str = "en") -> VoiceResponse:
        """
        Initial greeting + language selection menu.
        Webhook: POST /telephony/voice/incoming
        """
        resp = VoiceResponse()
        resp.say(_t("welcome", lang), voice=DEFAULT_VOICE, language=DEFAULT_LANGUAGE)
        resp.pause(length=1)

        gather = Gather(
            num_digits=1,
            action=f"{BASE_URL}/telephony/voice/language",
            method="POST",
            timeout=8,
            prosody={"rate": "medium"},
        )
        gather.say(_t("select_language", "en"), voice=DEFAULT_VOICE, language="en-IN")
        resp.append(gather)

        # Fallback if no input
        resp.redirect(f"{BASE_URL}/telephony/voice/incoming")
        return resp

    # ------------------------------------------------------------------
    # Language selection callback
    # ------------------------------------------------------------------

    @staticmethod
    def language_selected(digits: str) -> VoiceResponse:
        """
        Handle DTMF language choice and proceed to pincode capture.
        Webhook: POST /telephony/voice/language
        """
        lang = IVR_LANGUAGE_MAP.get(digits, "en")
        resp = VoiceResponse()

        # Store language in the call via a query parameter on the next redirect
        next_url = f"{BASE_URL}/telephony/voice/pincode?lang={lang}"
        resp.redirect(next_url)
        return resp

    # ------------------------------------------------------------------
    # Pincode / location capture
    # ------------------------------------------------------------------

    @staticmethod
    def collect_pincode(lang: str = "en") -> VoiceResponse:
        """
        Ask the caller for a 6-digit Indian pincode.
        Webhook: GET/POST /telephony/voice/pincode
        """
        resp = VoiceResponse()
        gather = Gather(
            num_digits=6,
            action=f"{BASE_URL}/telephony/voice/pincode-confirm?lang={lang}",
            method="POST",
            timeout=12,
            finish_on_key="#",
        )
        gather.say(_t("ask_pincode", lang), voice=DEFAULT_VOICE, language=_twilio_lang(lang))
        resp.append(gather)

        # No input → retry
        resp.redirect(f"{BASE_URL}/telephony/voice/pincode?lang={lang}")
        return resp

    @staticmethod
    def pincode_confirm(pincode: str, lang: str = "en") -> VoiceResponse:
        """
        Acknowledge pincode and move to speech query collection.
        Webhook: POST /telephony/voice/pincode-confirm
        """
        resp = VoiceResponse()
        # In production you would resolve pincode → lat/lon here
        # and store it in the call session / Redis.
        next_url = f"{BASE_URL}/telephony/voice/query?lang={lang}&pincode={pincode}"
        resp.redirect(next_url)
        return resp

    # ------------------------------------------------------------------
    # Speech query capture
    # ------------------------------------------------------------------

    @staticmethod
    def collect_query(lang: str = "en", pincode: str = "") -> VoiceResponse:
        """
        Use <Gather input="speech"> to capture the user's weather question.
        Webhook: GET/POST /telephony/voice/query
        """
        resp = VoiceResponse()
        action = f"{BASE_URL}/telephony/voice/process?lang={lang}&pincode={pincode}"

        gather = Gather(
            input="speech",
            action=action,
            method="POST",
            timeout=6,
            speech_timeout="auto",
            language=_twilio_lang(lang),
            enhanced=True,
            speech_model="phone_call",
        )
        gather.say(_t("ask_query", lang), voice=DEFAULT_VOICE, language=_twilio_lang(lang))
        resp.append(gather)

        # Timeout → prompt again
        resp.redirect(f"{BASE_URL}/telephony/voice/query?lang={lang}&pincode={pincode}")
        return resp

    # ------------------------------------------------------------------
    # Processing placeholder (played while backend runs AI pipeline)
    # ------------------------------------------------------------------

    @staticmethod
    def processing(lang: str = "en") -> VoiceResponse:
        """
        Short “please wait” message.
        Can be returned while the real advisory is being generated.
        """
        resp = VoiceResponse()
        resp.say(_t("processing", lang), voice=DEFAULT_VOICE, language=_twilio_lang(lang))
        resp.pause(length=2)
        return resp

    # ------------------------------------------------------------------
    # Play final advisory
    # ------------------------------------------------------------------

    @staticmethod
    def play_advisory(
        audio_url: Optional[str] = None,
        text: Optional[str] = None,
        lang: str = "en",
        pincode: str = "",
    ) -> VoiceResponse:
        """
        Play a pre-generated TTS audio file or fall back to <Say>.
        Then offer repeat / new query / hang-up menu.

        Parameters
        ----------
        audio_url : public HTTPS URL of the MP3/WAV generated by voice_service
        text      : plain-text fallback if no audio_url is available
        """
        resp = VoiceResponse()

        if audio_url:
            resp.play(audio_url)
        elif text:
            resp.say(text, voice=DEFAULT_VOICE, language=_twilio_lang(lang))
        else:
            resp.say(_t("error", lang), voice=DEFAULT_VOICE, language=_twilio_lang(lang))

        resp.pause(length=1)

        # Post-advisory menu
        gather = Gather(
            num_digits=1,
            action=f"{BASE_URL}/telephony/voice/menu?lang={lang}&pincode={pincode}",
            method="POST",
            timeout=8,
        )
        gather.say(_t("repeat_or_new", lang), voice=DEFAULT_VOICE, language=_twilio_lang(lang))
        resp.append(gather)

        # Default → goodbye
        resp.redirect(f"{BASE_URL}/telephony/voice/goodbye?lang={lang}")
        return resp

    # ------------------------------------------------------------------
    # Post-advisory menu handler
    # ------------------------------------------------------------------

    @staticmethod
    def handle_menu(digits: str, lang: str = "en", pincode: str = "") -> VoiceResponse:
        """
        1 = repeat last advisory (caller must re-request or cache)
        2 = new query
        3 = hang up
        """
        resp = VoiceResponse()
        if digits == "1":
            # In a real system you would replay the cached audio URL
            resp.redirect(f"{BASE_URL}/telephony/voice/query?lang={lang}&pincode={pincode}")
        elif digits == "2":
            resp.redirect(f"{BASE_URL}/telephony/voice/query?lang={lang}&pincode={pincode}")
        else:
            resp.redirect(f"{BASE_URL}/telephony/voice/goodbye?lang={lang}")
        return resp

    # ------------------------------------------------------------------
    # Goodbye
    # ------------------------------------------------------------------

    @staticmethod
    def goodbye(lang: str = "en") -> VoiceResponse:
        resp = VoiceResponse()
        resp.say(_t("goodbye", lang), voice=DEFAULT_VOICE, language=_twilio_lang(lang))
        resp.hangup()
        return resp

    # ------------------------------------------------------------------
    # Generic error
    # ------------------------------------------------------------------

    @staticmethod
    def error(lang: str = "en") -> VoiceResponse:
        resp = VoiceResponse()
        resp.say(_t("error", lang), voice=DEFAULT_VOICE, language=_twilio_lang(lang))
        resp.hangup()
        return resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _twilio_lang(lang_code: str) -> str:
    """
    Map internal Bhashini-style codes to Twilio SSML language tags.
    """
    mapping = {
        "hi": "hi-IN",
        "en": "en-IN",
        "bn": "bn-IN",
        "ta": "ta-IN",
        "te": "te-IN",
        "mr": "mr-IN",
        "gu": "gu-IN",
        "kn": "kn-IN",
        "ml": "ml-IN",
        "pa": "pa-IN",
        "ur": "ur-IN",
    }
    return mapping.get(lang_code, "en-IN")


def twiml_response(vr: VoiceResponse) -> str:
    """Return the XML string ready for an HTTP response."""
    return str(vr)


# ---------------------------------------------------------------------------
# Self-test (prints sample TwiML)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Welcome ===")
    print(TelephonyService.welcome())
    print("\n=== Collect Query (Hindi) ===")
    print(TelephonyService.collect_query(lang="hi", pincode="110001"))
    print("\n=== Play Advisory (text fallback) ===")
    print(
        TelephonyService.play_advisory(
            text="आज दिल्ली में हल्की बारिश की संभावना है।",
            lang="hi",
            pincode="110001",
        )
    )
    print("\n=== Goodbye ===")
    print(TelephonyService.goodbye(lang="hi"))