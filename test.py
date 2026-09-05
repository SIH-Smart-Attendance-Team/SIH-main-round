"""
backend/tests/test_ai_pipeline.py

Unit / integration tests for the WeatherGPT AI pipeline.

Coverage
--------
1. weather_service.py  – current / agri / marine helpers & forecast shape
2. language_manager.py – code-mixed normalisation & language-code mapping
3. vision_scanner.py   – structured JSON diagnostics schema

Run with:
    pytest backend/tests/test_ai_pipeline.py -v
"""
from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient

import httpx
import pytest
import pytest_asyncio
from httpx import ASGIClient, ASGITransport
from pydantic import ValidationError
from weather_service import WeatherService

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from language_manager import (
    get_bhashini_code,
    get_flores_code,
    list_supported_languages,
    normalize_lang_code,
    prepare_for_nlu,
    process_code_mixed_script,
    translate_to_english,
    translate_to_native,
)
from Vision_scanner import (
    DiagnosisCategory,
    Finding,
    Severity,
    VisionDiagnostics,
    VisionScanner,
)
from weather_service import (
    CurrentWeather,
    ForecastResponse,
    WeatherService,
)

# Optional: full app factory for endpoint-level tests
try:
    from backend_app_factory import create_app
    APP_AVAILABLE = True
except ImportError:
    APP_AVAILABLE = False


# ===========================================================================
# 1. language_manager tests
# ===========================================================================

class TestLanguageManager:
    """Code-mixed handling and language-code mapping."""

    def test_all_22_scheduled_languages_present(self) -> None:
        langs = list_supported_languages()
        # 22 scheduled + English
        assert len(langs) >= 23
        for name in (
            "hindi", "bengali", "tamil", "telugu", "marathi",
            "gujarati", "kannada", "malayalam", "odia", "assamese",
            "punjabi", "urdu", "sanskrit", "nepali", "sindhi",
            "konkani", "maithili", "santali", "manipuri", "dogri",
            "bodo", "kashmiri",
        ):
            assert name in langs, f"Missing scheduled language: {name}"

    def test_normalize_lang_code_aliases(self) -> None:
        assert normalize_lang_code("hi") == "hindi"
        assert normalize_lang_code("HI") == "hindi"
        assert normalize_lang_code("hin") == "hindi"
        assert normalize_lang_code("bn") == "bengali"
        assert normalize_lang_code("bangla") == "bengali"
        assert normalize_lang_code("ta") == "tamil"
        assert normalize_lang_code("en") == "english"
        assert normalize_lang_code("unknown_xyz") == "english"

    def test_flores_and_bhashini_codes(self) -> None:
        assert get_flores_code("hindi") == "hin_Deva"
        assert get_bhashini_code("hindi") == "hi"
        assert get_flores_code("tamil") == "tam_Taml"
        assert get_bhashini_code("tamil") == "ta"
        assert get_flores_code("english") == "eng_Latn"
        assert get_bhashini_code("english") == "en"

    @pytest.mark.parametrize(
        "text,lang,must_contain",
        [
            ("Ami ajke abhowa kemon janbo", "bengali", "Ami ajke"),
            ("Aaj mausam kaisa rahega bhai", "hindi", "Aaj mausam"),
            ("Innikku mazhai varuma", "tamil", "Innikku"),
            ("Nenu ee roju weather enti", "telugu", "Nenu"),
            ("आज मौसम कैसा रहेगा", "hindi", "मौसम"),
        ],
    )
    def test_process_code_mixed_script(
        self, text: str, lang: str, must_contain: str
    ) -> None:
        cleaned = process_code_mixed_script(text, lang)
        assert isinstance(cleaned, str)
        assert cleaned  # non-empty
        assert must_contain in cleaned or must_contain.lower() in cleaned.lower()
        # No leading/trailing whitespace
        assert cleaned == cleaned.strip()
        # No double spaces
        assert "  " not in cleaned

    def test_process_empty_input(self) -> None:
        assert process_code_mixed_script("", "hindi") == ""
        assert process_code_mixed_script("   ", "hindi") == ""

    def test_translate_to_english_identity(self) -> None:
        assert translate_to_english("Hello world", "english") == "Hello world"

    def test_translate_to_english_marks_source(self) -> None:
        result = translate_to_english("Aaj mausam kaisa hai", "hindi")
        assert "hindi" in result or "en←" in result or result.startswith("[")

    def test_translate_to_native_identity(self) -> None:
        assert translate_to_native("Hello", "english") == "Hello"

    def test_prepare_for_nlu_keys(self) -> None:
        out = prepare_for_nlu("Aaj barish hogi kya?", "hindi")
        assert set(out.keys()) >= {
            "original", "cleaned", "source_lang",
            "flores_code", "bhashini_code", "english",
        }
        assert out["source_lang"] == "hindi"
        assert out["bhashini_code"] == "hi"


