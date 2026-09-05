"""
all_india_voice.py

Speech Pipeline for WeatherGPT – All-India Voice support via Bhashini (ULCA / Dhruva).

Provides:
  - speech_to_text(audio_bytes: bytes, lang_code: str) -> str
  - text_to_speech(text: str, lang_code: str) -> bytes

Requires environment variables (obtain free credentials from https://bhashini.gov.in):
  BHASHINI_USER_ID
  BHASHINI_API_KEY
  (optional) BHASHINI_PIPELINE_ID
"""

from __future__ import annotations

import base64
import os
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from language_manager import get_bhashini_code, normalize_lang_code

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ULCA_BASE = "https://meity-auth.ulcacontrib.org"
PIPELINE_CONFIG_ENDPOINT = f"{ULCA_BASE}/ulca/apis/v0/model/getModelsPipeline"

# Default public pipeline that supports ASR + TTS for many Indian languages
DEFAULT_PIPELINE_ID = "64392f96daac500b55c543cd"

# Inference endpoint (returned by config call, but we keep a fallback)
DEFAULT_INFERENCE_URL = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"

# Recommended service IDs (can be overridden after pipeline config)
# Multilingual Conformer covering all 22 scheduled languages
DEFAULT_ASR_SERVICE_ID = "bhashini/ai4bharat/conformer-multilingual-asr"
# Broad TTS coverage
DEFAULT_TTS_SERVICE_ID = "Bhashini/IITM/TTS"

# Audio defaults expected by most Bhashini ASR models
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_AUDIO_FORMAT = "wav"          # or "pcm", "flac" depending on model
DEFAULT_TTS_GENDER = "female"
DEFAULT_TTS_SAMPLE_RATE = 22050


class BhashiniError(RuntimeError):
    """Raised when a Bhashini API call fails."""


# ---------------------------------------------------------------------------
# Credential & pipeline helpers
# ---------------------------------------------------------------------------

def _get_credentials() -> Tuple[str, str]:
    user_id = os.getenv("BHASHINI_USER_ID", "").strip()
    api_key = os.getenv("BHASHINI_API_KEY", "").strip()
    if not user_id or not api_key:
        raise BhashiniError(
            "BHASHINI_USER_ID and BHASHINI_API_KEY environment variables must be set. "
            "Register at https://bhashini.gov.in to obtain free credentials."
        )
    return user_id, api_key


# Simple in-process cache for pipeline configuration (valid for ~1 hour)
_pipeline_cache: Dict[str, Any] = {}
_pipeline_cache_ts: float = 0.0
_PIPELINE_CACHE_TTL = 3600.0


