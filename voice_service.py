
"""
backend/app/core/voice_service.py

Audio processing pipeline for WeatherGPT.

Primary path  : Bhashini ASR / TTS  (all_india_voice.py)
Fallback path : OpenAI Whisper (STT) + gTTS (TTS)

The service automatically switches to the fallback stack when Bhashini
credentials are missing or the remote API is unreachable.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile

import httpx

from language_manager import get_bhashini_code, normalize_lang_code

logger = logging.getLogger("voice_service")

# ---------------------------------------------------------------------------
# Optional heavy dependencies – imported lazily so the module still loads
# when they are not installed.
# ---------------------------------------------------------------------------

_WHISPER_MODEL = None
_GTTS_AVAILABLE = False

try:
    from gtts import gTTS
    _GTTS_AVAILABLE = True
except ImportError:
    logger.warning("gTTS not installed – TTS fallback will be unavailable")

try:
    import whisper
    _WHISPER_AVAILABLE = True
except ImportError:
    _WHISPER_AVAILABLE = False
    logger.warning("openai-whisper not installed – STT fallback will be unavailable")


def _load_whisper(model_size: str = "base"):
    """Load (and cache) a Whisper model.  Called only on first fallback use."""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None and _WHISPER_AVAILABLE:
        size = os.getenv("WHISPER_MODEL_SIZE", model_size)
        logger.info("Loading Whisper model '%s' …", size)
        _WHISPER_MODEL = whisper.load_model(size)
    return _WHISPER_MODEL


# ---------------------------------------------------------------------------
# Bhashini availability probe
# ---------------------------------------------------------------------------

def _bhashini_configured() -> bool:
    return bool(os.getenv("BHASHINI_USER_ID") and os.getenv("BHASHINI_API_KEY"))


async def _bhashini_reachable(timeout: float = 4.0) -> bool:
    """Quick connectivity check against the Dhruva inference host."""
    if not _bhashini_configured():
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # HEAD or lightweight GET – we only care that the host answers
            resp = await client.get("https://dhruva-api.bhashini.gov.in/")
            return resp.status_code < 500
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Primary implementations (delegate to all_india_voice)
# ---------------------------------------------------------------------------

async def _bhashini_stt(audio_bytes: bytes, lang_code: str) -> str:
    from all_India_voice import speech_to_text
    return await speech_to_text(audio_bytes, lang_code)


async def _bhashini_tts(text: str, lang_code: str) -> bytes:
    from all_India_voice import text_to_speech
    return await text_to_speech(text, lang_code)


# ---------------------------------------------------------------------------
# Fallback implementations
# ---------------------------------------------------------------------------

def _whisper_stt_sync(audio_bytes: bytes, lang_code: str) -> str:
    """Synchronous Whisper transcription (runs in a thread)."""
    model = _load_whisper()
    if model is None:
        raise RuntimeError("Whisper is not available")

    # Whisper expects a file path or a numpy array; easiest is a temp file
    suffix = ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        # Map our language codes to Whisper’s ISO-639-1 where possible
        whisper_lang = get_bhashini_code(lang_code)
        if whisper_lang == "or":          # Odia
            whisper_lang = None           # let Whisper auto-detect
        result = model.transcribe(
            tmp_path,
            language=whisper_lang if whisper_lang != "en" else "en",
            fp16=False,
        )
        return (result.get("text") or "").strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def _whisper_stt(audio_bytes: bytes, lang_code: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _whisper_stt_sync, audio_bytes, lang_code)


def _gtts_tts_sync(text: str, lang_code: str) -> bytes:
    """Synchronous gTTS synthesis (runs in a thread)."""
    if not _GTTS_AVAILABLE:
        raise RuntimeError("gTTS is not available")

    # gTTS supports a limited set of Indic languages; fall back to English
    # for unsupported codes so the pipeline never hard-fails.
    gtts_lang = get_bhashini_code(lang_code)
    supported = {
        "en", "hi", "bn", "ta", "te", "ml", "kn", "gu", "mr", "pa", "ur",
        "ne", "si",  # extra useful codes
    }
    if gtts_lang not in supported:
        logger.warning("gTTS does not support '%s' – using English", gtts_lang)
        gtts_lang = "en"

    tts = gTTS(text=text, lang=gtts_lang, slow=False)
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    return buf.getvalue()


async def _gtts_tts(text: str, lang_code: str) -> bytes:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _gtts_tts_sync, text, lang_code)


# ---------------------------------------------------------------------------
# Public pipeline API
# ---------------------------------------------------------------------------

class VoiceService:
    """
    Unified speech interface with automatic fallback.

    Usage
    -----
        svc = VoiceService()
        text  = await svc.speech_to_text(audio_bytes, "hi")
        audio = await svc.text_to_speech("नमस्ते", "hi")
    """

    def __init__(self, prefer_bhashini: bool = True) -> None:
        self.prefer_bhashini = prefer_bhashini
        self._bhashini_ok: bool | None = None   # cached reachability

    async def _use_bhashini(self) -> bool:
        if not self.prefer_bhashini:
            return False
        if self._bhashini_ok is None:
            self._bhashini_ok = await _bhashini_reachable()
            if not self._bhashini_ok:
                logger.warning("Bhashini unreachable or unconfigured – using fallback stack")
        return self._bhashini_ok

    # ------------------------------------------------------------------
    # STT
    # ------------------------------------------------------------------

    async def speech_to_text(
        self,
        audio_bytes: bytes,
        lang_code: str = "hi",
    ) -> str:
        """
        Convert audio to text.

        Tries Bhashini first; falls back to mock or Whisper when unconfigured.
        """
        if not audio_bytes:
            return ""

        lang = normalize_lang_code(lang_code)

        if await self._use_bhashini():
            try:
                return await _bhashini_stt(audio_bytes, lang)
            except Exception as exc:
                logger.warning("Bhashini STT failed (%s) – falling back", exc)
                self._bhashini_ok = False
                if _bhashini_configured():
                    if not _WHISPER_AVAILABLE:
                        raise RuntimeError(
                            "No STT backend available (Bhashini failed and Whisper is not installed)"
                        ) from exc
                    return await _whisper_stt(audio_bytes, lang)
                from all_India_voice import speech_to_text_mock
                return await speech_to_text_mock(audio_bytes, lang)

        if not _bhashini_configured():
            from all_India_voice import speech_to_text_mock
            return await speech_to_text_mock(audio_bytes, lang)

        if not _WHISPER_AVAILABLE:
            raise RuntimeError(
                "No STT backend available (Bhashini not configured and Whisper is not installed)"
            )
        return await _whisper_stt(audio_bytes, lang)

    # ------------------------------------------------------------------
    # TTS
    # ------------------------------------------------------------------

    async def text_to_speech(
        self,
        text: str,
        lang_code: str = "hi",
    ) -> bytes:
        """
        Convert text to speech audio (MP3 / WAV bytes).

        Tries Bhashini first; falls back to gTTS or mock when unconfigured.
        """
        text = (text or "").strip()
        if not text:
            return b""

        lang = normalize_lang_code(lang_code)

        if await self._use_bhashini():
            try:
                return await _bhashini_tts(text, lang)
            except Exception as exc:
                logger.warning("Bhashini TTS failed (%s) – falling back to gTTS", exc)
                self._bhashini_ok = False

        if not _bhashini_configured():
            if not _GTTS_AVAILABLE:
                from all_India_voice import text_to_speech_mock
                return await text_to_speech_mock(text, lang)
            try:
                return await _gtts_tts(text, lang)
            except Exception:
                from all_India_voice import text_to_speech_mock
                return await text_to_speech_mock(text, lang)

        if not _GTTS_AVAILABLE:
            raise RuntimeError(
                "No TTS backend available (Bhashini not configured and gTTS is not installed)"
            )
        return await _gtts_tts(text, lang)

    # ------------------------------------------------------------------
    # Convenience: force a specific backend (useful for tests)
    # ------------------------------------------------------------------

    async def stt_bhashini_only(self, audio_bytes: bytes, lang_code: str) -> str:
        return await _bhashini_stt(audio_bytes, lang_code)

    async def stt_whisper_only(self, audio_bytes: bytes, lang_code: str) -> str:
        return await _whisper_stt(audio_bytes, lang_code)

    async def tts_bhashini_only(self, text: str, lang_code: str) -> bytes:
        return await _bhashini_tts(text, lang_code)

    async def tts_gtts_only(self, text: str, lang_code: str) -> bytes:
        return await _gtts_tts(text, lang_code)


# ---------------------------------------------------------------------------
# Module-level singleton (FastAPI dependency friendly)
# ---------------------------------------------------------------------------

_default_service: VoiceService | None = None


def get_voice_service() -> VoiceService:
    global _default_service
    if _default_service is None:
        _default_service = VoiceService(prefer_bhashini=True)
    return _default_service


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def demo() -> None:
        svc = get_voice_service()
        print("Bhashini configured :", _bhashini_configured())
        print("Whisper available   :", _WHISPER_AVAILABLE)
        print("gTTS available      :", _GTTS_AVAILABLE)

        # TTS round-trip (will use whatever backend is reachable)
        print("\nSynthesising Hindi speech …")
        audio = await svc.text_to_speech("नमस्ते, आज का मौसम कैसा है?", "hi")
        print(f"  → {len(audio)} bytes of audio")

        # STT with silent / dummy audio (Whisper will return empty or noise)
        print("\nTranscribing dummy audio …")
        try:
            text = await svc.speech_to_text(b"\x00" * 32000, "hi")
            print(f"  → '{text}'")
        except Exception as exc:
            print(f"  → (expected failure on silence) {exc}")

    asyncio.run(demo())