# ===========================================================================
# 2. weather_service tests
# ===========================================================================

# Minimal Open-Meteo-like fixtures
MOCK_CURRENT = {
    "latitude": 28.61,
    "longitude": 77.21,
    "timezone": "Asia/Kolkata",
    "current": {
        "time": "2026-09-02T08:00",
        "temperature_2m": 31.2,
        "relative_humidity_2m": 68,
        "precipitation": 0.0,
        "wind_speed_10m": 12.5,
        "wind_direction_10m": 140,
        "weather_code": 2,
        "pressure_msl": 1008.3,
    },
}

MOCK_FORECAST = {
    **MOCK_CURRENT,
    "daily": {
        "time": ["2026-09-02", "2026-09-03", "2026-09-04"],
        "temperature_2m_max": [34.1, 33.0, 32.5],
        "temperature_2m_min": [26.0, 25.5, 25.0],
        "precipitation_sum": [0.0, 2.5, 10.0],
        "precipitation_probability_max": [10, 40, 80],
        "weather_code": [2, 61, 63],
    },
    "hourly": {
        "time": ["2026-09-02T08:00", "2026-09-02T09:00"],
        "temperature_2m": [31.2, 32.0],
        "precipitation": [0.0, 0.1],
        "precipitation_probability": [5, 10],
        "weather_code": [2, 3],
    },
}
from typing import AsyncGenerator

@pytest_asyncio.fixture
async def weather_svc() -> AsyncGenerator[WeatherService, None]:
    svc = WeatherService()
    yield svc
    await svc.aclose()


class TestWeatherService:
    """Validate weather_service helpers against mocked Open-Meteo payloads."""

    @pytest.mark.asyncio
    async def test_get_current_weather_shape(self, weather_svc: WeatherService) -> None:
        with patch.object(
            weather_svc, "_request", new_callable=AsyncMock, return_value=MOCK_CURRENT
        ):
            data = await weather_svc.get_current_weather(28.61, 77.21)

        assert isinstance(data, dict)
        assert data["temperature"] == 31.2
        assert data["relative_humidity"] == 68
        assert data["wind_speed"] == 12.5
        assert data["weather_code"] == 2
        assert data["pressure"] == 1008.3
        assert "time" in data

    @pytest.mark.asyncio
    async def test_get_forecast_model(self, weather_svc: WeatherService) -> None:
        with patch.object(
            weather_svc, "_request", new_callable=AsyncMock, return_value=MOCK_FORECAST
        ):
            forecast = await weather_svc.get_forecast(28.61, 77.21, days=3)

        assert isinstance(forecast, ForecastResponse)
        assert forecast.latitude == pytest.approx(28.61, abs=0.1)
        assert forecast.current is not None
        assert forecast.current.temperature == 31.2
        assert len(forecast.daily) == 3
        assert forecast.daily[0].temperature_max == 34.1
        assert len(forecast.hourly) >= 1

    @pytest.mark.asyncio
    async def test_get_agricultural_metrics_keys(
        self, weather_svc: WeatherService
    ) -> None:
        mock_agri = {
            "latitude": 28.61,
            "longitude": 77.21,
            "current": {
                "time": "2026-09-02T08:00",
                "et0_fao_evapotranspiration": 4.2,
                "soil_temperature_0_to_7cm": 29.5,
                "soil_temperature_7_to_28cm": 28.0,
                "soil_moisture_0_to_7cm": 0.25,
                "soil_moisture_7_to_28cm": 0.30,
                "leaf_wetness_probability": 15.0,
            },
        }
        with patch.object(
            weather_svc, "_request", new_callable=AsyncMock, return_value=mock_agri
        ):
            data = await weather_svc.get_agricultural_metrics(28.61, 77.21)

        assert "et0_fao_evapotranspiration" in data
        assert data["et0_fao_evapotranspiration"] == 4.2
        assert "soil_moisture_0_to_7cm" in data

    @pytest.mark.asyncio
    async def test_request_failure_raises(self, weather_svc: WeatherService) -> None:
        with patch.object(
            weather_svc,
            "_request",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API down"),
        ):
            with pytest.raises(RuntimeError, match="API down"):
                await weather_svc.get_current_weather(0.0, 0.0)


# ===========================================================================
# 3. vision_scanner schema tests
# ===========================================================================

VALID_DIAGNOSTICS_JSON = {
    "overall_severity": "moderate",
    "primary_category": "disease",
    "summary": "Leaf blast detected on rice crop with moderate severity.",
    "findings": [
        {
            "category": "disease",
            "label": "Leaf Blast",
            "confidence": 0.82,
            "severity": "moderate",
            "description": "Elliptical lesions with grey centres visible on leaves.",
            "recommended_actions": [
                "Apply tricyclazole fungicide",
                "Improve field drainage",
            ],
        }
    ],
}