async def _fetch_pipeline_config(
    client: httpx.AsyncClient,
    tasks: list[str],
    pipeline_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Call ULCA getModelsPipeline to obtain serviceIds and the inference
    Authorization token for the requested task sequence.
    """
    global _pipeline_cache, _pipeline_cache_ts

    cache_key = ",".join(sorted(tasks)) + "|" + (pipeline_id or DEFAULT_PIPELINE_ID)
    now = time.monotonic()
    if cache_key in _pipeline_cache and (now - _pipeline_cache_ts) < _PIPELINE_CACHE_TTL:
        return _pipeline_cache[cache_key]

    user_id, api_key = _get_credentials()
    body = {
        "pipelineTasks": [{"taskType": t} for t in tasks],
        "pipelineRequestConfig": {
            "pipelineId": pipeline_id or os.getenv("BHASHINI_PIPELINE_ID", DEFAULT_PIPELINE_ID)
        },
    }
    headers = {
        "userID": user_id,
        "ulcaApiKey": api_key,
        "Content-Type": "application/json",
    }

    resp = await client.post(PIPELINE_CONFIG_ENDPOINT, json=body, headers=headers, timeout=30.0)
    if resp.status_code != 200:
        raise BhashiniError(f"Pipeline config failed ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    _pipeline_cache[cache_key] = data
    _pipeline_cache_ts = now
    return data


def _extract_service_id(config: Dict[str, Any], task_type: str, lang: str) -> str:
    """Pick the best serviceId for a given task + language from pipeline config."""
    for block in config.get("pipelineResponseConfig", []):
        if block.get("taskType") != task_type:
            continue
        for cfg in block.get("config", []):
            src = cfg.get("language", {}).get("sourceLanguage", "")
            if src == lang or src == "en" or not src:
                return cfg.get("serviceId", "")
    # Fallbacks
    if task_type == "asr":
        return DEFAULT_ASR_SERVICE_ID
    if task_type == "tts":
        return DEFAULT_TTS_SERVICE_ID
    return ""


def _extract_inference_auth(config: Dict[str, Any]) -> Tuple[str, str]:
    """Return (callback_url, authorization_value)."""
    endpoint = config.get("pipelineInferenceAPIEndPoint", {})
    url = endpoint.get("callbackUrl", DEFAULT_INFERENCE_URL)
    key_info = endpoint.get("inferenceApiKey", {})
    token = key_info.get("value", "")
    if not token:
        raise BhashiniError("No inference Authorization token returned by pipeline config")
    return url, token


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------

async def speech_to_text(
    audio_bytes: bytes,
    lang_code: str,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    audio_format: str = DEFAULT_AUDIO_FORMAT,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """
    Convert speech audio to text using Bhashini ASR.

    Parameters
    ----------
    audio_bytes : bytes
        Raw audio content (WAV / PCM / FLAC recommended).
    lang_code : str
        Language identifier (Bhashini code, FLORES, ISO, or full name).
        Examples: "hi", "hin", "hindi", "ta", "tamil".
    sample_rate : int
        Sampling rate of the supplied audio (default 16000).
    audio_format : str
        Format string accepted by the model ("wav", "pcm", …).

    Returns
    -------
    str
        Recognised transcript.
    """
    if not audio_bytes:
        return ""

    lang = get_bhashini_code(lang_code)          # normalises via language_manager
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=60.0)

    try:
        # 1. Obtain pipeline configuration for ASR
        config = await _fetch_pipeline_config(client, tasks=["asr"])
        service_id = _extract_service_id(config, "asr", lang)
        inference_url, auth_token = _extract_inference_auth(config)

        # 2. Build inference payload
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        payload = {
            "pipelineTasks": [
                {
                    "taskType": "asr",
                    "config": {
                        "language": {"sourceLanguage": lang},
                        "serviceId": service_id,
                        "audioFormat": audio_format,
                        "samplingRate": sample_rate,
                    },
                }
            ],
            "inputData": {
                "audio": [
                    {"audioContent": audio_b64}
                ]
            },
        }
        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json",
        }

        resp = await client.post(inference_url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise BhashiniError(f"ASR inference failed ({resp.status_code}): {resp.text[:400]}")

        result = resp.json()
        # Typical response path
        try:
            output = result["pipelineResponse"][0]["output"][0]["source"]
            return (output or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise BhashiniError(f"Unexpected ASR response structure: {result}") from exc

    finally:
        if owns_client:
            await client.aclose()


async def text_to_speech(
    text: str,
    lang_code: str,
    *,
    gender: str = DEFAULT_TTS_GENDER,
    sample_rate: int = DEFAULT_TTS_SAMPLE_RATE,
    client: Optional[httpx.AsyncClient] = None,
) -> bytes:
    """
    Synthesize speech from text using Bhashini TTS.

    Parameters
    ----------
    text : str
        Unicode text to speak (should already be in the target script).
    lang_code : str
        Target language identifier.
    gender : str
        Preferred voice gender ("female" | "male").
    sample_rate : int
        Desired output sampling rate.

    Returns
    -------
    bytes
        Audio content (usually WAV or MP3 depending on the model).
    """
    text = (text or "").strip()
    if not text:
        return b""

    lang = get_bhashini_code(lang_code)
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=60.0)

    try:
        # 1. Pipeline config for TTS
        config = await _fetch_pipeline_config(client, tasks=["tts"])
        service_id = _extract_service_id(config, "tts", lang)
        inference_url, auth_token = _extract_inference_auth(config)

        # 2. Inference payload
        payload = {
            "pipelineTasks": [
                {
                    "taskType": "tts",
                    "config": {
                        "language": {"sourceLanguage": lang},
                        "serviceId": service_id,
                        "gender": gender,
                        "samplingRate": sample_rate,
                    },
                }
            ],
            "inputData": {
                "input": [
                    {"source": text}
                ]
            },
        }
        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json",
        }

        resp = await client.post(inference_url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise BhashiniError(f"TTS inference failed ({resp.status_code}): {resp.text[:400]}")

        result = resp.json()
        try:
            # Audio is returned base64-encoded
            audio_b64 = result["pipelineResponse"][0]["audio"][0]["audioContent"]
            return base64.b64decode(audio_b64)
        except (KeyError, IndexError, TypeError) as exc:
            raise BhashiniError(f"Unexpected TTS response structure: {result}") from exc

    finally:
        if owns_client:
            await client.aclose()


# ---------------------------------------------------------------------------
# Synchronous convenience wrappers (for non-async callers)
# ---------------------------------------------------------------------------

def speech_to_text_sync(audio_bytes: bytes, lang_code: str, **kwargs) -> str:
    """Blocking wrapper around speech_to_text."""
    import asyncio
    return asyncio.run(speech_to_text(audio_bytes, lang_code, **kwargs))


def text_to_speech_sync(text: str, lang_code: str, **kwargs) -> bytes:
    """Blocking wrapper around text_to_speech."""
    import asyncio
    return asyncio.run(text_to_speech(text, lang_code, **kwargs))


# ---------------------------------------------------------------------------
# Development / offline fallback (no credentials)
# ---------------------------------------------------------------------------

# Default weather questions per language for mock STT
_MOCK_QUESTIONS: Dict[str, str] = {
    "hindi": "आज मौसम कैसा रहेगा?",
    "bengali": "আজকের আবহাওয়া কেমন থাকবে?",
    "tamil": "இன்று வானிலை எப்படி இருக்கும்?",
    "telugu": "ఈరేపు వాతావరణం ఎలా ఉంటుంది?",
    "marathi": "आज हवामान कसे असेल?",
    "gujarati": "આજે હવામાન શું રહેશે?",
    "kannada": "ಇಂದು ಆದರೆ ಹೇಗಿರುತ್ತದೆ?",
    "malayalam": "ഇന്ന് കാലാവസ്ഥ എങ്ങനെ ആകും?",
    "punjabi": "ਅੱਜ ਮੌਸਮ ਕਿਵੇਂ ਰਹੇਗਾ?",
    "urdu": "آج موسم کیسا ہوگا؟",
    "odia": "ଆଜି ମୌସମ କିପରି ରହିବ?",
    "assamese": "আজিৰ অসমীয়া মৌসম কেনে হ'ব?",
    "nepali": "आज मौसम कसरी हुनेछ?",
    "sindhi": "اَجِ موسم ڇوڀراڻي؟",
    "sanskrit": "आज मौसमः कथम् भविष्यति?",
    "english": "What is the weather like today?",
}


# Default bilingual advisory snippets per language for mock TTS
_MOCK_ADVISORIES: Dict[str, str] = {
    "hindi": "आज मौसम सुधरेला। तापमान मध्यम रहेगा और बारिश की संभावना कम। सुरक्षित रहें।",
    "bengali": "আজ আবহাওয়া ভালো থাকবে। তাপমাত্রা মাঝারি এবং বৃষ্টির সম্ভাবনা কম। সুরক্ষিত থাকুন।",
    "tamil": "இன்று வானிலை சிறப்பாக இருக்கும். வெப்பநிலை நடுநிலையில் இருக்கும் மற்றும் மழை�ின் சாத்தியக்கும் சிறிது. பாதுகாக்கப்படுங்கள்.",
    "telugu": "ఈరేపు వాతావరణం మంచిగా ఉంటుంది. ఉష్ణోగ్రత సాధారణంగా ఉంటుంది మరియు వర్ష సంభావన తక్కువ. సురక్షితంగా ఉండండి.",
    "english": "Today's weather looks good. Temperature will be moderate with low chance of rain. Stay safe.",
}


async def speech_to_text_mock(audio_bytes: bytes, lang_code: str) -> str:
    """Return a deterministic mock transcript when credentials are absent."""
    lang = normalize_lang_code(lang_code)
    question = _MOCK_QUESTIONS.get(lang, _MOCK_QUESTIONS["english"])
    return question


async def text_to_speech_mock(text: str, lang_code: str) -> bytes:
    """
    Generate TTS audio using gTTS if available, otherwise
    return a silent WAV header as a last-resort mock.
    """
    try:
        from gtts import gTTS
        import io as _io
        eng = normalize_lang_code(lang_code)
        gtts_lang = get_bhashini_code(eng)
        supported = {"en", "hi", "bn", "ta", "te", "ml", "kn", "gu", "mr", "pa", "ur", "ne"}
        if gtts_lang not in supported:
            gtts_lang = "en"
        tts = gTTS(text=text, lang=gtts_lang, slow=False)
        buf = _io.BytesIO()
        tts.write_to_fp(buf)
        return buf.getvalue()
    except Exception:
        pass

    # Minimal valid silent WAV (44-byte header + a few zero samples)
    silent_wav = (
        b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
        b"\x40\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    )
    return silent_wav


# ---------------------------------------------------------------------------
# Auto-select real vs mock implementation
# ---------------------------------------------------------------------------

def _credentials_available() -> bool:
    return bool(os.getenv("BHASHINI_USER_ID") and os.getenv("BHASHINI_API_KEY"))


# Public names that the rest of the application should import
if _credentials_available():
    # Real Bhashini implementations already defined above
    pass
else:
    # Override with safe mocks so the rest of the stack can still start
    speech_to_text = speech_to_text_mock  # type: ignore
    text_to_speech = text_to_speech_mock  # type: ignore


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def demo() -> None:
        print("Credentials available:", _credentials_available())
        print("Testing TTS (may be mock)…")
        audio = await text_to_speech("नमस्ते, आज का मौसम कैसा है?", "hi")
        print(f"  Received {len(audio)} bytes of audio")

        print("Testing ASR with dummy bytes (may be mock)…")
        transcript = await speech_to_text(b"\x00" * 1000, "hi")
        print(f"  Transcript: {transcript}")

    asyncio.run(demo())