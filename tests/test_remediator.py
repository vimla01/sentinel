import hashlib
import hmac
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from services.remediator.argocd_client import ArgocdClient
from services.remediator.engine import RemediationEngine
from services.remediator.k8s_client import K8sClient
from services.remediator.main import app
from services.remediator.policy import classify, should_auto_execute
from services.remediator.slack_client import SlackClient, verify_signature

client = TestClient(app)

_GROUNDED_RESTART = {
    "alert": {"metric": "memory_bytes", "value": 5e8, "fired_at": 1700000000.0},
    "grounded": True,
    "runbook_id": "memory-leak-unbounded-growth",
    "recommended_action": "restart the affected pod",
    "safe_actions": ["restart the affected pod"],
    "approval_required": False,
}

_GROUNDED_NEEDS_APPROVAL = {
    "alert": {"metric": "error_rate", "value": 0.5, "fired_at": 1700000001.0},
    "grounded": True,
    "runbook_id": "error-rate-bad-deploy",
    "recommended_action": "roll back to the previous revision",
    "safe_actions": [],
    "approval_required": True,
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _mock_transport(base_url: str, handler):
    return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))


def _engine(k8s_handler=None, argocd_handler=None, slack_handler=None) -> RemediationEngine:
    k8s = K8sClient("http://k8s:6443", token="tok", namespace="sentinel")
    if k8s_handler:
        k8s._client = _mock_transport("http://k8s:6443", k8s_handler)
    argocd = ArgocdClient("http://argocd:80")
    if argocd_handler:
        argocd._client = _mock_transport("http://argocd:80", argocd_handler)
    slack = SlackClient("xoxb-test")
    if slack_handler:
        slack._client = _mock_transport("https://slack.com", slack_handler)
    return RemediationEngine(
        k8s=k8s,
        argocd=argocd,
        slack=slack,
        target_deployment="demo-api",
        argocd_app="sentinel",
        slack_channel="#incidents",
        scale_step=1,
        max_replicas=5,
    )


def test_classify_matches_hardcoded_categories() -> None:
    assert classify("restart the affected pod") == "restart"
    assert classify("Scale the deployment up by one replica") == "scale"
    assert classify("roll back to the previous revision") == "rollback"
    assert classify("roll-back immediately") == "rollback"
    assert classify("page the on-call engineer") == "unknown"


def test_should_auto_execute_requires_both_approval_flag_and_safe_category() -> None:
    assert should_auto_execute(_GROUNDED_RESTART) is True
    # approval_required True always wins, even though the text says "roll back".
    assert should_auto_execute(_GROUNDED_NEEDS_APPROVAL) is False
    unknown_action = {**_GROUNDED_RESTART, "recommended_action": "page the on-call engineer"}
    assert should_auto_execute(unknown_action) is False


def test_verify_signature_accepts_valid_and_rejects_tampered() -> None:
    secret = "shhh"
    timestamp = str(int(time.time()))
    body = "payload=%7B%7D"
    basestring = f"v0:{timestamp}:{body}".encode()
    signature = "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()

    assert verify_signature(secret, timestamp, body, signature) is True
    assert verify_signature(secret, timestamp, body, signature + "tampered") is False
    assert verify_signature("wrong-secret", timestamp, body, signature) is False


def test_verify_signature_rejects_stale_timestamp() -> None:
    secret = "shhh"
    old_timestamp = str(int(time.time()) - 600)
    body = "payload=%7B%7D"
    basestring = f"v0:{old_timestamp}:{body}".encode()
    signature = "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()

    assert verify_signature(secret, old_timestamp, body, signature) is False


@pytest.mark.anyio
async def test_engine_auto_executes_restart_for_safe_ungoverned_action() -> None:
    patched = {}

    def k8s_handler(request: httpx.Request) -> httpx.Response:
        patched["method"] = request.method
        patched["url"] = str(request.url)
        return httpx.Response(200, json={"status": "ok"})

    def slack_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Slack must not be called for an auto-executed remediation")

    engine = _engine(k8s_handler=k8s_handler, slack_handler=slack_handler)
    remediation = await engine.process_diagnosis(_GROUNDED_RESTART)

    assert remediation.auto is True
    assert remediation.category == "restart"
    assert remediation.status == "executed"
    assert "demo-api" in remediation.result
    assert patched["method"] == "PATCH"
    assert "deployments/demo-api" in patched["url"]
    assert remediation in engine.remediations


