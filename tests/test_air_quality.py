"""Unit tests for Mumbai Air Quality (SDG 3) service and dashboard routes."""

import httpx
import pytest
from fastapi.testclient import TestClient

from services.api.air_quality import (
    MUMBAI_STATIONS,
    clear_air_quality_cache,
    fetch_air_quality,
    fetch_station_trend,
    get_aqi_category,
    get_historical_baseline,
)
from services.api.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_cache() -> None:
    clear_air_quality_cache()
    yield
    clear_air_quality_cache()


def test_aqi_category_boundaries() -> None:
    assert get_aqi_category(25)["level"] == "Good"
    assert get_aqi_category(50)["level"] == "Good"
    assert get_aqi_category(75)["level"] == "Moderate"
    assert get_aqi_category(100)["level"] == "Moderate"
    assert get_aqi_category(125)["level"] == "Unhealthy for Sensitive Groups"
    assert get_aqi_category(150)["level"] == "Unhealthy for Sensitive Groups"
    assert get_aqi_category(175)["level"] == "Unhealthy"
    assert get_aqi_category(200)["level"] == "Unhealthy"
    assert get_aqi_category(250)["level"] == "Very Unhealthy"
    assert get_aqi_category(300)["level"] == "Very Unhealthy"
    assert get_aqi_category(350)["level"] == "Hazardous"


def test_historical_baseline_structure() -> None:
    baseline = get_historical_baseline()
    assert baseline["status"] == "success"
    assert baseline["data_mode"] == "historical_fallback"
    assert baseline["city"] == "Mumbai"
    assert baseline["station_count"] == 8
    assert len(baseline["stations"]) == 8

    station_names = {s["station"] for s in baseline["stations"]}
    assert "Bandra" in station_names
    assert "Colaba" in station_names
    assert "Kurla" in station_names
    assert "Worli" in station_names
    assert "BKC" in station_names
    assert "Andheri" in station_names
    assert "Borivali" in station_names
    assert "Navi Mumbai" in station_names

    first = baseline["stations"][0]
    assert "aqi" in first
    assert "category" in first
    assert "pm2_5" in first["pollutants"]
    assert "pm10" in first["pollutants"]
    assert "nitrogen_dioxide" in first["pollutants"]


@pytest.mark.anyio
async def test_fetch_air_quality_live_success() -> None:
    station_count = len(MUMBAI_STATIONS)
    mock_payload = [
        {
            "latitude": 19.0,
            "longitude": 72.8,
            "current": {
                "time": "2026-10-18T13:00",
                "us_aqi": 140 + i * 5,
                "pm2_5": 65.0 + i,
                "pm10": 95.0 + i,
                "nitrogen_dioxide": 22.0,
                "sulphur_dioxide": 12.0,
                "carbon_monoxide": 400.0,
                "ozone": 50.0,
            },
        }
        for i in range(station_count)
    ]

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_air_quality(client=client)

    assert result["status"] == "success"
    assert result["data_mode"] == "live"
    assert result["city"] == "Mumbai"
    assert len(result["stations"]) == station_count
    assert result["stations"][0]["aqi"] == 140


@pytest.mark.anyio
async def test_fetch_air_quality_fallback_on_api_error() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_air_quality(client=client)

    assert result["status"] == "success"
    assert result["data_mode"] == "historical_fallback"
    assert len(result["stations"]) == 8


@pytest.mark.anyio
async def test_fetch_air_quality_fallback_on_malformed_response() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "not a list"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_air_quality(client=client)

    assert result["data_mode"] == "historical_fallback"


@pytest.mark.anyio
async def test_fetch_station_trend_live_success() -> None:
    mock_hourly = {
        "hourly": {
            "time": [f"2026-10-18T{h:02d}:00" for h in range(24)],
            "pm2_5": [50.0 + h for h in range(24)],
            "pm10": [80.0 + h for h in range(24)],
            "us_aqi": [120 + h for h in range(24)],
            "nitrogen_dioxide": [20.0 + h for h in range(24)],
        }
    }

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_hourly)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        trend = await fetch_station_trend(station_name="Bandra", client=client)

    assert trend["status"] == "success"
    assert trend["data_mode"] == "live"
    assert trend["station"] == "Bandra"
    assert len(trend["trend"]) == 24
    assert trend["trend"][-1]["aqi"] == 143


@pytest.mark.anyio
async def test_fetch_station_trend_fallback_on_error() -> None:
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Network unreachable")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        trend = await fetch_station_trend(station_name="Colaba", client=client)

    assert trend["status"] == "success"
    assert trend["data_mode"] == "historical_fallback"
    assert trend["station"] == "Colaba"
    assert len(trend["trend"]) == 24


@pytest.mark.anyio
async def test_distinct_station_coordinates_and_data_mapping() -> None:
    station_names = list(MUMBAI_STATIONS.keys())
    coords = [
        (MUMBAI_STATIONS[name]["latitude"], MUMBAI_STATIONS[name]["longitude"])
        for name in station_names
    ]
    # Verify all configured station coordinates are unique
    assert len(set(coords)) == len(station_names) == 8

    mock_payload = [
        {
            "latitude": round(MUMBAI_STATIONS[name]["latitude"], 1),
            "longitude": round(MUMBAI_STATIONS[name]["longitude"], 1),
            "current": {
                "time": "2026-10-18T14:30",
                "us_aqi": 150 + i * 2,
                "pm2_5": 70.0 + i,
                "pm10": 100.0 + i,
                "nitrogen_dioxide": 20.0 + i,
                "sulphur_dioxide": 15.0,
                "carbon_monoxide": 300.0 + i * 20,
                "ozone": 50.0,
            },
        }
        for i, name in enumerate(station_names)
    ]

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_air_quality(client=client)

    assert result["data_mode"] == "live"
    assert "Spatial Grid Assimilation" in result["data_type"]
    assert result["observation_time"] == "2026-10-18T14:30"
    assert result["is_stale"] is False

    for i, s in enumerate(result["stations"]):
        name = s["station"]
        assert s["latitude"] == MUMBAI_STATIONS[name]["latitude"]
        assert s["longitude"] == MUMBAI_STATIONS[name]["longitude"]
        assert s["grid_latitude"] == round(MUMBAI_STATIONS[name]["latitude"], 1)
        assert s["grid_longitude"] == round(MUMBAI_STATIONS[name]["longitude"], 1)
        assert s["pollutants"]["pm2_5"]["unit"] == "μg/m³"
        assert s["pollutants"]["carbon_monoxide"]["value"] == 300.0 + i * 20


