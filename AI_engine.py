"""
ai_engine.py

Core AI Engine for WeatherGPT.

Combines:
  - language_manager.py  (code-mixed detection, translation)
  - weather_service.py   (real-time / forecast context)
  - LangChain + Google Gemini (advisory generation)

Pipeline:
  1. Detect / clean code-mixed input
  2. Translate query → English
  3. Fetch & inject weather context
  4. Run LLM to generate advisory
  5. Translate advisory → target Indic language
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from language_manager import (
    normalize_lang_code,
    prepare_for_nlu,
    process_code_mixed_script,
    translate_to_english,
    translate_to_native,
    get_bhashini_code,
)
from weather_service import WeatherService, get_weather_service

load_dotenv()

# ---------------------------------------------------------------------------
# Optional LangChain / Gemini imports (graceful degradation)
# ---------------------------------------------------------------------------

_LLM_AVAILABLE = False
_llm = None
_prompt = None

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    _LLM_AVAILABLE = True
except ImportError:
    pass


def _init_llm() -> None:
    """Initialise Gemini via LangChain if credentials and package are present."""
    global _llm, _prompt

    if not _LLM_AVAILABLE:
        return

    api_key = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_GENERATIVE_AI_API_KEY")
    )
    if not api_key:
        return

    _llm = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        google_api_key=api_key,
        temperature=0.4,
        max_output_tokens=1024,
    )

    _prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are WeatherGPT, an expert meteorological advisor for India. "
                    "You give clear, actionable, safety-first weather advice for farmers, "
                    "travellers, coastal communities and the general public. "
                    "Use the supplied weather context. "
                    "Reply in concise, natural English. "
                    "If the data indicates danger (heavy rain, strong wind, heat wave, etc.) "
                    "explicitly state the risk level and recommended actions. "
                    "Never invent numeric values that are not present in the context."
                ),
            ),
            (
                "human",
                (
                    "User query (English): {query}\n\n"
                    "Current weather context:\n{weather_context}\n\n"
                    "Generate a helpful weather advisory."
                ),
            ),
        ]
    )


# Initialise on import
_init_llm()


# ---------------------------------------------------------------------------
# Weather context builder
# ---------------------------------------------------------------------------

async def _build_weather_context(
    lat: float,
    lon: float,
    svc: WeatherService,
) -> str:
    """Fetch current + short-range forecast and format as plain text for the LLM."""
    try:
        current = await svc.get_current_weather(lat, lon)
        forecast = await svc.get_forecast(lat, lon, days=3)
    except Exception as exc:
        return f"(Weather data temporarily unavailable: {exc})"

    lines: List[str] = []
    lines.append(
        f"Location: {lat:.3f}, {lon:.3f} | Timezone: {current.get('timezone', 'N/A')}"
    )
    lines.append(
        f"Current: {current.get('temperature')}°C, "
        f"Humidity {current.get('relative_humidity')}%, "
        f"Wind {current.get('wind_speed')} km/h from {current.get('wind_direction')}°, "
        f"Precip {current.get('precipitation')} mm, "
        f"Pressure {current.get('pressure')} hPa, "
        f"Weather code {current.get('weather_code')}"
    )

    if forecast.daily:
        lines.append("Next 3 days:")
        for day in forecast.daily[:3]:
            lines.append(
                f"  {day.date}: max {day.temperature_max}°C / min {day.temperature_min}°C, "
                f"precip {day.precipitation_sum} mm "
                f"(prob {day.precipitation_probability_max}%), "
                f"code {day.weather_code}"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM advisory generation
# ---------------------------------------------------------------------------

async def _generate_advisory_english(query: str, weather_context: str) -> str:
    """
    Run the Gemini / LangChain chain.
    Falls back to a deterministic template when the LLM is unavailable.
    """
    if _llm is not None and _prompt is not None:
        try:
            chain = _prompt | _llm | StrOutputParser()
            result = await chain.ainvoke(
                {"query": query, "weather_context": weather_context}
            )
            return result.strip()
        except Exception as exc:
            fallback_reason = str(exc)
    else:
        fallback_reason = "LLM not configured (missing package or API key)"

    return (
        f"[Offline advisory – {fallback_reason}]\n"
        f"Based on the available data:\n{weather_context}\n\n"
        f"Regarding your query “{query}”: "
        "Please check official IMD / NDMA sources for the latest warnings. "
        "Stay hydrated, avoid unnecessary travel during heavy rain or strong winds, "
        "and follow local authority guidance."
    )


# ---------------------------------------------------------------------------
# Multilingual fallback advisories (used when LLM is unavailable)
# ---------------------------------------------------------------------------

_MULTILINGUAL_FALLBACKS = {
    "hindi": "आज का मौसम सामान्य रहेगा। सुरक्षित रहें और आधिकारिक IMD/NDMA स्रोतों की जाँच करें।",
    "bengali": "আজকের আবহাওয়া সাধারণ থাকবে। নিরাপথাকান সুরক্ষিত থাকুন এবং সরকারি IMD/NDMA সূত্রগুলি পরীক্ষা করুন।",
    "tamil": "இன்று வானிலை சாதாரணமாக இருக்கும். பாதுகாக்கப்படுங்கள் மற்றும் அதிகரிப்பாக்கக் கூட்டங்கள் (IMD/NDMA) வழங்கும் தகவல்களைப் பரிசோதியுங்கள்.",
    "telugu": "ఈరేపు వాతావరణం సాధారణంగా ఉంటుంది. సురక్షితంగా ఉండండి మరియు IMD/NDMA సమాచారాన్ని సమీక్షించండి.",
    "marathi": "आज हवामान सामान्य असेल. सुरक्षित राहा आणि अधिकृत IMD/NDMA स्रोतांकडे लक्षात घ्या.",
    "gujarati": "આજે હવામાન સામાન્ય રહેશે. સુરક્ષિત રહો અને અધિકૃત IMD/NDMA સ્રોતોની તપાસણી કરો.",
    "kannada": "ಇಂದು ಆದರೆ ಸಾಮಾನ್ಯವಾಗಿರುತ್ತದೆ. ಸುರಕ್ಷಿತವಾಗಿರಿ ಮತ್ತು ಅಧಿಕೃತ IMD/NDMA ಮೂಲಗಳನ್ನು ಪರಿಶೀಲಿಸಿ.",
    "malayalam": "ഇന്ന് കാലാവസ്ഥ സാധാരനമാകും. സുരക്ഷിതമാകൂ മറ്റു അധികൃത IMD/NDMA മൂലങ്ങൾ പരിശോധിക്കുക.",
    "punjabi": "ਅੱਜ ਮੌਸਮ ਸਧਾਰਨ ਹੋਵੇਗਾ। ਸੁਰੱਖਿਅਤ ਰਹੋ ਅਤੇ ਅਧਿਕਾਰਤ IMD/NDMA ਸਰੋਤਾਂ ਦੀ ਜਾਂਚ ਕਰੋ।",
    "urdu": "آج موسم سادہ ہوگا۔ محفوظ رہیں اور ادائیگی IMD/NDMA کے مماثلات کی جانچ کریں۔",
    "odia": "ଆଜି ମୌସମ ସାଧାରଣ ରହିବ। ସୁରକ୍ଷିତ ଥାଅ ଏବଂ ଅଧିକାରିକ IMD/NDMA ଉତ୍ସଗୁଡ଼ିକୁ ଅନ୍ୱେଷଣ କର।",
    "assamese": "আজিৰ অসমীয়া মৌসম সাধাৰণ হব। নিৰাপদ থাকু আৰু অধিকাৰিক IMD/NDMA সোৱাৰো চৰিক্ষা কৰুন।",
    "nepali": "आज मौसम सामान्य हुनेछ। सुरक्षित रहनुहोस् र अधिकृत IMD/NDMA स्रोतहरू जाँच गर्नुहोस्।",
}


# ---------------------------------------------------------------------------
# Public high-level pipeline
# ---------------------------------------------------------------------------

async def generate_weather_advisory(
    user_text: str,
    source_lang: str,
    lat: float,
    lon: float,
    *,
    target_lang: Optional[str] = None,
    weather_svc: Optional[WeatherService] = None,
) -> Dict[str, Any]:
    """
    Full WeatherGPT pipeline.

    Steps
    -----
    1. Detect & clean code-mixed / Romanized input
    2. Translate query → English
    3. Inject live weather context
    4. Generate English advisory with Gemini
    5. Translate advisory → target Indic language

    Parameters
    ----------
    user_text : str
        Raw user utterance (any script / code-mixed).
    source_lang : str
        Language of the user (name, ISO, Bhashini or FLORES code).
    lat, lon : float
        Location for weather lookup.
    target_lang : str, optional
        Language for the final reply. Defaults to source_lang.
    weather_svc : WeatherService, optional
        Injected service instance (useful for testing).

    Returns
    -------
    dict with keys:
        original_text, cleaned_text, english_query,
        weather_context, english_advisory, native_advisory,
        source_lang, target_lang
    """
    svc = weather_svc or get_weather_service()
    src = normalize_lang_code(source_lang)
    tgt = normalize_lang_code(target_lang or source_lang)

    # ------------------------------------------------------------------
    # 1 + 2  Code-mixed handling & translation to English
    # ------------------------------------------------------------------
    nlu = prepare_for_nlu(user_text, src)
    cleaned = nlu["cleaned"]
    english_query = nlu["english"]

    # If the translation layer returned a placeholder marker, strip it for the LLM
    english_query = re.sub(r"^\[en←[^\]]+\]\s*", "", english_query).strip()
    if not english_query:
        english_query = cleaned or user_text

    # ------------------------------------------------------------------
    # 3  Weather context
    # ------------------------------------------------------------------
    weather_ctx = await _build_weather_context(lat, lon, svc)

    # ------------------------------------------------------------------
    # 4  LLM advisory (English)
    # ------------------------------------------------------------------
    english_advisory = await _generate_advisory_english(english_query, weather_ctx)

    # ------------------------------------------------------------------
    # 5  Translate back to target language
    # ------------------------------------------------------------------
    if tgt == "english":
        native_advisory = english_advisory
    else:
        native_advisory = translate_to_native(english_advisory, tgt)
        if native_advisory.startswith(f"[{tgt}←en]"):
            native_advisory = _MULTILINGUAL_FALLBACKS.get(tgt) or english_advisory
        else:
            native_advisory = re.sub(r"^\[[^\]]+←en\]\s*", "", native_advisory).strip()

    return {
        "original_text": user_text,
        "cleaned_text": cleaned,
        "english_query": english_query,
        "weather_context": weather_ctx,
        "english_advisory": english_advisory,
        "native_advisory": native_advisory,
        "source_lang": src,
        "target_lang": tgt,
        "bhashini_source": get_bhashini_code(src),
        "bhashini_target": get_bhashini_code(tgt),
    }


# ---------------------------------------------------------------------------
# Convenience synchronous wrapper
# ---------------------------------------------------------------------------

def generate_weather_advisory_sync(
    user_text: str,
    source_lang: str,
    lat: float,
    lon: float,
    **kwargs,
) -> Dict[str, Any]:
    """Blocking helper for non-async callers."""
    import asyncio
    return asyncio.run(
        generate_weather_advisory(user_text, source_lang, lat, lon, **kwargs)
    )


# ---------------------------------------------------------------------------
# Self-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def demo() -> None:
        # Delhi coordinates
        lat, lon = 28.61, 77.21

        samples = [
            ("Aaj mausam kaisa rahega?", "hindi"),
            ("Ami ajke abhowa kemon janbo", "bengali"),
            ("Innikku mazhai varuma?", "tamil"),
            ("Will it rain heavily in the next two days?", "english"),
        ]

        for text, lang in samples:
            print("=" * 60)
            print(f"Input ({lang}): {text}")
            result = await generate_weather_advisory(text, lang, lat, lon)
            print(f"English query : {result['english_query']}")
            print(f"Advisory (en) : {result['english_advisory'][:200]}…")
            print(f"Advisory ({result['target_lang']}): {result['native_advisory'][:200]}…")
            print()

    asyncio.run(demo())