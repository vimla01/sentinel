from fastapi.testclient import TestClient

from services.demo_api.main import app

client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_hello() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "sentinel-demo-api"


def test_debug_status_defaults_to_no_chaos() -> None:
    client.post("/debug/reset")
    status = client.get("/debug/status").json()
    assert status == {
        "memory_leak_mb": 0,
        "cpu_spike_active": False,
        "cpu_spike_remaining_seconds": 0.0,
        "latency_ms": 0,
        "error_probability": 0.0,
    }


def test_leak_memory_grows_reported_usage() -> None:
    client.post("/debug/reset")
    client.post("/debug/leak-memory", json={"chunk_mb": 5})
    status = client.get("/debug/status").json()
    assert status["memory_leak_mb"] >= 5
    client.post("/debug/reset")
    assert client.get("/debug/status").json()["memory_leak_mb"] == 0


def test_error_rate_injects_failures() -> None:
    client.post("/debug/reset")
    client.post("/debug/error-rate", json={"probability": 1.0, "duration_seconds": 5})
    response = client.get("/")
    assert response.status_code == 500
    client.post("/debug/reset")
    assert client.get("/").status_code == 200


def test_cpu_spike_reports_active_then_clears() -> None:
    client.post("/debug/reset")
    status = client.post("/debug/cpu-spike", json={"duration_seconds": 0.2, "workers": 1}).json()
    assert status["cpu_spike_active"] is True

    import time

    time.sleep(0.4)
    assert client.get("/debug/status").json()["cpu_spike_active"] is False
