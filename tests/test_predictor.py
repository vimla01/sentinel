import random
from collections import deque

from fastapi.testclient import TestClient

from services.predictor.config import settings
from services.predictor.main import app
from services.predictor.metrics_client import PrometheusClient
from services.predictor.monitor import RiskMonitor, evaluate_metric

client = TestClient(app)


def _seed_baseline(window: deque, rng: random.Random, base: float = 10.0) -> None:
    for _ in range(settings.min_samples):
        evaluate_metric(window, base + rng.uniform(-0.2, 0.2))


def test_evaluate_metric_does_not_breach_on_normal_jitter() -> None:
    rng = random.Random(42)
    window: deque = deque(maxlen=settings.window_size)
    _seed_baseline(window, rng)

    result = evaluate_metric(window, 10.1)

    assert not result.breached


def test_evaluate_metric_breaches_on_large_spike() -> None:
    rng = random.Random(42)
    window: deque = deque(maxlen=settings.window_size)
    _seed_baseline(window, rng)

    result = evaluate_metric(window, 500.0)

    assert result.breached
    assert result.z_score >= settings.threshold_sigma


def test_evaluate_metric_skips_zscore_before_min_samples() -> None:
    window: deque = deque(maxlen=settings.window_size)

    result = evaluate_metric(window, 999.0)

    assert not result.breached
    assert result.z_score == 0.0


def test_risk_monitor_edge_triggers_alert_and_respects_cooldown() -> None:
    monitor = RiskMonitor(PrometheusClient("http://unused:9090"), "demo-api")
    rng = random.Random(7)
    state = monitor._states["cpu_percent"]  # noqa: SLF001 - inspecting internal state in test
    for _ in range(settings.min_samples):
        monitor._evaluate("cpu_percent", 10.0 + rng.uniform(-0.2, 0.2))
    assert monitor.alerts == []

    monitor._evaluate("cpu_percent", 500.0)
    assert len(monitor.alerts) == 1
    assert state.alerting is True

    monitor._evaluate("cpu_percent", 500.0)
    assert len(monitor.alerts) == 1  # cooldown suppresses an immediate re-fire


def test_overall_risk_reflects_worst_metric() -> None:
    monitor = RiskMonitor(PrometheusClient("http://unused:9090"), "demo-api")
    rng = random.Random(3)
    for _ in range(settings.min_samples):
        monitor._evaluate("cpu_percent", 10.0 + rng.uniform(-0.2, 0.2))
        monitor._evaluate("memory_bytes", 1_000_000 + rng.uniform(-1000, 1000))

    assert monitor.overall_risk() == 0.0

    monitor._evaluate("memory_bytes", 50_000_000)

    assert monitor.overall_risk() > 0.0


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_risk_endpoint_shape() -> None:
    response = client.get("/risk")
    assert response.status_code == 200
    body = response.json()
    assert body["target"] == settings.target_job
    assert body["threshold_sigma"] == settings.threshold_sigma
    assert "overall_risk" in body
    assert set(body["metrics"].keys()) == {
        "cpu_percent",
        "memory_bytes",
        "latency_seconds",
        "error_rate",
    }


def test_alerts_endpoint_starts_empty() -> None:
    response = client.get("/alerts")
    assert response.status_code == 200
    assert response.json() == {"alerts": []}
