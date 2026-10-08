import asyncio
import time
from typing import Any
import httpx
import pytest

from services.api.db import IncidentStore, STAGE_LEVELS, incident_id, stage
from services.api.sync import IncidentSync, incident_stage_level
from services.remediator.engine import Remediation, RemediationEngine
from services.remediator.k8s_client import K8sClient
from services.remediator.argocd_client import ArgocdClient
from services.remediator.slack_client import SlackClient
from services.remediator.verifier import HealthVerifier, PrometheusClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _mock_transport(base_url: str, handler):
    return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))


def _make_remediation(metric: str = "error_rate", auto: bool = True) -> Remediation:
    return Remediation(
        id="rem-12345",
        alert={"metric": metric, "value": 0.5, "fired_at": 1700000000.0},
        runbook_id="error-rate-bad-deploy",
        action_text="roll back to previous revision",
        category="rollback",
        auto=auto,
        status="pending",
        target_workload="demo-api",
    )


@pytest.mark.anyio
async def test_successful_verification_resolves_incident() -> None:
    """Requirement 9A: Remediation executes -> verification begins -> metrics recover -> RESOLVED."""
    def k8s_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": {"readyReplicas": 1, "unavailableReplicas": 0}, "spec": {"replicas": 1}})

    def prom_handler(request: httpx.Request) -> httpx.Response:
        # Returns healthy error rate 0.01 (< 0.05)
        return httpx.Response(200, json={"data": {"result": [{"value": [1700000000, "0.01"]}]}})

    def workload_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    k8s = K8sClient("http://k8s:6443", token="tok", namespace="sentinel")
    k8s._client = _mock_transport("http://k8s:6443", k8s_handler)

    prom = PrometheusClient("http://prom:9090")
    prom._client = _mock_transport("http://prom:9090", prom_handler)

    verifier = HealthVerifier(
        k8s=k8s,
        prometheus=prom,
        workload_url="http://demo-api:8080",
        delay_seconds=0.001,
        interval_seconds=0.001,
        max_attempts=3,
    )
    verifier._http_client = _mock_transport("http://demo-api:8080", workload_handler)

    remediation = _make_remediation(metric="error_rate")
    success = await verifier.verify(remediation)

    assert success is True
    assert remediation.status == "resolved"
    assert remediation.verification_status == "resolved"
    assert remediation.verification_result == "healthy"
    assert remediation.verification_attempt == 1
    assert remediation.resolved_at is not None
    assert remediation.verification_details["signals"]["prometheus_error_rate_healthy"] is True

    await verifier.aclose()
    await k8s.aclose()


@pytest.mark.anyio
async def test_failed_verification_escalates_incident() -> None:
    """Requirement 9B: Remediation executes -> metrics remain unhealthy -> retries -> FAILED_VERIFICATION & ESCALATED."""
    slack_messages = []

    def k8s_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": {"readyReplicas": 1}, "spec": {"replicas": 1}})

    def prom_handler(request: httpx.Request) -> httpx.Response:
        # Stays above error rate threshold 0.05
        return httpx.Response(200, json={"data": {"result": [{"value": [1700000000, "0.25"]}]}})

    def slack_handler(request: httpx.Request) -> httpx.Response:
        slack_messages.append(request.read().decode())
        return httpx.Response(200, json={"ok": True})

    k8s = K8sClient("http://k8s:6443", token="tok", namespace="sentinel")
    k8s._client = _mock_transport("http://k8s:6443", k8s_handler)

    prom = PrometheusClient("http://prom:9090")
    prom._client = _mock_transport("http://prom:9090", prom_handler)

    slack = SlackClient("tok")
    slack._client = _mock_transport("https://slack.com", slack_handler)

    verifier = HealthVerifier(
        k8s=k8s,
        prometheus=prom,
        delay_seconds=0.001,
        interval_seconds=0.001,
        max_attempts=3,
    )

    remediation = _make_remediation(metric="error_rate")
    remediation.slack_channel = "#sentinel-incidents"
    success = await verifier.verify(remediation, slack=slack)

    assert success is False
    assert remediation.status == "escalated"
    assert remediation.verification_status == "failed_verification"
    assert remediation.verification_result == "unhealthy"
    assert remediation.verification_attempt == 3
    assert "Health verification failed after 3 attempts" in remediation.failure_reason
    assert remediation.escalated_at is not None
    assert len(slack_messages) == 1
    assert "Remediation Verification Failed" in slack_messages[0]

    await verifier.aclose()
    await k8s.aclose()
    await slack.aclose()


@pytest.mark.anyio
async def test_recovery_during_retry() -> None:
    """Requirement 9C: Attempt 1 fails, attempt 2 recovers -> incident becomes RESOLVED."""
    call_count = {"count": 0}

    async def custom_checker(rem: Any, attempt: int) -> bool:
        call_count["count"] += 1
        return attempt >= 2  # False on attempt 1, True on attempt 2

    verifier = HealthVerifier(
        delay_seconds=0.001,
        interval_seconds=0.001,
        max_attempts=4,
        custom_checker=custom_checker,
    )

    remediation = _make_remediation()
    success = await verifier.verify(remediation)

    assert success is True
    assert remediation.status == "resolved"
    assert remediation.verification_status == "resolved"
    assert remediation.verification_attempt == 2
    assert call_count["count"] == 2


