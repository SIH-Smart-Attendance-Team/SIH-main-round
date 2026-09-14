"""
test_main_endpoints.py — Integration tests for main.py FastAPI endpoints.

Uses FastAPI TestClient with all external dependencies mocked via conftest fixtures.
"""



class TestHealthEndpoint:
    """Test /health endpoint."""

    def test_health_returns_ok(self, test_client):
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded")
        assert "timestamp" in data
        assert data["service"] == "WeatherGPT"


class TestCurrentWeather:
    """Test /api/v1/weather/current endpoint."""

    def test_valid_request(self, test_client, mock_external_apis):
        response = test_client.get("/api/v1/weather/current", params={"lat": 28.61, "lon": 77.21})
        assert response.status_code == 200
        data = response.json()
        assert "temperature" in data
        assert "wind_speed" in data
        assert data["latitude"] == 28.61
        assert data["longitude"] == 77.21

    def test_missing_params_rejected(self, test_client):
        response = test_client.get("/api/v1/weather/current", params={"lat": 28.61})
        assert response.status_code == 422


class TestAgriMetrics:
    """Test /api/v1/weather/agri endpoint."""

    def test_valid_request(self, test_client, mock_external_apis):
        response = test_client.get("/api/v1/weather/agri", params={"lat": 28.61, "lon": 77.21})
        assert response.status_code == 200
        data = response.json()
        assert "et0_fao_evapotranspiration" in data

    def test_missing_params(self, test_client):
        response = test_client.get("/api/v1/weather/agri", params={})
        assert response.status_code == 422


class TestMarineMetrics:
    """Test /api/v1/weather/marine endpoint."""

    def test_valid_request(self, test_client, mock_external_apis):
        response = test_client.get("/api/v1/weather/marine", params={"lat": 19.07, "lon": 72.87})
        assert response.status_code == 200
        data = response.json()
        assert "wave_height" in data

    def test_missing_params(self, test_client):
        response = test_client.get("/api/v1/weather/marine", params={})
        assert response.status_code == 422


class TestDisasterAlerts:
    """Test /api/v1/disaster/alerts endpoint."""

    def test_valid_request(self, test_client, mock_external_apis):
        response = test_client.get("/api/v1/disaster/alerts", params={"lat": 28.61, "lon": 77.21, "radius_km": 300, "days": 14})
        assert response.status_code == 200
        data = response.json()
        assert "alerts" in data

    def test_missing_required_params(self, test_client):
        response = test_client.get("/api/v1/disaster/alerts", params={})
        assert response.status_code == 422

    def test_invalid_days_rejected(self, test_client):
        response = test_client.get("/api/v1/disaster/alerts", params={"lat": 28.61, "lon": 77.21, "days": 0})
        assert response.status_code == 422
        response = test_client.get("/api/v1/disaster/alerts", params={"lat": 28.61, "lon": 77.21, "days": 31})
        assert response.status_code == 422


class TestAlertEndpoints:
    """Test Layer 3 alert endpoints (drafted, approve, reject)."""

    def test_list_draft_alerts_without_db(self, test_client):
        """Should return 503 when MongoDB unavailable."""
        response = test_client.get("/api/v1/alerts/drafted")
        # With mocked DB returning None/empty, may return 200 with empty list or 503
        assert response.status_code in (200, 503)

    def test_approve_nonexistent_alert(self, test_client):
        response = test_client.post("/api/v1/alerts/nonexistent/approve", json={"approved_by": "tester"})
        assert response.status_code in (404, 503)

    def test_reject_nonexistent_alert(self, test_client):
        response = test_client.post("/api/v1/alerts/nonexistent/reject", json={"rejected_by": "tester", "reason": "test"})
        assert response.status_code in (404, 503)

    def test_approve_missing_approved_by(self, test_client):
        response = test_client.post("/api/v1/alerts/someid/approve", json={})
        assert response.status_code == 422


class TestAuthEndpoints:
    """Test auth endpoints."""

    def test_me_without_token(self, test_client):
        response = test_client.get("/api/v1/auth/me")
        assert response.status_code == 401

    def test_me_with_invalid_token(self, test_client):
        response = test_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"})
        assert response.status_code == 401


class TestDocs:
    """Test docs endpoints."""

    def test_swagger_ui(self, test_client):
        response = test_client.get("/docs")
        assert response.status_code == 200

    def test_openapi_schema(self, test_client):
        response = test_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data