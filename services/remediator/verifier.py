import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx
from prometheus_client import Counter, REGISTRY

from .k8s_client import K8sClient
from .slack_client import SlackClient

logger = logging.getLogger("remediator.verifier")

if "sentinel_remediation_verification_total" not in REGISTRY._names_to_collectors:
    VERIFICATION_TOTAL = Counter(
        "sentinel_remediation_verification_total",
        "Total post-remediation health verifications evaluated",
        ["target", "result"],
    )
else:
    VERIFICATION_TOTAL = REGISTRY._names_to_collectors[
        "sentinel_remediation_verification_total"
    ]


class PrometheusClient:
    """Queries Prometheus instant query API for post-remediation verification."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def instant_query(self, promql: str) -> float | None:
        """Executes an instant PromQL query and returns the first float value."""
        try:
            resp = await self._client.get("/api/v1/query", params={"query": promql})
            resp.raise_for_status()
            data = resp.json().get("data", {}).get("result", [])
            if data and len(data) > 0:
                val = data[0].get("value")
                if val and len(val) > 1:
                    return float(val[1])
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.debug("Prometheus query '%s' failed: %s", promql, exc)
        return None

    async def aclose(self) -> None:
        """Closes the underlying HTTP client."""
        await self._client.aclose()


@dataclass
class VerificationAttemptResult:
    """Result of a single verification attempt."""

    attempt: int
    healthy: bool
    signals: dict[str, Any]
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


class HealthVerifier:
    """Verifies that a remediated workload has recovered and stabilized.

    Lifecycle:
    REMEDIATION_STARTED -> VERIFYING -> RESOLVED | FAILED_VERIFICATION -> ESCALATED
    """

    def __init__(
        self,
        k8s: K8sClient | None = None,
        prometheus: PrometheusClient | None = None,
        workload_url: str | None = None,
        delay_seconds: float = 5.0,
        interval_seconds: float = 3.0,
        max_attempts: int = 3,
        error_rate_threshold: float = 0.05,
        latency_threshold_seconds: float = 0.5,
        cpu_threshold_percent: float = 80.0,
        memory_threshold_bytes: float = 500 * 1024 * 1024,
        custom_checker: Callable[..., Awaitable[bool]] | None = None,
    ) -> None:
        self.k8s = k8s
        self.prometheus = prometheus
        self.workload_url = workload_url
        self.delay_seconds = delay_seconds
        self.interval_seconds = interval_seconds
        self.max_attempts = max_attempts
        self.error_rate_threshold = error_rate_threshold
        self.latency_threshold_seconds = latency_threshold_seconds
        self.cpu_threshold_percent = cpu_threshold_percent
        self.memory_threshold_bytes = memory_threshold_bytes
        self.custom_checker = custom_checker
        self._http_client = httpx.AsyncClient(timeout=5.0)

    async def verify(
        self,
        remediation: Any,
        slack: SlackClient | None = None,
    ) -> bool:
        """Runs the verification retry loop.

        Updates remediation fields and returns True if healthy, False if failed.
        """
        remediation.status = "verifying"
        remediation.verification_status = "verifying"
        remediation.verification_result = "pending"
        target_workload = (
            getattr(remediation, "target_workload", "demo-api") or "demo-api"
        )
        action = getattr(remediation, "action_executed", remediation.category)

        logger.info(
            "VERIFICATION_STARTED id=%s workload=%s action=%s delay=%.2fs max_attempts=%d",
            remediation.id,
            target_workload,
            action,
            self.delay_seconds,
            self.max_attempts,
        )

        # 1. Stabilization delay
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        start_time = time.time()
        last_reason = ""

        for attempt in range(1, self.max_attempts + 1):
            remediation.verification_attempt = attempt
            attempt_result = await self._check_signals(remediation, attempt)

            logger.info(
                "VERIFICATION_ATTEMPT attempt=%d/%d id=%s healthy=%s signals=%s reason=%s",
                attempt,
                self.max_attempts,
                remediation.id,
                attempt_result.healthy,
                attempt_result.signals,
                attempt_result.reason,
            )

            if attempt_result.healthy:
                duration = time.time() - start_time
                remediation.status = "resolved"
                remediation.verification_status = "resolved"
                remediation.verification_result = "healthy"
                remediation.resolved_at = time.time()
                remediation.verification_details = {
                    "attempt": attempt,
                    "duration_seconds": round(duration, 2),
                    "signals": attempt_result.signals,
                }
                logger.info(
                    "VERIFICATION_SUCCESS id=%s on attempt %d (duration=%.2fs) - incident RESOLVED",
                    remediation.id,
                    attempt,
                    duration,
                )
                try:
                    VERIFICATION_TOTAL.labels(
                        target=target_workload, result="resolved"
                    ).inc()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
                if slack and remediation.slack_channel and remediation.slack_ts:
                    try:
                        await slack.update_message(
                            remediation.slack_channel,
                            remediation.slack_ts,
                            (
                                f"Approved & Verified — RESOLVED on attempt {attempt}: "
                                f"{remediation.result}"
                            ),
                        )
                    except (httpx.HTTPError, RuntimeError):
                        logger.debug("Failed to update Slack on resolution")
                return True

            last_reason = attempt_result.reason
            remediation.verification_details = {
                "attempt": attempt,
                "signals": attempt_result.signals,
                "last_reason": last_reason,
            }

            if attempt < self.max_attempts and self.interval_seconds > 0:
                await asyncio.sleep(self.interval_seconds)

        # Retries exhausted -> FAILED_VERIFICATION -> ESCALATED
        remediation.status = "failed_verification"
        remediation.verification_status = "failed_verification"
        remediation.verification_result = "unhealthy"
        remediation.failure_reason = f"Health verification failed after {self.max_attempts} attempts: {last_reason}"
        remediation.resolved_at = time.time()
        try:
            VERIFICATION_TOTAL.labels(
                target=target_workload, result="failed_verification"
            ).inc()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        logger.warning(
            "VERIFICATION_FAILED id=%s after %d attempts: %s",
            remediation.id,
            self.max_attempts,
            remediation.failure_reason,
        )

        await self._escalate(remediation, slack)
        return False

    async def _check_k8s_readiness(
        self, dep_name: str, signals: dict[str, Any], unhealthy: list[str]
    ) -> None:
        """Verifies deployment replica readiness."""
        if not self.k8s:
            return
        try:
            dep = await self.k8s.get_deployment(dep_name)
            spec_replicas = dep.get("spec", {}).get("replicas", 1)
            status = dep.get("status", {})
            ready_replicas = status.get("readyReplicas", 0)
            unavailable = status.get("unavailableReplicas", 0)

            signals["k8s_ready_replicas"] = ready_replicas
            signals["k8s_spec_replicas"] = spec_replicas
            if ready_replicas < spec_replicas or unavailable:
                unhealthy.append(
                    f"k8s deployment not ready ({ready_replicas}/{spec_replicas} ready)"
                )
            else:
                signals["k8s_status"] = "ready"
        except (httpx.HTTPError, KeyError) as exc:
            signals["k8s_error"] = str(exc)

    async def _check_http_healthz(
        self, signals: dict[str, Any], unhealthy: list[str]
    ) -> None:
        """Verifies HTTP healthz endpoint returns 200 OK."""
        if not self.workload_url:
            return
        try:
            url = f"{self.workload_url.rstrip('/')}/healthz"
            resp = await self._http_client.get(url)
            signals["http_healthz_status"] = resp.status_code
            if resp.status_code != 200:
                unhealthy.append(f"HTTP healthz status={resp.status_code}")
            else:
                signals["http_healthz"] = "ok"
        except httpx.HTTPError as exc:
            signals["http_healthz_error"] = str(exc)
            unhealthy.append(f"HTTP healthz unreachable: {exc}")

    async def _check_prometheus_metrics(
        self, remediation: Any, signals: dict[str, Any], unhealthy: list[str]
    ) -> None:
        """Queries Prometheus for the metric that triggered the incident."""
        if not self.prometheus:
            return
        alert = getattr(remediation, "alert", {}) or {}
        metric = alert.get("metric")
        job = getattr(remediation, "target_workload", "demo-api") or "demo-api"
        query_map = {
            "error_rate": (
                f'sum(rate(http_requests_total{{job="{job}", status=~"5.."}}[1m])) / '
                f'sum(rate(http_requests_total{{job="{job}"}}[1m]))',
                self.error_rate_threshold,
            ),
            "latency_seconds": (
                f'sum(rate(http_request_duration_seconds_sum{{job="{job}"}}[1m])) / '
                f'sum(rate(http_request_duration_seconds_count{{job="{job}"}}[1m]))',
                self.latency_threshold_seconds,
            ),
            "cpu_percent": (
                f'rate(process_cpu_seconds_total{{job="{job}"}}[1m]) * 100',
                self.cpu_threshold_percent,
            ),
            "memory_bytes": (
                f'process_resident_memory_bytes{{job="{job}"}}',
                self.memory_threshold_bytes,
            ),
        }
        if metric in query_map:
            promql, threshold = query_map[metric]
            val = await self.prometheus.instant_query(promql)
            signals[f"prometheus_{metric}"] = val
            if val is not None:
                if val > threshold:
                    unhealthy.append(
                        f"metric {metric}={val:.4f} > threshold {threshold}"
                    )
                else:
                    signals[f"prometheus_{metric}_healthy"] = True

    async def _check_signals(
        self, remediation: Any, attempt: int
    ) -> VerificationAttemptResult:
        """Evaluates health signals across K8s, HTTP healthz, and Prometheus."""
        if self.custom_checker:
            try:
                healthy = await self.custom_checker(remediation, attempt)
                return VerificationAttemptResult(
                    attempt=attempt,
                    healthy=healthy,
                    signals={"custom": healthy},
                    reason="" if healthy else "custom check returned unhealthy",
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                return VerificationAttemptResult(
                    attempt=attempt,
                    healthy=False,
                    signals={"custom": False},
                    reason=f"custom checker error: {exc}",
                )

        signals: dict[str, Any] = {}
        unhealthy: list[str] = []
        dep_name = getattr(remediation, "target_workload", "demo-api") or "demo-api"

        await self._check_k8s_readiness(dep_name, signals, unhealthy)
        await self._check_http_healthz(signals, unhealthy)
        await self._check_prometheus_metrics(remediation, signals, unhealthy)

        healthy = len(unhealthy) == 0
        return VerificationAttemptResult(
            attempt=attempt,
            healthy=healthy,
            signals=signals,
            reason="; ".join(unhealthy) if not healthy else "",
        )

    async def _escalate(self, remediation: Any, slack: SlackClient | None) -> None:
        """Transitions remediation to escalated status and alerts Slack."""
        remediation.status = "escalated"
        remediation.escalated_at = time.time()
        logger.warning(
            "INCIDENT_ESCALATED id=%s target=%s reason=%s",
            remediation.id,
            getattr(remediation, "target_workload", "demo-api"),
            remediation.failure_reason,
        )

        if slack:
            channel = remediation.slack_channel or "#sentinel-incidents"
            escalation_text = (
                f":rotating_light: *Remediation Verification Failed — Incident Escalated*\n"
                f"• *Remediation ID*: `{remediation.id}`\n"
                f"• *Target Workload*: `{getattr(remediation, 'target_workload', 'demo-api')}`\n"
                f"• *Metric*: `{remediation.alert.get('metric', 'unknown')}`\n"
                f"• *Action Executed*: `{remediation.action_text}`\n"
                f"• *Attempts*: {remediation.verification_attempt}\n"
                f"• *Reason*: {remediation.failure_reason}\n"
                f"_Automated remediation did not resolve the incident. Human intervention required._"
            )
            try:
                if remediation.slack_channel and remediation.slack_ts:
                    await slack.update_message(
                        remediation.slack_channel,
                        remediation.slack_ts,
                        escalation_text,
                    )
                else:
                    await slack.post_message(channel, escalation_text)
            except (httpx.HTTPError, RuntimeError) as exc:
                logger.warning("Failed to post Slack escalation: %s", exc)

    async def aclose(self) -> None:
        """Releases all network resources."""
        await self._http_client.aclose()
        if self.prometheus:
            await self.prometheus.aclose()
