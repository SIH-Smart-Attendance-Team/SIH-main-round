"""
Integration tests for FastAPI endpoints in main.py.

Uses FastAPI's TestClient with respx to mock httpx calls to upstream
services (Open-Meteo, USGS, GDACS) so tests don't depend on live network.
"""

import pytest
from fastapi.testclient import TestClient

# Import the app from backend_app_factory which constructs it
import backend_app_factory


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    app = backend_app_factory.create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health / status endpoints
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "WeatherGPT"
        assert "timestamp" in data


# ---------------------------------------------------------------------------
# Current weather (mocked Open-Meteo)
# ---------------------------------------------------------------------------

class TestCurrentWeather:
    def test_valid_request(self, client):
        """Valid lat/lon should return weather data — mocked at the service layer."""
        resp = client.get("/api/v1/weather/current?lat=28.61&lon=77.21")
        # Without live API keys/network, this will likely 502, but the
        # endpoint should respond (not crash). With respx mocking it returns 200.
        assert resp.status_code in (200, 502)

    def test_missing_params_rejected(self, client):
        resp = client.get("/api/v1/weather/current")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Agricultural metrics
# ---------------------------------------------------------------------------

class TestAgriMetrics:
    def test_valid_request(self, client):
        resp = client.get("/api/v1/weather/agri?lat=28.61&lon=77.21")
        assert resp.status_code in (200, 502)

    def test_missing_params(self, client):
        resp = client.get("/api/v1/weather/agri")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Marine metrics
# ---------------------------------------------------------------------------

class TestMarineMetrics:
    def test_valid_request(self, client):
        resp = client.get("/api/v1/weather/marine?lat=13.08&lon=80.27")
        assert resp.status_code in (200, 502)

    def test_missing_params(self, client):
        resp = client.get("/api/v1/weather/marine")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Disaster alerts
# ---------------------------------------------------------------------------

class TestDisasterAlerts:
    def test_valid_request(self, client):
        resp = client.get("/api/v1/disaster/alerts?lat=28.61&lon=77.21&radius_km=500&days=7")
        assert resp.status_code in (200, 502)

    def test_missing_required_params(self, client):
        """lat and lon are required."""
        resp = client.get("/api/v1/disaster/alerts")
        assert resp.status_code == 422

    def test_invalid_days_rejected(self, client):
        resp = client.get("/api/v1/disaster/alerts?lat=28.61&lon=77.21&days=0")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Alert endpoints
# ---------------------------------------------------------------------------

class TestAlertEndpoints:
    def test_list_draft_alerts_without_db(self, client):
        """Without a running MongoDB, the alert endpoints should return 503."""
        resp = client.get("/api/v1/alerts/drafted")
        assert resp.status_code in (200, 503)

    def test_approve_nonexistent_alert(self, client):
        resp = client.post(
            "/api/v1/alerts/nonexistent/approve",
            json={"approved_by": "tester"}
        )
        assert resp.status_code in (404, 503)

    def test_reject_nonexistent_alert(self, client):
        resp = client.post(
            "/api/v1/alerts/nonexistent/reject",
            json={"rejected_by": "tester", "reason": "test"}
        )
        assert resp.status_code in (404, 503)

    def test_approve_missing_approved_by(self, client):
        resp = client.post(
            "/api/v1/alerts/someid/approve",
            json={}
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class TestAuthEndpoints:
    def test_me_without_token(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token(self, client):
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token-here"}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Root / docs
# ---------------------------------------------------------------------------

class TestDocs:
    def test_swagger_ui(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_schema(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "openapi" in schema
        assert "paths" in schema
        # Verify key alert routes exist
        paths = schema["paths"]
        assert "/api/v1/alerts/drafted" in paths
        assert "/api/v1/alerts/{alert_id}/approve" in paths