@pytest.mark.anyio
async def test_engine_requests_slack_approval_when_approval_required() -> None:
    def k8s_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("K8s must not be touched before a human approves")

    def slack_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat.postMessage"
        return httpx.Response(200, json={"ok": True, "channel": "#incidents", "ts": "123.456"})

    engine = _engine(k8s_handler=k8s_handler, slack_handler=slack_handler)
    remediation = await engine.process_diagnosis(_GROUNDED_NEEDS_APPROVAL)

    assert remediation.auto is False
    assert remediation.status == "awaiting_approval"
    assert remediation.slack_channel == "#incidents"
    assert remediation.slack_ts == "123.456"


@pytest.mark.anyio
async def test_engine_resolve_executes_rollback_only_after_approval() -> None:
    executed = {"called": False}

    def argocd_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"status": {"history": [{"id": 1, "revision": "abc"}, {"id": 2, "revision": "def"}]}},
            )
        executed["called"] = True
        return httpx.Response(200, json={})

    def slack_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "channel": "#incidents", "ts": "999.111"})

    engine = _engine(argocd_handler=argocd_handler, slack_handler=slack_handler)
    remediation = await engine.process_diagnosis(_GROUNDED_NEEDS_APPROVAL)
    assert remediation.status == "awaiting_approval"
    assert executed["called"] is False

    resolved = await engine.resolve(remediation.id, approved=True, actor="alice")

    assert executed["called"] is True
    assert resolved.status == "executed"
    assert "sentinel" in resolved.result


@pytest.mark.anyio
async def test_engine_resolve_denies_without_touching_the_cluster() -> None:
    def argocd_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("ArgoCD must not be called when a remediation is denied")

    def slack_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "channel": "#incidents", "ts": "999.111"})

    engine = _engine(argocd_handler=argocd_handler, slack_handler=slack_handler)
    remediation = await engine.process_diagnosis(_GROUNDED_NEEDS_APPROVAL)

    resolved = await engine.resolve(remediation.id, approved=False, actor="bob")

    assert resolved.status == "denied"
    assert "bob" in resolved.result


@pytest.mark.anyio
async def test_engine_skips_ungrounded_diagnoses() -> None:
    engine = _engine()
    remediation = await engine.process_diagnosis({"grounded": False, "recommended_action": ""})
    assert remediation is None
    assert engine.remediations == []


@pytest.mark.anyio
async def test_k8s_client_scale_reads_current_replicas_before_patching() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"spec": {"replicas": 2}})
        import json as _json

        body = _json.loads(request.content)
        assert body == {"spec": {"replicas": 3}}
        return httpx.Response(200, json={"spec": {"replicas": 3}})

    k8s = K8sClient("http://k8s:6443", token="tok", namespace="sentinel")
    k8s._client = _mock_transport("http://k8s:6443", handler)

    await k8s.scale_deployment("demo-api", step=1, max_replicas=5)
    assert calls == ["GET", "PATCH"]


@pytest.mark.anyio
async def test_k8s_client_scale_caps_at_max_replicas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"spec": {"replicas": 5}})
        import json as _json

        body = _json.loads(request.content)
        assert body == {"spec": {"replicas": 5}}
        return httpx.Response(200, json={"spec": {"replicas": 5}})

    k8s = K8sClient("http://k8s:6443", token="tok", namespace="sentinel")
    k8s._client = _mock_transport("http://k8s:6443", handler)

    await k8s.scale_deployment("demo-api", step=1, max_replicas=5)


@pytest.mark.anyio
async def test_argocd_client_rollback_raises_without_previous_revision() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": {"history": [{"id": 1, "revision": "abc"}]}})

    argocd = ArgocdClient("http://argocd:80")
    argocd._client = _mock_transport("http://argocd:80", handler)

    with pytest.raises(ValueError):
        await argocd.rollback("sentinel")


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_remediations_endpoint_starts_empty() -> None:
    response = client.get("/remediations")
    assert response.status_code == 200
    assert response.json() == {"remediations": []}


def test_slack_interactions_rejects_bad_signature() -> None:
    response = client.post(
        "/slack/interactions",
        headers={"X-Slack-Request-Timestamp": str(int(time.time())), "X-Slack-Signature": "v0=bogus"},
        content=b"payload=%7B%7D",
    )
    assert response.status_code == 401
