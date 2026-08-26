import asyncio
import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field

import httpx

from .config import settings
from .metrics_client import PrometheusClient

logger = logging.getLogger("predictor.monitor")

_STDDEV_EPSILON = 1e-9


def build_queries(job: str) -> dict[str, str]:
    return {
        "cpu_percent": f'rate(process_cpu_seconds_total{{job="{job}"}}[1m]) * 100',
        "memory_bytes": f'process_resident_memory_bytes{{job="{job}"}}',
        "latency_seconds": (
            f'sum(rate(http_request_duration_seconds_sum{{job="{job}"}}[1m])) / '
            f'sum(rate(http_request_duration_seconds_count{{job="{job}"}}[1m]))'
        ),
        "error_rate": (
            f'sum(rate(http_requests_total{{job="{job}", status=~"5.."}}[1m])) / '
            f'sum(rate(http_requests_total{{job="{job}"}}[1m]))'
        ),
    }


@dataclass
class Evaluation:
    value: float
    mean: float
    stddev: float
    z_score: float
    breached: bool


def evaluate_metric(window: deque, value: float) -> Evaluation:
    """Compare `value` against the rolling baseline in `window`, then append it."""
    if len(window) >= settings.min_samples:
        mean = statistics.fmean(window)
        stddev = statistics.pstdev(window)
        z_score = (value - mean) / stddev if stddev > _STDDEV_EPSILON else 0.0
    else:
        mean, stddev, z_score = value, 0.0, 0.0

    window.append(value)
    breached = z_score >= settings.threshold_sigma
    return Evaluation(value=value, mean=mean, stddev=stddev, z_score=z_score, breached=breached)


@dataclass
class Alert:
    metric: str
    value: float
    mean: float
    stddev: float
    z_score: float
    fired_at: float


@dataclass
class MetricState:
    window: deque = field(default_factory=lambda: deque(maxlen=settings.window_size))
    last_value: float | None = None
    last_z_score: float = 0.0
    alerting: bool = False
    last_alert_at: float = 0.0


class RiskMonitor:
    """Polls Prometheus for a target job's metrics and flags rolling-baseline breaches."""

    def __init__(self, prometheus: PrometheusClient, job: str) -> None:
        self._prometheus = prometheus
        self._queries = build_queries(job)
        self._states: dict[str, MetricState] = {name: MetricState() for name in self._queries}
        self._alerts: deque[Alert] = deque(maxlen=settings.max_alerts)

    @property
    def alerts(self) -> list[Alert]:
        return list(self._alerts)

    def snapshot(self) -> dict[str, dict]:
        return {
            name: {
                "value": state.last_value,
                "z_score": round(state.last_z_score, 3),
                "alerting": state.alerting,
                "samples": len(state.window),
            }
            for name, state in self._states.items()
        }

    def overall_risk(self) -> float:
        if not self._states:
            return 0.0
        peak_z_score = max(state.last_z_score for state in self._states.values())
        return round(max(0.0, peak_z_score) / settings.threshold_sigma, 3)

    async def poll_once(self) -> None:
        for name, query in self._queries.items():
            try:
                value = await self._prometheus.instant_query(query)
            except httpx.HTTPError as exc:
                logger.warning("prometheus query failed metric=%s error=%s", name, exc)
                continue
            if value is None:
                continue
            self._evaluate(name, value)

    def _evaluate(self, name: str, value: float) -> None:
        state = self._states[name]
        result = evaluate_metric(state.window, value)
        state.last_value = result.value
        state.last_z_score = result.z_score

        now = time.monotonic()
        if result.breached:
            if not state.alerting and (now - state.last_alert_at) >= settings.alert_cooldown_seconds:
                state.alerting = True
                state.last_alert_at = now
                self._fire_alert(name, result)
        else:
            state.alerting = False

    def _fire_alert(self, name: str, result: Evaluation) -> None:
        alert = Alert(
            metric=name,
            value=result.value,
            mean=result.mean,
            stddev=result.stddev,
            z_score=result.z_score,
            fired_at=time.time(),
        )
        self._alerts.append(alert)
        logger.warning(
            "ALERT risk threshold crossed metric=%s value=%.4f mean=%.4f stddev=%.4f z_score=%.2f",
            name,
            result.value,
            result.mean,
            result.stddev,
            result.z_score,
        )

    async def run_forever(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(settings.poll_interval_seconds)