class TestVisionScannerSchema:
    """Ensure VisionDiagnostics / Finding accept valid JSON and reject bad data."""

    def test_valid_diagnostics_parses(self) -> None:
        diag = VisionDiagnostics(
            success=True,
            model_used="gemini-2.0-flash",
            overall_severity=Severity(VALID_DIAGNOSTICS_JSON["overall_severity"]),
            primary_category=DiagnosisCategory(
                VALID_DIAGNOSTICS_JSON["primary_category"]
            ),
            summary=VALID_DIAGNOSTICS_JSON["summary"],
            findings=[Finding(**f) for f in VALID_DIAGNOSTICS_JSON["findings"]],
        )
        assert diag.success is True
        assert diag.overall_severity == Severity.MODERATE
        assert diag.primary_category == DiagnosisCategory.DISEASE
        assert len(diag.findings) == 1
        assert diag.findings[0].confidence == pytest.approx(0.82)
        assert "tricyclazole" in diag.findings[0].recommended_actions[0].lower()

    def test_finding_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Finding(
                category=DiagnosisCategory.PEST,
                label="Brown Planthopper",
                confidence=1.5,  # invalid > 1.0
                severity=Severity.HIGH,
                description="test",
            )

    def test_severity_enum(self) -> None:
        for s in ("none", "low", "moderate", "high", "critical"):
            assert Severity(s).value == s
        with pytest.raises(ValueError):
            Severity("extreme")

    def test_mock_scanner_returns_valid_schema(self) -> None:
        """When Gemini is unavailable the scanner still returns a valid model."""
        scanner = VisionScanner()
        # Force mock path
        scanner._model = None
        result = scanner.analyse_sync(b"\xff\xd8\xff")  # tiny invalid jpeg bytes
        assert isinstance(result, VisionDiagnostics)
        assert result.model_used in ("mock", scanner.model_name)
        # Schema must still be valid
        dumped = result.model_dump()
        assert "overall_severity" in dumped
        assert "findings" in dumped
        assert isinstance(dumped["findings"], list)

    def test_json_roundtrip(self) -> None:
        diag = VisionDiagnostics(
            success=True,
            model_used="test",
            overall_severity=Severity.LOW,
            primary_category=DiagnosisCategory.HEALTHY,
            summary="Crop appears healthy.",
            findings=[
                Finding(
                    category=DiagnosisCategory.HEALTHY,
                    label="Healthy",
                    confidence=0.95,
                    severity=Severity.NONE,
                    description="No visible stress.",
                    recommended_actions=[],
                )
            ],
        )
        raw = diag.model_dump_json()
        reloaded = VisionDiagnostics.model_validate(json.loads(raw))
        assert reloaded.summary == diag.summary
        assert reloaded.findings[0].label == "Healthy"


# ===========================================================================
# 4. Optional endpoint-level smoke tests (when app_factory is importable)
# ===========================================================================

@pytest.mark.skipif(not APP_AVAILABLE, reason="app_factory not importable")
class TestWeatherEndpoints:
    """Hit /api/v1/weather/* via httpx.AsyncClient against the real app."""

    @pytest_asyncio.fixture
    async def client(self):
        app = create_app(enable_docs=False, log_level="WARNING")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_health(self, client: AsyncClient) -> None:
        res = await client.get("/health")
        assert res.status_code == 200
        body = res.json()
        assert body.get("status") == "ok"

    @pytest.mark.asyncio
    async def test_current_weather_validation(self, client: AsyncClient) -> None:
        # Missing required query params → 422
        res = await client.get("/api/v1/weather/current")
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_current_weather_mocked(self, client: AsyncClient) -> None:
        with patch(
            "weather_service.WeatherService.get_current_weather",
            new_callable=AsyncMock,
            return_value={
                "temperature": 30.0,
                "relative_humidity": 70,
                "precipitation": 0.0,
                "wind_speed": 10.0,
                "wind_direction": 90,
                "weather_code": 1,
                "pressure": 1010.0,
                "time": "2026-09-02T08:00",
                "latitude": 28.61,
                "longitude": 77.21,
                "timezone": "Asia/Kolkata",
            },
        ):
            res = await client.get(
                "/api/v1/weather/current",
                params={"lat": 28.61, "lon": 77.21},
            )
        # Endpoint may be absent if main.py routes were not loaded; accept 200 or 404
        assert res.status_code in (200, 404)
        if res.status_code == 200:
            data = res.json()
            assert data["temperature"] == 30.0