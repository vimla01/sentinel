import hashlib
import hmac
import subprocess
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from services.remediator.argocd_client import ArgocdClient
from services.remediator.engine import RemediationEngine
from services.remediator.git_client import GitClient
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


def _engine(k8s_handler=None, argocd_handler=None, slack_handler=None, git=None) -> RemediationEngine:
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
        git=git,
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


def test_git_client_is_git_repo(tmp_path) -> None:
    non_git = GitClient(str(tmp_path))
    assert non_git.is_git_repo() is False

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    git_repo = GitClient(str(tmp_path))
    assert git_repo.is_git_repo() is True


def test_git_client_rollback_and_scale(tmp_path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "tester"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "tester@test.local"], check=True)

    app_dir = tmp_path / "infra" / "k8s" / "apps" / "demo-api"
    app_dir.mkdir(parents=True)
    deploy_file = app_dir / "deployment.yaml"
    deploy_file.write_text("replicas: 1\nimage: demo-api:v1\n")

    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "initial v1"], check=True)
    rev1 = (
        subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
    )

    # Modify to bad image
    deploy_file.write_text("replicas: 1\nimage: demo-api:v2-bad\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "bad v2"], check=True)

    git = GitClient(str(tmp_path))
    new_rev = git.rollback_deployment("demo-api", rev1)
    assert new_rev != ""
    assert "image: demo-api:v1" in deploy_file.read_text()

    scale_rev = git.scale_deployment("demo-api", 3)
    assert scale_rev != ""
    assert "replicas: 3" in deploy_file.read_text()


@pytest.mark.anyio
async def test_engine_git_native_rollback(tmp_path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "tester"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "tester@test.local"], check=True)

    app_dir = tmp_path / "infra" / "k8s" / "apps" / "demo-api"
    app_dir.mkdir(parents=True)
    deploy_file = app_dir / "deployment.yaml"
    deploy_file.write_text("replicas: 1\nimage: demo-api:v1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "initial v1"], check=True)
    rev1 = (
        subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
    )

    deploy_file.write_text("replicas: 1\nimage: demo-api:v2-broken\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "broken deploy"], check=True)

    git = GitClient(str(tmp_path))

    executed = {"sync_called": False}

    def argocd_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"status": {"history": [{"id": 1, "revision": rev1}, {"id": 2, "revision": "def"}]}},
            )
        if "/sync" in request.url.path:
            executed["sync_called"] = True
            return httpx.Response(200, json={"status": "Synced"})
        return httpx.Response(200, json={})

    def slack_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "channel": "#incidents", "ts": "999.111"})

    engine = _engine(argocd_handler=argocd_handler, slack_handler=slack_handler, git=git)
    remediation = await engine.process_diagnosis(_GROUNDED_NEEDS_APPROVAL)
    resolved = await engine.resolve(remediation.id, approved=True, actor="alice")

    assert resolved.status == "executed"
    assert "sentinel" in resolved.result
    assert "image: demo-api:v1" in deploy_file.read_text()


def test_git_client_errors_when_not_git_repo(tmp_path) -> None:
    git = GitClient(str(tmp_path))
    with pytest.raises(RuntimeError, match="not a valid git repository"):
        git.rollback_deployment("demo-api", "rev1")

    with pytest.raises(RuntimeError, match="not a valid git repository"):
        git.scale_deployment("demo-api", 2)


def test_git_client_scale_deployment_missing_file_and_no_change(tmp_path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "tester"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "tester@test.local"], check=True)

    git = GitClient(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        git.scale_deployment("nonexistent", 3)

    app_dir = tmp_path / "infra" / "k8s" / "apps" / "demo-api"
    app_dir.mkdir(parents=True)
    deploy_file = app_dir / "deployment.yaml"
    deploy_file.write_text("replicas: 3\nimage: demo-api:v1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "initial v1"], check=True)

    # Scaling to same replicas returns "no change"
    res = git.scale_deployment("demo-api", 3)
    assert res == "no change"


@pytest.mark.anyio
async def test_argocd_client_sync_error_and_aclose() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    argocd = ArgocdClient("http://argocd:80")
    argocd._client = _mock_transport("http://argocd:80", handler)

    res = await argocd.sync("sentinel")
    assert res == {}

    await argocd.aclose()


@pytest.mark.anyio
async def test_argocd_client_rollback_git_error_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"status": {"history": [{"id": 1, "revision": "rev1"}, {"id": 2, "revision": "rev2"}]}},
            )
        return httpx.Response(200, json={})

    argocd = ArgocdClient("http://argocd:80")
    argocd._client = _mock_transport("http://argocd:80", handler)

    class BrokenGit:
        def is_git_repo(self):
            return True

        def rollback_deployment(self, name, rev):
            raise RuntimeError("simulated git error")

    res = await argocd.rollback("sentinel", git_client=BrokenGit())
    assert res["rolled_back_to"]["id"] == 1