@pytest.mark.anyio
async def test_verification_max_attempts_limit() -> None:
    """Requirement 9D: Workload never recovers -> stops after configured limit."""
    call_count = {"count": 0}

    async def custom_checker(rem: Any, attempt: int) -> bool:
        call_count["count"] += 1
        return False

    verifier = HealthVerifier(
        delay_seconds=0.001,
        interval_seconds=0.001,
        max_attempts=2,
        custom_checker=custom_checker,
    )

    remediation = _make_remediation()
    success = await verifier.verify(remediation)

    assert success is False
    assert remediation.verification_attempt == 2
    assert call_count["count"] == 2
    assert remediation.verification_status == "failed_verification"


def test_state_transitions_and_stage_derivation() -> None:
    """Requirement 9E: Verify all state transitions and stage derivation."""
    assert stage({"remediation_status": "remediation_started"}) == "remediation_started"
    assert stage({"remediation_status": "verifying"}) == "verifying"
    assert stage({"remediation_status": "resolved"}) == "resolved"
    assert stage({"remediation_status": "failed_verification"}) == "failed_verification"
    assert stage({"remediation_status": "escalated"}) == "escalated"
    assert stage({"remediation_status": "executed"}) == "remediated"
    assert stage({"remediation_status": "denied"}) == "denied"
    assert stage({"remediation_status": "failed"}) == "failed"
    assert stage({"remediation_status": "awaiting_approval"}) == "awaiting_approval"
    assert stage({"remediation_status": None, "diagnosed_at": 100.0}) == "diagnosed"
    assert stage({"remediation_status": None, "diagnosed_at": None}) == "predicted"

    # All stages have numeric representation in STAGE_LEVELS
    for stg in [
        "predicted", "diagnosed", "awaiting_approval", "denied",
        "remediation_started", "remediated", "verifying", "resolved",
        "failed_verification", "escalated", "failed"
    ]:
        assert stg in STAGE_LEVELS


@pytest.mark.anyio
async def test_remediation_engine_closed_loop_execution(tmp_path) -> None:
    """Full closed-loop test: RemediationEngine + HealthVerifier end-to-end."""
    k8s_calls = []

    def k8s_handler(request: httpx.Request) -> httpx.Response:
        k8s_calls.append(request.method)
        return httpx.Response(200, json={"status": {"readyReplicas": 1}, "spec": {"replicas": 1}})

    def argocd_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "Synced"})

    k8s = K8sClient("http://k8s:6443", token="tok", namespace="sentinel")
    k8s._client = _mock_transport("http://k8s:6443", k8s_handler)

    argocd = ArgocdClient("http://argocd:80")
    argocd._client = _mock_transport("http://argocd:80", argocd_handler)

    slack = SlackClient("tok")

    async def instant_healthy(rem: Any, attempt: int) -> bool:
        return True

    verifier = HealthVerifier(
        delay_seconds=0.001,
        interval_seconds=0.001,
        max_attempts=3,
        custom_checker=instant_healthy,
    )

    engine = RemediationEngine(
        k8s=k8s,
        argocd=argocd,
        slack=slack,
        target_deployment="demo-api",
        argocd_app="sentinel",
        slack_channel="#incidents",
        scale_step=1,
        max_replicas=5,
        verifier=verifier,
        wait_for_verification=True,
    )

    diagnosis = {
        "grounded": True,
        "runbook_id": "restart-runbook",
        "recommended_action": "restart the deployment",
        "approval_required": False,
        "alert": {"metric": "cpu_percent", "value": 95.0, "fired_at": 1700000000.0},
    }

    remediation = await engine.process_diagnosis(diagnosis)
    assert remediation is not None
    assert remediation.status == "resolved"
    assert remediation.verification_status == "resolved"
    assert remediation.verification_result == "healthy"
    assert "restarted deployment/demo-api" in remediation.result

    # Check store integration
    store = IncidentStore(str(tmp_path / "test.db"))
    iid = store.upsert_remediation({
        "id": remediation.id,
        "alert": remediation.alert,
        "category": remediation.category,
        "auto": True,
        "status": remediation.status,
        "result": remediation.result,
        "resolved_at": remediation.resolved_at,
        "verification_status": remediation.verification_status,
        "verification_attempt": remediation.verification_attempt,
        "verification_result": remediation.verification_result,
        "verification_details": remediation.verification_details,
    })

    incident = store.get(iid)
    assert incident is not None
    assert incident["stage"] == "resolved"
    assert incident["status"] == "resolved"
    assert incident["verification_status"] == "resolved"
    assert incident["verification_attempt"] == 1
    assert incident["verification_result"] == "healthy"

    await verifier.aclose()
    await k8s.aclose()
    await argocd.aclose()
    await slack.aclose()
