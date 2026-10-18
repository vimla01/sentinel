import asyncio
import hashlib
import hmac
import json
import os
import signal
import subprocess
import sys
import time

import httpx
import pytest

pytestmark = pytest.mark.integration


def check_env():
    import shutil

    if not shutil.which("kubectl"):
        pytest.skip("E2E prerequisites not met: kubectl not found")
    try:
        res = subprocess.run(
            ["kubectl", "get", "ns", "sentinel"], capture_output=True, text=True
        )
        if res.returncode != 0:
            pytest.skip(
                "E2E prerequisites not met: Kind cluster or sentinel namespace not available"
            )
    except Exception:
        pytest.skip(
            "E2E prerequisites not met: Kind cluster or sentinel namespace not available"
        )


@pytest.fixture(scope="module")
def port_forwards():
    check_env()

    # Start port forwards
    api_pf = subprocess.Popen(
        ["kubectl", "port-forward", "-n", "sentinel", "svc/api", "8083:8080"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    demo_api_pf = subprocess.Popen(
        ["kubectl", "port-forward", "-n", "sentinel", "svc/demo-api", "8081:8080"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    remediator_pf = subprocess.Popen(
        ["kubectl", "port-forward", "-n", "sentinel", "svc/remediator", "8082:8080"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Let them settle
    time.sleep(3)

    yield

    api_pf.kill()
    demo_api_pf.kill()
    remediator_pf.kill()


async def get_latest_incident(client):
    try:
        resp = await client.get("http://127.0.0.1:8083/api/v1/incidents/latest")
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def get_incident(client, incident_id):
    try:
        resp = await client.get(f"http://127.0.0.1:8083/api/v1/incidents/{incident_id}")
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def find_recent_incident(client, min_predicted_at):
    try:
        resp = await client.get("http://127.0.0.1:8083/api/v1/incidents")
        if resp.status_code == 200:
            for inc in resp.json().get("incidents", []):
                if inc.get("predicted_at", 0) >= min_predicted_at:
                    return inc
    except Exception:
        pass
    return None


def get_demo_api_restarts():
    res = subprocess.run(
        [
            "kubectl",
            "get",
            "pod",
            "-l",
            "app.kubernetes.io/name=demo-api",
            "-n",
            "sentinel",
            "-o",
            "jsonpath={.items[0].status.containerStatuses[0].restartCount}",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 and res.stdout.strip().isdigit():
        return int(res.stdout.strip())
    return 0


def get_demo_api_pod_name():
    res = subprocess.run(
        [
            "kubectl",
            "get",
            "pod",
            "-l",
            "app.kubernetes.io/name=demo-api",
            "-n",
            "sentinel",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        return res.stdout.strip()
    return ""


def get_demo_api_restarted_at():
    res = subprocess.run(
        [
            "kubectl",
            "get",
            "deployment",
            "demo-api",
            "-n",
            "sentinel",
            "-o",
            "jsonpath={.spec.template.metadata.annotations['kubectl\\.kubernetes\\.io/restartedAt']}",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        return res.stdout.strip()
    return ""


@pytest.mark.asyncio
async def test_full_incident_lifecycle(port_forwards):
    # Get initial deployment and pod state
    initial_restarts = get_demo_api_restarts()
    initial_pod = get_demo_api_pod_name()
    initial_restarted_at = get_demo_api_restarted_at()
    chaos_proc = None

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            old_incident = await get_latest_incident(client)
            old_incident_id = old_incident["id"] if old_incident else None

            # Inject memory leak
            chaos_proc = subprocess.Popen(
                [
                    sys.executable,
                    "scripts/chaos/inject_memory_leak.py",
                    "--base-url",
                    "http://127.0.0.1:8081",
                    "--chunk-mb",
                    "30",
                    "--steps",
                    "5",
                    "--interval-seconds",
                    "5.0",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            print("\nWaiting for incident to be predicted...")
            incident = None
            start_time = time.time()
            test_start = time.time()

            # Wait for prediction
            while time.time() - start_time < 120:
                incident = await find_recent_incident(client, test_start - 5)
                if incident:
                    break
                await asyncio.sleep(5)

            assert incident is not None, "Failed to get any incident within 120s"
            incident_id = incident["id"]

            print(f"Incident {incident_id} found. Waiting for diagnosis...")

            # Wait for diagnosis
            start_time = time.time()
            while time.time() - start_time < 120:
                incident = await get_incident(client, incident_id)
                if incident and incident.get("stage") in (
                    "diagnosed",
                    "awaiting_approval",
                    "remediation_started",
                    "remediated",
                    "verifying",
                    "resolved",
                    "escalated",
                ):
                    break
                await asyncio.sleep(5)

            assert incident.get("stage") in (
                "diagnosed",
                "awaiting_approval",
                "remediation_started",
                "remediated",
                "verifying",
                "resolved",
                "escalated",
            ), f"Incident stuck at {incident.get('stage')}"
            assert incident.get("runbook_id"), "Diagnosis should have a runbook_id"
            assert incident.get("grounded") is True, "Diagnosis should be grounded"

            print(
                f"Diagnosed with runbook {incident['runbook_id']}. Waiting for remediation creation..."
            )

            # Wait for remediation
            start_time = time.time()
            while time.time() - start_time < 60:
                incident = await get_incident(client, incident_id)
                if incident and incident.get("remediation_id"):
                    break
                await asyncio.sleep(5)

            # ------------------------------------------------------------
            # After diagnosis, locate the corresponding remediation via the remediator API.
            # ------------------------------------------------------------
            incident_metric = incident.get("metric")
            incident_fired = incident.get("predicted_at")
            incident_runbook = incident.get("runbook_id")
            remediation = None
            for _ in range(12):  # up to 60 s, poll every 5 s
                resp = await client.get("http://127.0.0.1:8082/remediations")
                if resp.status_code == 200:
                    for r in resp.json().get("remediations", []):
                        alert = r.get("alert", {})
                        if (
                            r.get("runbook_id") == incident_runbook
                            and alert.get("metric") == incident_metric
                            and alert.get("fired_at") == incident_fired
                        ):
                            remediation = r
                            break
                if remediation:
                    break
                await asyncio.sleep(5)

            if not remediation:
                pytest.fail("Could not find a matching remediation for the incident")

            remediation_id = remediation.get("id")
            remediation_status = remediation.get("status")
            remediation_category = remediation.get("category")
            remediation_result = remediation.get("result")

            if remediation_status == "awaiting_approval":
                print(
                    f"Remediation {remediation_id} needs approval. Simulating Slack approval..."
                )
                signing_secret = os.getenv("SENTINEL_E2E_SLACK_SECRET")
                if not signing_secret:
                    pytest.skip(
                        "SENTINEL_E2E_SLACK_SECRET not set; configure the live remediator with the same Slack signing secret for E2E test"
                    )
                ts = str(int(time.time()))
                payload = {
                    "actions": [{"action_id": "approve", "value": remediation_id}],
                    "user": {"username": "e2e-test-user"},
                }
                body = f"payload={json.dumps(payload)}"
                basestring = f"v0:{ts}:{body}".encode()
                signature = (
                    "v0="
                    + hmac.new(
                        signing_secret.encode(), basestring, hashlib.sha256
                    ).hexdigest()
                )
                resp = await client.post(
                    "http://127.0.0.1:8082/slack/interactions",
                    headers={
                        "X-Slack-Request-Timestamp": ts,
                        "X-Slack-Signature": signature,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    content=body.encode(),
                )
                assert resp.status_code == 200, f"Approval failed: {resp.text}"
                print("Approval sent successfully.")
            elif remediation_status in (
                "remediation_started",
                "executed",
                "verifying",
                "resolved",
            ):
                # Automatic remediation – verify category and result
                assert (
                    remediation_category == "restart"
                ), f"Automatic remediation category expected 'restart', got {remediation_category}"
                print(
                    f"Automatic remediation {remediation_id} status: {remediation_status}."
                )
            else:
                pytest.fail(f"Unexpected remediation status: {remediation_status}")

            print("Waiting for execution and verification...")
            # Wait for the incident to reach a terminal or post-execution stage (allow up to 120s)
            start_time = time.time()
            while time.time() - start_time < 120:
                incident = await get_incident(client, incident_id)
                if incident and incident.get("stage") in (
                    "remediated",
                    "verifying",
                    "resolved",
                    "escalated",
                ):
                    break
                await asyncio.sleep(5)
            assert incident.get("stage") in (
                "remediated",
                "verifying",
                "resolved",
                "escalated",
            ), f"Final stage was {incident.get('stage')}, expected remediated, verifying, resolved, or escalated"
            assert incident.get("remediation_result"), "Missing remediation result"

            # Verify restarts: either container restarted or deployment rolled out a new pod
            await asyncio.sleep(20)
            final_restarts = get_demo_api_restarts()
            final_pod = get_demo_api_pod_name()
            final_restarted_at = get_demo_api_restarted_at()
            restarted = (
                final_restarts > initial_restarts
                or (final_pod and final_pod != initial_pod)
                or (final_restarted_at and final_restarted_at != initial_restarted_at)
            )
            assert restarted, "Expected demo-api to be restarted or rolled out"
            print("E2E Test Passed Successfully!")
    finally:
        if chaos_proc is not None:
            chaos_proc.terminate()
            try:
                chaos_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chaos_proc.kill()
