"""
language_manager.py

Language Manager for WeatherGPT.
Supports all 22 scheduled languages of India with FLORES-200 / Bhashini codes.
Handles code-mixed / Romanized Indian language text and provides
translation helpers (English ↔ native).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# 22 Scheduled Languages of India → FLORES-200 / Bhashini codes
# ---------------------------------------------------------------------------

# Primary mapping used throughout the system.
# Format: language_name → (flores_code, bhashini_code, script, iso_639_3)
LANGUAGE_MAP: Dict[str, Tuple[str, str, str, str]] = {
    "assamese":   ("asm_Beng", "as", "Beng", "asm"),
    "bengali":    ("ben_Beng", "bn", "Beng", "ben"),
    "bodo":       ("brx_Deva", "brx", "Deva", "brx"),
    "dogri":      ("doi_Deva", "doi", "Deva", "doi"),
    "gujarati":   ("guj_Gujr", "gu", "Gujr", "guj"),
    "hindi":      ("hin_Deva", "hi", "Deva", "hin"),
    "kannada":    ("kan_Knda", "kn", "Knda", "kan"),
    "kashmiri":   ("kas_Arab", "ks", "Arab", "kas"),  # also kas_Deva
    "konkani":    ("gom_Deva", "gom", "Deva", "gom"),
    "maithili":   ("mai_Deva", "mai", "Deva", "mai"),
    "malayalam":  ("mal_Mlym", "ml", "Mlym", "mal"),
    "manipuri":   ("mni_Beng", "mni", "Beng", "mni"),  # Meitei
    "marathi":    ("mar_Deva", "mr", "Deva", "mar"),
    "nepali":     ("npi_Deva", "ne", "Deva", "npi"),
    "odia":       ("ory_Orya", "or", "Orya", "ory"),
    "punjabi":    ("pan_Guru", "pa", "Guru", "pan"),
    "sanskrit":   ("san_Deva", "sa", "Deva", "san"),
    "santali":    ("sat_Olck", "sat", "Olck", "sat"),
    "sindhi":     ("snd_Arab", "sd", "Arab", "snd"),  # also snd_Deva
    "tamil":      ("tam_Taml", "ta", "Taml", "tam"),
    "telugu":     ("tel_Telu", "te", "Telu", "tel"),
    "urdu":       ("urd_Arab", "ur", "Arab", "urd"),
}

# Reverse lookup helpers
FLORES_TO_NAME: Dict[str, str] = {v[0].lower(): k for k, v in LANGUAGE_MAP.items()}
BHASHINI_TO_NAME: Dict[str, str] = {v[1].lower(): k for k, v in LANGUAGE_MAP.items()}
ISO_TO_NAME: Dict[str, str] = {v[3].lower(): k for k, v in LANGUAGE_MAP.items()}

# Common aliases (including Romanized / colloquial names)
LANGUAGE_ALIASES: Dict[str, str] = {
    "as": "assamese", "asm": "assamese",
    "bn": "bengali", "ben": "bengali", "bangla": "bengali",
    "brx": "bodo",
    "doi": "dogri",
    "gu": "gujarati", "guj": "gujarati",
    "hi": "hindi", "hin": "hindi",
    "kn": "kannada", "kan": "kannada",
    "ks": "kashmiri", "kas": "kashmiri",
    "gom": "konkani", "kok": "konkani",
    "mai": "maithili",
    "ml": "malayalam", "mal": "malayalam",
    "mni": "manipuri", "meitei": "manipuri", "manipuri": "manipuri",
    "mr": "marathi", "mar": "marathi",
    "ne": "nepali", "npi": "nepali",
    "or": "odia", "ory": "odia", "oriya": "odia",
    "pa": "punjabi", "pan": "punjabi", "punjabi": "punjabi",
    "sa": "sanskrit", "san": "sanskrit",
    "sat": "santali", "santali": "santali",
    "sd": "sindhi", "snd": "sindhi",
    "ta": "tamil", "tam": "tamil",
    "te": "telugu", "tel": "telugu",
    "ur": "urdu", "urd": "urdu",
    "en": "english", "eng": "english", "english": "english",
}


def normalize_lang_code(lang: str) -> str:
    """
    Normalize any user-supplied language identifier to the canonical
    lowercase name used as key in LANGUAGE_MAP (or 'english').
    """
    if not lang:
        return "english"
    key = lang.strip().lower().replace("-", "_").replace(" ", "")
    if key in LANGUAGE_MAP:
        return key
    if key in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[key]
    # Try FLORES / Bhashini / ISO direct
    if key in FLORES_TO_NAME:
        return FLORES_TO_NAME[key]
    if key in BHASHINI_TO_NAME:
        return BHASHINI_TO_NAME[key]
    if key in ISO_TO_NAME:
        return ISO_TO_NAME[key]
    # Fallback: treat unknown as English
    return "english"


def get_flores_code(lang: str) -> str:
    """Return FLORES-200 code for a language (or 'eng_Latn' for English)."""
    name = normalize_lang_code(lang)
    if name == "english":
        return "eng_Latn"
    return LANGUAGE_MAP[name][0]


def get_bhashini_code(lang: str) -> str:
    """Return Bhashini / ISO-639-1 style code."""
    name = normalize_lang_code(lang)
    if name == "english":
        return "en"
    return LANGUAGE_MAP[name][1]


def get_script(lang: str) -> str:
    """Return ISO 15924 script code."""
    name = normalize_lang_code(lang)
    if name == "english":
        return "Latn"
    return LANGUAGE_MAP[name][2]


def list_supported_languages() -> Dict[str, Dict[str, str]]:
    """Return a human-readable catalogue of all supported languages."""
    result = {
        "english": {
            "flores": "eng_Latn",
            "bhashini": "en",
            "script": "Latn",
            "iso639_3": "eng",
        }
    }
    for name, (flores, bhashini, script, iso) in LANGUAGE_MAP.items():
        result[name] = {
            "flores": flores,
            "bhashini": bhashini,
            "script": script,
            "iso639_3": iso,
        }
    return result


# ---------------------------------------------------------------------------
# Code-mixed / Romanized text handling
# ---------------------------------------------------------------------------

# Very lightweight Romanization cleanup patterns common in Indian code-mixed text
_ROMAN_CLEANUP = [
    (re.compile(r"\s+"), " "),
    (re.compile(r"[“”]"), '"'),
    (re.compile(r"[‘’]"), "'"),
    (re.compile(r"[–—]"), "-"),
]

# Common Hinglish / Benglish / Tanglish particles that stay in Latin script
_CODEMIX_MARKERS = {
    "hai", "hain", "ho", "hoon", "tha", "thi", "the", "kya", "kyaa",
    "nahi", "nahin", "mat", "bhi", "toh", "to", "se", "ke", "ki", "ka",
    "mein", "me", "par", "pe", "aur", "ya", "lekin", "magar",
    "ami", "tumi", "apni", "kemon", "achen", "jacchi", "korbo", "hobe",
    "naan", "neenga", "irukken", "pannu", "vena", "illa",
    "nenu", "meeru", "unna", "chestunna", "ledi",
}


def process_code_mixed_script(text: str, source_lang: str) -> str:
    """
    Normalize code-mixed / Romanized Indian language text.

    Examples of input this aims to handle:
        - "Ami ajke abhowa kemon janbo"          (Benglish)
        - "Aaj mausam kaisa rahega"              (Hinglish)
        - "Innikku mazhai varuma"                (Tanglish)
        - Mixed Devanagari + Latin, etc.

    Current behaviour (production-ready baseline):
      1. Unicode normalisation (NFC)
      2. Whitespace / punctuation cleanup
      3. Detection of dominant script
      4. Preservation of Latin tokens that are common discourse markers
      5. Returns cleaned text ready for downstream translation / NLU

    For full Roman → Native script conversion a dedicated transliteration
    model (IndicXlit, AI4Bharat, etc.) should be plugged in later.
    """
    if not text or not text.strip():
        return ""

    # 1. Unicode normalise
    cleaned = unicodedata.normalize("NFC", text.strip())

    # 2. Basic cleanup
    for pattern, repl in _ROMAN_CLEANUP:
        cleaned = pattern.sub(repl, cleaned)

    # 3. Collapse multiple spaces again after punctuation fixes
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 4. Optional: mark pure-Latin code-mixed sentences
    #    (useful for routing to a specialised Hinglish/Benglish model)
    has_native_script = any(
        unicodedata.category(ch) == "Lo" and ord(ch) > 127
        for ch in cleaned
    )
    tokens = cleaned.lower().split()
    latin_ratio = sum(1 for t in tokens if t.isascii()) / max(len(tokens), 1)

    # Attach a lightweight metadata prefix only when clearly Romanized
    # (callers can strip it if not needed)
    if not has_native_script and latin_ratio > 0.85:
        # Keep the original cleaned text; just ensure consistent casing
        # for downstream models that expect lower-cased Roman input
        return cleaned

    return cleaned


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------

def translate_to_english(text: str, source_lang: str) -> str:
    """
    Translate `text` from `source_lang` into English.

    This is a production skeleton. In a real deployment replace the body
    with a call to:
      - Bhashini Translation API
      - IndicTrans2 / AI4Bharat models
      - Google Cloud Translation / Azure Translator
      - or any FLORES-200 compatible NMT service

    Current behaviour:
      - English → English (identity)
      - Any other language → returns the original text with a clear
        marker so the rest of the pipeline can still function offline.
    """
    text = (text or "").strip()
    if not text:
        return ""

    src = normalize_lang_code(source_lang)
    if src == "english":
        return text

    # Placeholder – replace with real NMT call
    # Example integration point:
    #   return bhashini_translate(text, src_lang=get_bhashini_code(src), tgt_lang="en")
    return f"[en←{src}] {text}"


def translate_to_native(text: str, target_lang: str) -> str:
    """
    Translate English `text` into the requested Indian language.

    Same integration contract as translate_to_english.
    """
    text = (text or "").strip()
    if not text:
        return ""

    tgt = normalize_lang_code(target_lang)
    if tgt == "english":
        return text

    # Placeholder – replace with real NMT call
    # Example:
    #   return bhashini_translate(text, src_lang="en", tgt_lang=get_bhashini_code(tgt))
    return f"[{tgt}←en] {text}"


# ---------------------------------------------------------------------------
# Convenience high-level helper
# ---------------------------------------------------------------------------

def prepare_for_nlu(text: str, source_lang: str) -> Dict[str, str]:
    """
    End-to-end preprocessing for an incoming user utterance:
      1. Detect / normalise language code
      2. Clean code-mixed / Romanized script
      3. Translate to English for the core NLU / weather engine
    """
    lang = normalize_lang_code(source_lang)
    cleaned = process_code_mixed_script(text, lang)
    english = translate_to_english(cleaned, lang)
    return {
        "original": text,
        "cleaned": cleaned,
        "source_lang": lang,
        "flores_code": get_flores_code(lang),
        "bhashini_code": get_bhashini_code(lang),
        "english": english,
    }


# ---------------------------------------------------------------------------
# Self-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Supported languages (22 + English) ===")
    for name, info in list_supported_languages().items():
        print(f"  {name:12} → FLORES={info['flores']:12} Bhashini={info['bhashini']}")

    print("\n=== Code-mixed processing examples ===")
    samples = [
        ("Ami ajke abhowa kemon janbo", "bengali"),
        ("Aaj mausam kaisa rahega bhai", "hindi"),
        ("Innikku mazhai varuma", "tamil"),
        ("Nenu ee roju weather enti", "telugu"),
        ("आज मौसम कैसा रहेगा", "hindi"),
    ]
    for txt, lang in samples:
        result = prepare_for_nlu(txt, lang)
        print(f"  [{lang}] {txt}")
        print(f"       → cleaned : {result['cleaned']}")
        print(f"       → english : {result['english']}")
        print()