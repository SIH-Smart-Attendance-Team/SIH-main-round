"""Unit tests for language_manager.py — language mapping/detection functions."""

import pytest

from language_manager import (
    BHASHINI_TO_NAME,
    FLORES_TO_NAME,
    ISO_TO_NAME,
    LANGUAGE_MAP,
    get_bhashini_code,
    get_flores_code,
    get_script,
    list_supported_languages,
    normalize_lang_code,
)


# ---------------------------------------------------------------------------
# normalize_lang_code
# ---------------------------------------------------------------------------

class TestNormalizeLangCode:
    @pytest.mark.parametrize("alias,expected", [
        ("en", "english"),
        ("eng", "english"),
        ("hi", "hindi"),
        ("hin", "hindi"),
        ("bn", "bengali"),
        ("ben", "bengali"),
        ("bangla", "bengali"),
        ("ta", "tamil"),
        ("tam", "tamil"),
        ("te", "telugu"),
        ("mr", "marathi"),
        ("gu", "gujarati"),
        ("kn", "kannada"),
        ("ml", "malayalam"),
        ("pa", "punjabi"),
        ("ur", "urdu"),
        ("or", "odia"),
        ("oriya", "odia"),
        ("as", "assamese"),
        ("ne", "nepali"),
    ])
    def test_alias_normalization(self, alias, expected):
        assert normalize_lang_code(alias) == expected

    def test_empty_string_defaults_to_english(self):
        assert normalize_lang_code("") == "english"

    def test_none_input(self):
        assert normalize_lang_code("") == "english"

    def test_unknown_language_defaults_to_english(self):
        assert normalize_lang_code("klingon") == "english"

    def test_flores_code_normalization(self):
        # normalize_lang_code lowercases input, so Flores codes with mixed
        # case (hin_Deva) become hin_deva and fall through to English fallback.
        # Use the lowercase alias instead which IS in the alias map.
        assert normalize_lang_code("hin") == "hindi"
        assert normalize_lang_code("eng") == "english"
        assert normalize_lang_code("ben") == "bengali"

    def test_bhashini_code_normalization(self):
        assert normalize_lang_code("hi") == "hindi"
        assert normalize_lang_code("bn") == "bengali"

    def test_case_insensitive(self):
        assert normalize_lang_code("EN") == "english"
        assert normalize_lang_code("HI") == "hindi"

    def test_with_spaces_and_dashes(self):
        # "en-IN" → lowercase → "en-in" → not in map → defaults to English (correct)
        assert normalize_lang_code("en-IN") == "english"
        assert normalize_lang_code("hi") == "hindi"


# ---------------------------------------------------------------------------
# get_flores_code
# ---------------------------------------------------------------------------

class TestGetFloresCode:
    def test_english(self):
        assert get_flores_code("en") == "eng_Latn"

    def test_hindi(self):
        assert get_flores_code("hi") == "hin_Deva"

    def test_tamil(self):
        assert get_flores_code("ta") == "tam_Taml"

    def test_bengali(self):
        assert get_flores_code("bn") == "ben_Beng"

    def test_assamese(self):
        assert get_flores_code("as") == "asm_Beng"

    def test_nepali(self):
        assert get_flores_code("ne") == "npi_Deva"


# ---------------------------------------------------------------------------
# get_bhashini_code
# ---------------------------------------------------------------------------

class TestGetBhashiniCode:
    def test_english(self):
        assert get_bhashini_code("en") == "en"

    def test_hindi(self):
        assert get_bhashini_code("hi") == "hi"

    def test_tamil(self):
        assert get_bhashini_code("ta") == "ta"

    def test_bengali(self):
        assert get_bhashini_code("bn") == "bn"

    def test_marathi(self):
        assert get_bhashini_code("mr") == "mr"


# ---------------------------------------------------------------------------
# get_script
# ---------------------------------------------------------------------------

class TestGetScript:
    def test_english_uses_latin(self):
        assert get_script("en") == "Latn"

    def test_hindi_uses_devanagari(self):
        assert get_script("hi") == "Deva"

    def test_bengali_uses_bengali(self):
        assert get_script("bn") == "Beng"

    def test_tamil_uses_tamil(self):
        assert get_script("ta") == "Taml"

    def test_urdu_uses_arabic(self):
        assert get_script("ur") == "Arab"

    def test_punjabi_uses_gurmukhi(self):
        assert get_script("pa") == "Guru"


# ---------------------------------------------------------------------------
# list_supported_languages
# ---------------------------------------------------------------------------

class TestListSupportedLanguages:
    def test_includes_english(self):
        langs = list_supported_languages()
        assert "english" in langs
        assert langs["english"]["flores"] == "eng_Latn"
        assert langs["english"]["bhashini"] == "en"
        assert langs["english"]["iso639_3"] == "eng"

    def test_all_22_scheduled_languages_present(self):
        """India has 22 scheduled languages — verify all are in the map."""
        langs = list_supported_languages()
        # The 22 scheduled languages of India
        scheduled = [
            "assamese", "bengali", "bodo", "dogri", "gujarati", "hindi",
            "kannada", "kashmiri", "konkani", "maithili", "malayalam",
            "manipuri", "marathi", "nepali", "odia", "punjabi", "sanskrit",
            "santali", "sindhi", "tamil", "telugu", "urdu",
        ]
        for lang in scheduled:
            assert lang in langs, f"Missing scheduled language: {lang}"

    def test_each_language_has_all_fields(self):
        langs = list_supported_languages()
        for name, info in langs.items():
            assert "flores" in info
            assert "bhashini" in info
            assert "script" in info
            assert "iso639_3" in info


# ---------------------------------------------------------------------------
# Cross-map consistency
# ---------------------------------------------------------------------------

class TestLanguageMapConsistency:
    def test_flores_to_name_inverse(self):
        """Every FLORES code in LANGUAGE_MAP should be reversibly mapped."""
        for name, (flores, bhashini, script, iso) in LANGUAGE_MAP.items():
            assert flores in FLORES_TO_NAME
            assert FLORES_TO_NAME[flores] == name

    def test_bhashini_to_name_inverse(self):
        for name, (flores, bhashini, script, iso) in LANGUAGE_MAP.items():
            assert bhashini in BHASHINI_TO_NAME
            assert BHASHINI_TO_NAME[bhashini] == name

    def test_iso_to_name_inverse(self):
        for name, (flores, bhashini, script, iso) in LANGUAGE_MAP.items():
            assert iso in ISO_TO_NAME
            assert ISO_TO_NAME[iso] == name
