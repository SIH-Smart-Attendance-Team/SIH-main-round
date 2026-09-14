"""
test_language_manager.py — Unit tests for language_manager.py mapping/detection functions.

Covers normalize_lang_code, get_flores_code, get_bhashini_code, get_script,
list_supported_languages, and cross-map consistency.
"""

import pytest

from language_manager import (
    BHASHINI_TO_NAME,
    FLORES_TO_NAME,
    ISO_TO_NAME,
    LANGUAGE_ALIASES,
    LANGUAGE_MAP,
    get_bhashini_code,
    get_flores_code,
    get_script,
    list_supported_languages,
    normalize_lang_code,
)


class TestNormalizeLangCode:
    """Test normalize_lang_code alias resolution."""

    @pytest.mark.parametrize("alias,expected", [
        ("en", "english"),
        ("eng", "english"),
        ("english", "english"),
        ("hi", "hindi"),
        ("hin", "hindi"),
        ("hindi", "hindi"),
        ("bn", "bengali"),
        ("ben", "bengali"),
        ("bangla", "bengali"),
        ("ta", "tamil"),
        ("tam", "tamil"),
        ("tamil", "tamil"),
        ("te", "telugu"),
        ("tel", "telugu"),
        ("telugu", "telugu"),
        ("mr", "marathi"),
        ("mar", "marathi"),
        ("marathi", "marathi"),
        ("gu", "gujarati"),
        ("guj", "gujarati"),
        ("gujarati", "gujarati"),
        ("kn", "kannada"),
        ("kan", "kannada"),
        ("kannada", "kannada"),
        ("ml", "malayalam"),
        ("mal", "malayalam"),
        ("malayalam", "malayalam"),
        ("pa", "punjabi"),
        ("pan", "punjabi"),
        ("punjabi", "punjabi"),
        ("ur", "urdu"),
        ("urd", "urdu"),
        ("urdu", "urdu"),
        ("or", "odia"),
        ("ory", "odia"),
        ("odia", "odia"),
        ("oriya", "odia"),
        ("as", "assamese"),
        ("asm", "assamese"),
        ("assamese", "assamese"),
        ("ne", "nepali"),
        ("npi", "nepali"),
        ("nepali", "nepali"),
    ])
    def test_alias_normalization(self, alias, expected):
        assert normalize_lang_code(alias) == expected

    def test_empty_string_defaults_to_english(self):
        assert normalize_lang_code("") == "english"

    def test_none_input(self):
        assert normalize_lang_code(None) == "english"

    def test_unknown_language_defaults_to_english(self):
        assert normalize_lang_code("xyz123") == "english"

    def test_flores_code_normalization(self):
        assert normalize_lang_code("eng_Latn") == "english"
        assert normalize_lang_code("hin_Deva") == "hindi"
        assert normalize_lang_code("ben_Beng") == "bengali"

    def test_bhashini_code_normalization(self):
        assert normalize_lang_code("hi") == "hindi"
        assert normalize_lang_code("bn") == "bengali"
        assert normalize_lang_code("ta") == "tamil"

    def test_case_insensitive(self):
        assert normalize_lang_code("EN") == "english"
        assert normalize_lang_code("Hi") == "hindi"
        assert normalize_lang_code("Bn") == "bengali"

    def test_with_spaces_and_dashes(self):
        assert normalize_lang_code("  hi  ") == "hindi"
        assert normalize_lang_code("en-GB") == "english"


class TestGetFloresCode:
    """Test FLORES-200 code retrieval."""

    def test_english(self):
        assert get_flores_code("english") == "eng_Latn"

    def test_hindi(self):
        assert get_flores_code("hindi") == "hin_Deva"

    def test_tamil(self):
        assert get_flores_code("tamil") == "tam_Taml"

    def test_bengali(self):
        assert get_flores_code("bengali") == "ben_Beng"

    def test_assamese(self):
        assert get_flores_code("assamese") == "asm_Beng"

    def test_nepali(self):
        assert get_flores_code("nepali") == "npi_Deva"

    def test_unknown_returns_english(self):
        assert get_flores_code("unknown") == "eng_Latn"


class TestGetBhashiniCode:
    """Test Bhashini code retrieval."""

    def test_english(self):
        assert get_bhashini_code("english") == "en"

    def test_hindi(self):
        assert get_bhashini_code("hindi") == "hi"

    def test_tamil(self):
        assert get_bhashini_code("tamil") == "ta"

    def test_bengali(self):
        assert get_bhashini_code("bengali") == "bn"

    def test_marathi(self):
        assert get_bhashini_code("marathi") == "mr"

    def test_unknown_returns_english(self):
        assert get_bhashini_code("unknown") == "en"


class TestGetScript:
    """Test script retrieval for each language."""

    def test_english_uses_latin(self):
        assert get_script("english") == "Latn"

    def test_hindi_uses_devanagari(self):
        assert get_script("hindi") == "Deva"

    def test_bengali_uses_bengali(self):
        assert get_script("bengali") == "Beng"

    def test_tamil_uses_tamil(self):
        assert get_script("tamil") == "Taml"

    def test_telugu_uses_telugu(self):
        assert get_script("telugu") == "Telu"

    def test_urdu_uses_arabic(self):
        assert get_script("urdu") == "Arab"

    def test_punjabi_uses_gurmukhi(self):
        assert get_script("punjabi") == "Guru"


class TestListSupportedLanguages:
    """Test list_supported_languages output."""

    def test_includes_english(self):
        langs = list_supported_languages()
        assert "english" in langs

    def test_all_22_scheduled_languages_present(self):
        langs = list_supported_languages()
        # 22 scheduled languages + English = 23
        assert len(langs) >= 23

    def test_each_language_has_all_fields(self):
        langs = list_supported_languages()
        for name, lang in langs.items():
            assert "flores" in lang
            assert "bhashini" in lang
            assert "script" in lang
            assert "iso639_3" in lang


class TestLanguageMapConsistency:
    """Test cross-map consistency (no stale entries)."""

    def test_flores_to_name_inverse(self):
        for flores, name in FLORES_TO_NAME.items():
            assert normalize_lang_code(name) == name
            assert get_flores_code(name).lower() == flores.lower()

    def test_bhashini_to_name_inverse(self):
        for bhashini, name in BHASHINI_TO_NAME.items():
            assert normalize_lang_code(name) == name
            assert get_bhashini_code(name).lower() == bhashini.lower()

    def test_iso_to_name_inverse(self):
        for iso, name in ISO_TO_NAME.items():
            assert normalize_lang_code(name) == name
            # ISO codes should normalize back to the canonical name
            assert normalize_lang_code(iso) == name

    def test_all_aliases_in_map(self):
        """Every alias should resolve to a key in LANGUAGE_MAP or 'english'."""
        for alias, canonical in LANGUAGE_ALIASES.items():
            assert canonical == "english" or canonical in LANGUAGE_MAP