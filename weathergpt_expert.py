"""
weathergpt_expert.py — Unified WeatherGPT AI Expert
====================================================

A single agent that handles ALL AI interactions:
  • Text chat with conversation memory
  • Voice chat (ASR → chat → TTS)
  • Image / PDF / CSV analysis
  • Live weather context via Open-Meteo
  • Multi-language support (22 Indian languages)
  • Persona-aware responses (farmer, fisherman, urban commuter)

Replaces the fragmented weathergpt_agent.py + AI_engine.py split.
Uses Google Gemini (via LangChain) as the primary LLM.
Falls back to deterministic templates when offline.

Dependencies
------------
Required:
  - google-genai / langchain-google-genai
  - weather_service.py
  - voice_service.py
  - language_manager.py

Optional:
  - anthropic (for Claude fallback mode)
  - openai-whisper (for offline STT)
  - gtts (for offline TTS)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from dotenv import load_dotenv

# Language utilities
from language_manager import (
    normalize_lang_code,
    prepare_for_nlu,
    translate_to_native,
)

# Weather data
from weather_service import WeatherService, get_weather_service

load_dotenv()

logger = logging.getLogger("weathergpt.expert")

# ---------------------------------------------------------------------------
# Optional imports with graceful fallback
# ---------------------------------------------------------------------------

# Core LLM stack
_LLM_AVAILABLE = False
try:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_google_genai import ChatGoogleGenerativeAI
    _LLM_AVAILABLE = True
except ImportError:
    logger.warning("LangChain/Gemini not available – expert will use fallback mode")

# Voice stack
_VOICE_AVAILABLE = False
try:
    from voice_service import get_voice_service
    _VOICE_AVAILABLE = True
except ImportError:
    logger.warning("voice_service not available – voice features disabled")

VALID_PERSONAS = ("farmer", "fisherman", "urban_commuter", "general")
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
MAX_TOKENS = int(os.getenv("EXPERT_MAX_TOKENS", "2048"))
TEMPERATURE = float(os.getenv("EXPERT_TEMPERATURE", "0.4"))

# ---------------------------------------------------------------------------
# Persona system prompts
# ---------------------------------------------------------------------------

_PERSONA_PROMPTS = {
    "farmer": (
        "You are WeatherGPT's agriculture specialist for Indian farmers. "
        "ALWAYS reply in the user's requested language. "
        "Focus on: rainfall timing and amount, soil moisture, irrigation windows, "
        "spraying/fertilizer application conditions, heat/cold stress on crops, "
        "pest/disease risk from weather, and harvest planning. "
        "Use simple, practical language that farmers understand. "
        "Example topics: 'Should I irrigate my wheat today?', 'Will rain damage my crops?'"
    ),
    "fisherman": (
        "You are WeatherGPT's marine specialist for fishermen and coastal communities. "
        "ALWAYS reply in the user's requested language. "
        "Focus on: wave height, swell direction/period, wind gusts, "
        "sea surface temperature, storm risk, cyclone warnings, and safe fishing windows. "
        "Prioritize safety warnings for coastal operations. "
        "Example topics: 'Is it safe to go fishing today?', 'When will the storm hit?'"
    ),
    "urban_commuter": (
        "You are WeatherGPT's urban weather assistant for city dwellers. "
        "ALWAYS reply in the user's requested language. "
        "Focus on: rain timing for commute planning, heat/UV exposure, "
        "air quality, flooding risk in urban areas, and travel advisories. "
        "Keep it concise and actionable. "
        "Example topics: 'Will it rain during my commute?', 'Should I carry an umbrella?'"
    ),
    "general": (
        "You are WeatherGPT, a friendly meteorological advisor for everyone. "
        "ALWAYS reply in the user's requested language. "
        "Give clear, accurate, safety-first weather advice for India. "
        "Never invent data – if information is missing, say so."
    ),
}

# ---------------------------------------------------------------------------
# Multilingual fallback responses (when LLM is unavailable)
# ---------------------------------------------------------------------------

_FALLBACK_RESPONSES = {
    "en": (
        "Based on the weather data:\n{weather_context}\n\n"
        "For your query about {query}: "
        "Please check official IMD/NDMA sources for the latest warnings. "
        "Stay safe and follow local authority guidance."
    ),
    "hi": (
        "मौसम डेटा के आधार पर:\n{weather_context}\n\n"
        "आपके प्रश्न के बारे में: "
        "कृपया नवीनतम चेतावनियों के लिए आधिकारिक IMD/NDMA स्रोतों की जांच करें। "
        "सुरक्षित रहें और स्थानीय अधिकारियों के मार्गदर्शन का पालन करें।"
    ),
    "bn": (
        "আবহাওয়া ডেটার ভিত্তিতে:\n{weather_context}\n\n"
        "আপনার প্রশ্নের বিষয়ে: "
        "সর্বশেষ সতর্কতার জন্য আনুষ্ঠানিক IMD/NDMA সূত্র পরীক্ষা করুন। "
        "নিরাপদ থাকুন এবং স্থানীয় কর্তৃপক্ষের নির্দেশিকা অনুসরণ করুন।"
    ),
    "ta": (
        "வானிலை தரவின் அடிப்படையில்:\n{weather_context}\n\n"
        "உங்கள் கேள்விக்கு: "
        "அதிகரிப்புக்கான அதிகாரப்பூர்வ IMD/NDMA மூலங்களை சரிபார்க்கவும். "
        "பாதுகாப்பாக இருங்கள் மற்றும் உள்ளூர் அதிகாரிகளின் வழிநடத்தையை பின்பற்றவும்."
    ),
    "te": (
        "వాతావరణ డేటా ఆధారంగా:\n{weather_context}\n\n"
        "మీ ప్రశ్నకు: "
        "తాజా ఎచ్చరికల కోసం అధికారిక IMD/NDMA మూలాలను తనిఖీ చేయండి. "
        "సురక్షితంగా ఉండండి మరియు స్థానిక అధికారుల మార్గదర్శకాన్ని అనుసరించండి."
    ),
}

# ---------------------------------------------------------------------------
# WeatherGPT Expert Agent
# ---------------------------------------------------------------------------


class WeatherGPTExpert:
    """
    Unified AI expert that handles text chat, voice chat, and file analysis
    with live weather context and multi-language support.
    """

    def __init__(
        self,
        api_key: str | None = None,
        weather_service: WeatherService | None = None,
        default_persona: str = "general",
        default_language: str = "en",
    ):
        self._svc = weather_service or get_weather_service()
        self._voice_svc = get_voice_service() if _VOICE_AVAILABLE else None
        self._default_persona = default_persona if default_persona in VALID_PERSONAS else "general"
        self._default_language = normalize_lang_code(default_language)
        self._llm = None
        self._prompt = None

        if _LLM_AVAILABLE:
            self._init_llm(api_key)

    def _init_llm(self, api_key: str | None = None) -> None:
        """Initialize Gemini LLM if credentials are available."""
        key = api_key or (
            os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_GENERATIVE_AI_API_KEY")
        )
        if not key or key.strip() in ("your_gemini_api_key_here", "YOUR_GEMINI_API_KEY_HERE", ""):
            logger.warning(
                "No valid Gemini API key found – expert running in fallback mode. "
                "Set GOOGLE_API_KEY in .env or environment variables. "
                "Get a free key at https://aistudio.google.com/app/apikey"
            )
            return

        try:
            self._llm = ChatGoogleGenerativeAI(
                model=DEFAULT_MODEL,
                google_api_key=key,
                temperature=TEMPERATURE,
                max_output_tokens=MAX_TOKENS,
            )
            logger.info("Gemini LLM initialized: %s", DEFAULT_MODEL)
        except Exception as exc:
            logger.error("Failed to initialize Gemini LLM: %s", exc)

    # ─────────────────────────────────────────────────────────────────────
    # Public API — Text Chat
    # ─────────────────────────────────────────────────────────────────────

    async def chat(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        persona: str | None = None,
        language: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        location_name: str | None = None,
    ) -> dict[str, Any]:
        """
        One text chat turn with the weather expert.

        Parameters
        ----------
        message : str
            User's text message
        history : list[dict], optional
            Conversation history as [{"role": "user", "content": "..."}, ...]
        persona : str, optional
            One of: farmer, fisherman, urban_commuter, general
        language : str, optional
            Language code (e.g. "hi", "bn", "ta", "en")
        latitude, longitude : float, optional
            Location for weather context
        location_name : str, optional
            Human-readable location name

        Returns
        -------
        dict with keys:
            reply (str): Expert's response
            history (list[dict]): Updated conversation history
            language (str): Detected/used language
            weather_available (bool): Whether live weather data was used
        """
        persona = persona or self._default_persona
        language = normalize_lang_code(language or self._default_language)
        history = list(history or [])

        # Detect language from message if not specified
        detected_lang = self._detect_language(message, language)

        # Build weather context
        weather_ctx, weather_avail = await self._get_weather_context(
            latitude, longitude, location_name
        )

        # Generate reply
        if self._llm is not None:
            reply = await self._generate_llm_reply(
                message=message,
                persona=persona,
                language=detected_lang,
                weather_context=weather_ctx,
                history=history,
            )
        else:
            reply = self._generate_fallback_reply(
                message=message,
                persona=persona,
                language=detected_lang,
                weather_context=weather_ctx,
            )

        # Translate reply to target language if needed
        if detected_lang != "english":
            if not _LLM_AVAILABLE or "Offline advisory" in reply:
                reply = self._translate_fallback(reply, detected_lang, message, weather_ctx)
            else:
                translated = translate_to_native(reply, detected_lang)
                if translated and not translated.startswith("["):
                    reply = translated

        updated_history = history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": reply},
        ]

        return {
            "reply": reply,
            "history": updated_history,
            "language": detected_lang,
            "weather_available": weather_avail,
            "persona": persona,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Public API — Streaming Chat
    # ─────────────────────────────────────────────────────────────────────

    async def chat_stream(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        persona: str | None = None,
        language: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        location_name: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming version of chat(). Yields token chunks for real-time display.
        """
        result = await self.chat(
            message=message,
            history=history,
            persona=persona,
            language=language,
            latitude=latitude,
            longitude=longitude,
            location_name=location_name,
        )
        reply = result["reply"]

        # Stream in chunks for smooth UI
        chunk_size = 30
        for i in range(0, len(reply), chunk_size):
            yield {"type": "token", "text": reply[i : i + chunk_size]}
            await asyncio.sleep(0.02)  # Small delay for smooth streaming effect

        yield {"type": "done", **result}

    # ─────────────────────────────────────────────────────────────────────
    # Public API — Voice Chat
    # ─────────────────────────────────────────────────────────────────────

    async def voice_chat(
        self,
        audio_bytes: bytes,
        audio_format: str = "wav",
        history: list[dict[str, str]] | None = None,
        persona: str | None = None,
        language: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        location_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Complete voice chat pipeline:
        audio → ASR → text chat → TTS audio response

        Returns
        -------
        dict with keys:
            transcript (str): What the user said
            reply (str): Expert's text response
            reply_audio (bytes): TTS audio response (if available)
            history (list[dict]): Updated conversation history
            language (str): Detected language
        """
        if not _VOICE_AVAILABLE or self._voice_svc is None:
            return {
                "error": "Voice service unavailable",
                "transcript": "",
                "reply": "Voice features are currently unavailable. Please use text chat.",
                "reply_audio": b"",
                "history": history or [],
                "language": language or "en",
            }

        # Step 1: Speech-to-Text
        try:
            transcript = await self._voice_svc.speech_to_text(audio_bytes, language or "en")
            if not transcript:
                return {
                    "error": "Could not understand audio",
                    "transcript": "",
                    "reply": "I couldn't understand what you said. Please try again.",
                    "reply_audio": b"",
                    "history": history or [],
                    "language": language or "en",
                }
        except Exception as exc:
            logger.error("ASR failed: %s", exc)
            return {
                "error": f"ASR failed: {exc}",
                "transcript": "",
                "reply": "Speech recognition failed. Please try typing your question.",
                "reply_audio": b"",
                "history": history or [],
                "language": language or "en",
            }

        # Step 2: Text chat
        chat_result = await self.chat(
            message=transcript,
            history=history,
            persona=persona,
            language=language,
            latitude=latitude,
            longitude=longitude,
            location_name=location_name,
        )

        # Step 3: Text-to-Speech for the reply
        reply_audio = b""
        try:
            reply_audio = await self._voice_svc.text_to_speech(
                chat_result["reply"],
                chat_result["language"],
            )
        except Exception as exc:
            logger.warning("TTS failed: %s", exc)

        return {
            "transcript": transcript,
            "reply": chat_result["reply"],
            "reply_audio": reply_audio,
            "history": chat_result["history"],
            "language": chat_result["language"],
            "persona": chat_result["persona"],
            "weather_available": chat_result["weather_available"],
        }

    # ─────────────────────────────────────────────────────────────────────
    # Public API — File / Image Analysis
    # ─────────────────────────────────────────────────────────────────────

    async def analyze_file(
        self,
        file_bytes: bytes,
        content_type: str,
        filename: str | None = None,
        prompt: str | None = None,
        persona: str | None = None,
        language: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """
        Analyze uploaded files: images (crop photos, radar), PDFs (reports),
        CSVs (weather data logs).

        Returns
        -------
        dict with keys:
            reply (str): Analysis and advice
            history (list[dict]): Updated conversation history
            language (str): Response language
        """
        persona = persona or self._default_persona
        language = normalize_lang_code(language or self._default_language)
        history = list(history or [])

        # Build weather context
        weather_ctx, weather_avail = await self._get_weather_context(
            latitude, longitude, None
        )

        # Build media block for Gemini
        media_block, default_prompt = self._build_media_block(file_bytes, content_type, filename)
        prompt_text = prompt or default_prompt

        # Generate analysis
        if self._llm is not None:
            reply = await self._generate_vision_reply(
                media_block=media_block,
                prompt_text=prompt_text,
                persona=persona,
                language=language,
                weather_context=weather_ctx,
            )
        else:
            reply = self._generate_fallback_file_reply(
                filename=filename or "file",
                content_type=content_type,
                persona=persona,
                language=language,
            )

        updated_history = history + [
            {"role": "user", "content": f"[Uploaded: {filename or 'file'}] {prompt_text}"},
            {"role": "assistant", "content": reply},
        ]

        return {
            "reply": reply,
            "history": updated_history,
            "language": language,
            "weather_available": weather_avail,
            "persona": persona,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Weather Context
    # ─────────────────────────────────────────────────────────────────────

    async def _get_weather_context(
        self,
        lat: float | None,
        lon: float | None,
        location_name: str | None,
    ) -> tuple[str, bool]:
        """Fetch live weather context. Returns (context_text, success_bool)."""
        try:
            # Try to resolve location if coordinates not provided
            if lat is None or lon is None:
                if location_name:
                    geocode_results = await self._svc.geocode(location_name, count=1)
                    if geocode_results:
                        lat = geocode_results[0]["latitude"]
                        lon = geocode_results[0]["longitude"]
                        location_name = geocode_results[0]["name"]
                    else:
                        return "(Location not found – weather context unavailable)", False
                else:
                    # Use default location
                    lat, lon = 28.61, 77.21  # New Delhi
                    location_name = "New Delhi"

            # Fetch current weather and forecast
            current = await self._svc.get_current_weather(lat, lon)
            forecast = await self._svc.get_forecast(lat, lon, days=3)

            lines: list[str] = []
            if location_name:
                lines.append(f"Location: {location_name}")
            lines.append(f"Coordinates: {lat:.3f}°N, {lon:.3f}°E")

            # Current conditions - handle both dict and model responses
            if hasattr(current, 'temperature'):
                # Pydantic model
                temp = current.temperature
                humidity = current.relative_humidity
                wind = current.wind_speed
                wind_dir = current.wind_direction
                precip = current.precipitation
                code = current.weather_code
            else:
                # Dict response
                temp = current.get("temperature_2m") or current.get("temperature")
                humidity = current.get("relative_humidity_2m") or current.get("relative_humidity")
                wind = current.get("wind_speed_10m") or current.get("wind_speed")
                wind_dir = current.get("wind_direction_10m") or current.get("wind_direction")
                precip = current.get("precipitation")
                code = current.get("weather_code")

            lines.append(
                f"Current: {temp if temp is not None else 'N/A'}°C, "
                f"Humidity {humidity if humidity is not None else 'N/A'}%, "
                f"Wind {wind if wind is not None else 'N/A'} km/h ({self._wind_direction_name(wind_dir)}), "
                f"Precipitation {precip if precip is not None else 'N/A'} mm, "
                f"Weather code: {code if code is not None else 'N/A'}"
            )

            # 3-day forecast - handle both dict and model responses
            daily = forecast.daily if hasattr(forecast, 'daily') else forecast.get("daily", [])
            if daily:
                lines.append("3-day forecast:")
                for day in daily[:3]:
                    if hasattr(day, 'date'):
                        # Pydantic model
                        date = day.date
                        tmax = day.temperature_max
                        tmin = day.temperature_min
                        precip_prob = day.precipitation_probability_max
                        precip_sum = day.precipitation_sum
                    else:
                        # Dict
                        date = day.get("date", "N/A")
                        tmax = day.get("temperature_max")
                        tmin = day.get("temperature_min")
                        precip_prob = day.get("precipitation_probability_max")
                        precip_sum = day.get("precipitation_sum")

                    lines.append(
                        f"  {date}: {tmin if tmin is not None else 'N/A'}°C to {tmax if tmax is not None else 'N/A'}°C, "
                        f"Rain {precip_sum if precip_sum is not None else 'N/A'}mm (prob {precip_prob if precip_prob is not None else 'N/A'}%)"
                    )

            return "\n".join(lines), True

        except Exception as exc:
            logger.error("Weather context fetch failed: %s", exc)
            return f"(Weather data unavailable: {exc})", False

    # ─────────────────────────────────────────────────────────────────────
    # LLM-Powered Reply Generation
    # ─────────────────────────────────────────────────────────────────────

    async def _generate_llm_reply(
        self,
        message: str,
        persona: str,
        language: str,
        weather_context: str,
        history: list[dict[str, str]],
    ) -> str:
        """Generate a reply using Gemini LLM with weather context."""
        if self._llm is None:
            return self._generate_fallback_reply(message, persona, language, weather_context)

        try:
            # Build system prompt
            system_text = _PERSONA_PROMPTS.get(persona, _PERSONA_PROMPTS["general"])
            if language != "english":
                system_text += f" Reply in {language}."

            # Build conversation messages
            messages = []
            # Add system prompt as first message
            messages.append({"role": "system", "content": system_text})

            # Add weather context
            messages.append({
                "role": "user",
                "content": f"[Weather Data for your location]\n{weather_context}"
            })
            messages.append({
                "role": "assistant",
                "content": "I have the current weather data. What would you like to know?"
            })

            # Add conversation history
            for turn in history[-6:]:  # Keep last 6 turns for context window
                messages.append(turn)

            # Add current message
            messages.append({"role": "user", "content": message})

            # Create prompt template
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_text),
                ("human", "{input}"),
            ])

            # Build context string
            context = f"Weather Context:\n{weather_context}\n\nConversation:\n"
            for turn in history[-4:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                context += f"{role.capitalize()}: {content}\n"
            context += f"User: {message}\nAssistant:"

            chain = prompt | self._llm | StrOutputParser()
            reply = await chain.ainvoke({"input": context})
            return reply.strip()

        except Exception as exc:
            logger.error("LLM generation failed: %s", exc)
            return self._generate_fallback_reply(message, persona, language, weather_context)

    async def _generate_vision_reply(
        self,
        media_block: dict[str, Any],
        prompt_text: str,
        persona: str,
        language: str,
        weather_context: str,
    ) -> str:
        """Generate reply for image/file analysis using Gemini Vision."""
        if self._llm is None:
            return self._generate_fallback_file_reply(
                filename="uploaded file",
                content_type="unknown",
                persona=persona,
                language=language,
            )

        try:
            system_text = _PERSONA_PROMPTS.get(persona, _PERSONA_PROMPTS["general"])
            if language != "english":
                system_text += f" Reply in {language}."

            # Build multimodal message
            content_parts = [
                media_block,
                {
                    "type": "text",
                    "text": (
                        f"{system_text}\n\n"
                        f"Current weather context:\n{weather_context}\n\n"
                        f"User request: {prompt_text}\n\n"
                        f"Analyze this file/image in the context of weather and provide actionable advice."
                    ),
                },
            ]

            # Use Gemini directly for multimodal
            import google.generativeai as genai
            api_key = (
                os.getenv("GOOGLE_API_KEY")
                or os.getenv("GEMINI_API_KEY")
                or os.getenv("GOOGLE_GENERATIVE_AI_API_KEY")
            )
            if not api_key:
                return self._generate_fallback_file_reply(
                    filename="uploaded file",
                    content_type="image",
                    persona=persona,
                    language=language,
                )

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(DEFAULT_MODEL)
            response = model.generate_content(content_parts)
            return response.text.strip()

        except Exception as exc:
            logger.error("Vision analysis failed: %s", exc)
            return self._generate_fallback_file_reply(
                filename="uploaded file",
                content_type="image",
                persona=persona,
                language=language,
            )

    # ─────────────────────────────────────────────────────────────────────
    # Fallback Replies (when LLM unavailable)
    # ─────────────────────────────────────────────────────────────────────

    def _generate_fallback_reply(
        self,
        message: str,
        persona: str,
        language: str,
        weather_context: str,
    ) -> str:
        """Generate a deterministic fallback reply when LLM is unavailable."""
        template = _FALLBACK_RESPONSES.get(language, _FALLBACK_RESPONSES["en"])
        return template.format(weather_context=weather_context, query=message)

    def _generate_fallback_file_reply(
        self,
        filename: str,
        content_type: str,
        persona: str,
        language: str,
    ) -> str:
        """Generate fallback for file analysis when vision is unavailable."""
        if language == "en":
            return (
                f"I received your file '{filename}' ({content_type}). "
                f"However, I'm currently unable to analyze files in detail. "
                f"Please describe what you'd like to know, and I'll help based on "
                f"your description and any available weather data."
            )
        return (
            f"Received file '{filename}' ({content_type}). "
            f"Detailed file analysis is temporarily unavailable. "
            f"Please describe your question in text."
        )

    def _translate_fallback(self, reply: str, target_lang: str, query: str, weather_ctx: str) -> str:
        """Translate fallback response to target language."""
        template = _FALLBACK_RESPONSES.get(target_lang, _FALLBACK_RESPONSES["en"])
        return template.format(weather_context=weather_ctx, query=query)

    # ─────────────────────────────────────────────────────────────────────
    # Language Detection
    # ─────────────────────────────────────────────────────────────────────

    def _detect_language(self, text: str, default: str) -> str:
        """Detect language from text, falling back to default."""
        try:
            nlu = prepare_for_nlu(text, default)
            detected = nlu.get("language", default)
            return normalize_lang_code(detected)
        except Exception:
            return normalize_lang_code(default)

    # ─────────────────────────────────────────────────────────────────────
    # Media Block Builder
    # ─────────────────────────────────────────────────────────────────────

    def _build_media_block(
        self,
        file_bytes: bytes,
        content_type: str,
        filename: str | None,
    ) -> tuple[dict[str, Any], str]:
        """
        Build a media block for Gemini Vision API.
        Returns (media_block, default_prompt).
        """
        b64_data = base64.standard_b64encode(file_bytes).decode("utf-8")

        if content_type.startswith("image/"):
            block = {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": content_type,
                    "data": b64_data,
                },
            }
            prompt = (
                "Analyze this image. If it shows crops/plants, identify any visible "
                "stress symptoms (fungal, pest, drought, waterlogging, nutrient deficiency). "
                "If it's a weather radar/satellite image, describe the weather pattern. "
                "Provide practical advice based on what you see."
            )
            return block, prompt

        if content_type == "application/pdf":
            block = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": b64_data,
                },
            }
            prompt = (
                "Analyze this document. Summarize key information and provide "
                "actionable insights related to weather or agriculture."
            )
            return block, prompt

        if content_type in ("text/csv", "text/plain") or (filename and filename.lower().endswith(".csv")):
            try:
                csv_text = file_bytes.decode("utf-8", errors="replace")[:10000]
                block = {"type": "text", "text": f"CSV Data:\n{csv_text}"}
                prompt = "Analyze this data and summarize key trends or anomalies."
                return block, prompt
            except Exception as exc:
                logger.warning("CSV decode failed: %s", exc)

        raise ValueError(
            f"Unsupported file type: {content_type}. "
            "Supported: image/*, application/pdf, text/csv"
        )

    # ─────────────────────────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _wind_direction_name(degrees: float | None) -> str:
        """Convert wind direction degrees to compass name."""
        if degrees is None:
            return "unknown"
        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        idx = int((degrees + 22.5) / 45) % 8
        return dirs[idx]

    # ─────────────────────────────────────────────────────────────────────
    # Health Check
    # ─────────────────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return agent status for diagnostics."""
        return {
            "llm_available": self._llm is not None,
            "voice_available": _VOICE_AVAILABLE and self._voice_svc is not None,
            "weather_service_ready": self._svc is not None,
            "default_persona": self._default_persona,
            "default_language": self._default_language,
            "model": DEFAULT_MODEL if self._llm else "fallback",
        }


# ---------------------------------------------------------------------------
# Convenience singleton
# ---------------------------------------------------------------------------

_default_agent: WeatherGPTExpert | None = None


def get_expert(**kwargs) -> WeatherGPTExpert:
    """Get or create the default expert instance."""
    global _default_agent
    if _default_agent is None:
        _default_agent = WeatherGPTExpert(**kwargs)
    return _default_agent