@pytest.mark.anyio
async def test_air_quality_cache_and_force_refresh() -> None:
    call_count = 0
    mock_payload = [
        {
            "latitude": 19.1,
            "longitude": 72.8,
            "current": {
                "time": "2026-10-18T14:30",
                "us_aqi": 150,
                "pm2_5": 70.0,
                "pm10": 100.0,
                "nitrogen_dioxide": 20.0,
                "sulphur_dioxide": 15.0,
                "carbon_monoxide": 350.0,
                "ozone": 50.0,
            },
        }
        for _ in MUMBAI_STATIONS
    ]

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=mock_payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # First call: hits transport
        res1 = await fetch_air_quality(client=client)
        assert call_count == 1
        assert res1["is_stale"] is False

        # Second call: within TTL, returns cached data without calling transport
        res2 = await fetch_air_quality(client=client)
        assert call_count == 1
        assert res2["is_stale"] is False

        # Third call: force_refresh=True, bypasses cache and hits transport
        res3 = await fetch_air_quality(client=client, force_refresh=True)
        assert call_count == 2
        assert res3["is_stale"] is False


@pytest.mark.anyio
async def test_stale_cache_on_upstream_failure() -> None:
    should_fail = False
    mock_payload = [
        {
            "latitude": 19.1,
            "longitude": 72.8,
            "current": {
                "time": "2026-10-18T14:30",
                "us_aqi": 160,
                "pm2_5": 80.0,
                "pm10": 110.0,
                "nitrogen_dioxide": 22.0,
                "sulphur_dioxide": 16.0,
                "carbon_monoxide": 400.0,
                "ozone": 55.0,
            },
        }
        for _ in MUMBAI_STATIONS
    ]

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if should_fail:
            raise httpx.ConnectError("Network timeout to Open-Meteo")
        return httpx.Response(200, json=mock_payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # Populate cache initially
        res1 = await fetch_air_quality(client=client)
        assert res1["data_mode"] == "live"
        assert res1["is_stale"] is False

        # Now simulate network failure with force_refresh
        should_fail = True
        res2 = await fetch_air_quality(client=client, force_refresh=True)
        assert res2["data_mode"] == "live"
        assert res2["is_stale"] is True
        assert "Upstream API temporary issue" in res2["stale_reason"]
        assert res2["city_average_aqi"] == 160


def test_api_routes_integration() -> None:
    client = TestClient(app)

    # Index route
    resp_index = client.get("/")
    assert resp_index.status_code == 200
    data_index = resp_index.json()
    assert "sdg_project" in data_index
    assert data_index["dashboard_url"] == "/dashboard"
    assert data_index["air_quality_api"] == "/api/v1/air-quality"
    assert data_index["incidents_latest"] == "/incidents/latest"
    assert data_index["metrics"] == "/metrics"
    assert data_index["health"] == "/healthz"

    # Dashboard HTML page
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    assert "text/html" in resp_dash.headers["content-type"]
    assert "SENTINEL Air Sentinel" in resp_dash.text
    assert "UN SDG 3" in resp_dash.text
    assert "/metrics" in resp_dash.text
    assert "/api/v1/air-quality" in resp_dash.text
    assert "/incidents/latest" in resp_dash.text
    assert "/healthz" in resp_dash.text
    assert "Spatial Grid Modeling Transparency" in resp_dash.text

    # Air Quality API endpoint (/api/v1/air-quality)
    resp_aq = client.get("/api/v1/air-quality")
    assert resp_aq.status_code == 200
    data_aq = resp_aq.json()
    assert data_aq["city"] == "Mumbai"
    assert len(data_aq["stations"]) == 8

    # Latest Air Quality API endpoint (/api/v1/air-quality/latest alias)
    resp_aq_latest = client.get("/api/v1/air-quality/latest")
    assert resp_aq_latest.status_code == 200

    # History Air Quality API endpoint
    resp_hist = client.get("/api/v1/air-quality/history?station=Worli")
    assert resp_hist.status_code == 200
    data_hist = resp_hist.json()
    assert data_hist["station"] == "Worli"
    assert len(data_hist["trend"]) == 24

    # Prometheus metrics endpoint
    resp_metrics = client.get("/metrics")
    assert resp_metrics.status_code == 200
    assert "mumbai_aqi" in resp_metrics.text or "http_requests" in resp_metrics.text

    # Service health endpoint
    resp_health = client.get("/healthz")
    assert resp_health.status_code == 200
    assert resp_health.json() == {"status": "ok"}

    # Incidents latest endpoint (404 expected if no incidents, or incident dict)
    resp_inc = client.get("/incidents/latest")
    assert resp_inc.status_code in (200, 404)
    resp_inc_api = client.get("/api/v1/incidents/latest")
    assert resp_inc_api.status_code in (200, 404)
