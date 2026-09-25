import asyncio
import hmac
import hashlib
import time
import json
import httpx
import pytest
import subprocess
import os
import signal

pytestmark = pytest.mark.integration

def check_env():
    # Check if we can reach sentinel namespace
    res = subprocess.run(["kubectl", "get", "ns", "sentinel"], capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip("E2E prerequisites not met: Kind cluster or sentinel namespace not available")

@pytest.fixture(scope="module")
def port_forwards():
    check_env()
    
    # Start port forwards
    api_pf = subprocess.Popen(["kubectl", "port-forward", "-n", "sentinel", "svc/api", "8083:8080"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    demo_api_pf = subprocess.Popen(["kubectl", "port-forward", "-n", "sentinel", "svc/demo-api", "8081:8080"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    remediator_pf = subprocess.Popen(["kubectl", "port-forward", "-n", "sentinel", "svc/remediator", "8082:8080"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
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

def get_demo_api_restarts():
    res = subprocess.run(
        ["kubectl", "get", "pod", "-l", "app.kubernetes.io/name=demo-api", "-n", "sentinel", "-o", "jsonpath={.items[0].status.containerStatuses[0].restartCount}"],
        capture_output=True, text=True
    )
    if res.returncode == 0 and res.stdout.strip().isdigit():
        return int(res.stdout.strip())
    return 0

@pytest.mark.asyncio
async def test_full_incident_lifecycle(port_forwards):
    # Get initial restarts
    initial_restarts = get_demo_api_restarts()
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            old_incident = await get_latest_incident(client)
            old_incident_id = old_incident["id"] if old_incident else None
            
            # Inject memory leak
            chaos_proc = subprocess.Popen([
                "python", "scripts/chaos/inject_memory_leak.py", 
                "--base-url", "http://127.0.0.1:8081",
                "--chunk-mb", "30",
                "--steps", "5",
                "--interval-seconds", "5.0"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            print("\nWaiting for incident to be predicted...")
            incident = None
            start_time = time.time()
            
            # Wait for prediction
            while time.time() - start_time < 120:
                incident = await get_latest_incident(client)
                if incident and incident["id"] != old_incident_id and incident.get("stage") in ("predicted", "diagnosed", "awaiting_approval", "remediated"):
                    break
                await asyncio.sleep(5)
            
            assert incident is not None, "Failed to get any incident within 120s"
            incident_id = incident["id"]
            
            print(f"Incident {incident_id} found. Waiting for diagnosis...")
            
            # Wait for diagnosis
            start_time = time.time()
            while time.time() - start_time < 120:
                incident = await get_latest_incident(client)
                if incident and incident["id"] == incident_id and incident.get("stage") in ("diagnosed", "awaiting_approval", "remediated"):
                    break
                await asyncio.sleep(5)
                
            assert incident.get("stage") in ("diagnosed", "awaiting_approval", "remediated"), f"Incident stuck at {incident.get('stage')}"
            assert incident.get("runbook_id"), "Diagnosis should have a runbook_id"
            assert incident.get("grounded") is True, "Diagnosis should be grounded"
            
            print(f"Diagnosed with runbook {incident['runbook_id']}. Waiting for remediation creation...")
            
            # Wait for remediation awaiting_approval
            start_time = time.time()
            while time.time() - start_time < 60:
                incident = await get_latest_incident(client)
                if incident and incident["id"] == incident_id and incident.get("remediation_id"):
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
                print(f"Remediation {remediation_id} needs approval. Simulating Slack approval...")
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
                signature = "v0=" + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
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
            elif remediation_status == "executed":
                # Automatic remediation – verify category and result
                assert remediation_category == "restart", f"Automatic remediation category expected 'restart', got {remediation_category}"
                assert "restarted deployment" in remediation_result.lower(), f"Unexpected remediation result: {remediation_result}"
                print(f"Automatic remediation {remediation_id} already executed.")
            else:
                pytest.fail(f"Unexpected remediation status: {remediation_status}")

            print("Waiting for execution...")
            # Wait for the incident to reach the remediated stage (allow up to 120 s)
            start_time = time.time()
            while time.time() - start_time < 120:
                incident = await get_latest_incident(client)
                if (
                    incident
                    and incident["id"] == incident_id
                    and incident.get("stage") == "remediated"
                ):
                    break
                await asyncio.sleep(5)
            
            # ------------------------------------------------------------
            # Determine remediation handling (approval required vs automatic)
            # ------------------------------------------------------------
            remediation_status = None
            for _ in range(12):  # up to 60 seconds, poll every 5s
                resp = await client.get("http://127.0.0.1:8082/remediations")
                if resp.status_code == 200:
                    for r in resp.json().get("remediations", []):
                        if r.get("id") == incident.get("remediation_id"):
                            remediation_status = r.get("status")
                            break
                if remediation_status:
                    break
                await asyncio.sleep(5)

            if remediation_status == "awaiting_approval":
                print(f"Remediation {incident['remediation_id']} needs approval. Simulating Slack approval...")
                signing_secret = os.getenv("SENTINEL_E2E_SLACK_SECRET")
                if not signing_secret:
                    pytest.skip(
                        "SENTINEL_E2E_SLACK_SECRET not set; configure the live remediator with the same Slack signing secret for E2E test"
                    )
                ts = str(int(time.time()))
                payload = {
                    "actions": [{"action_id": "approve", "value": incident["remediation_id"]}],
                    "user": {"username": "e2e-test-user"},
                }
                body = f"payload={json.dumps(payload)}"
                basestring = f"v0:{ts}:{body}".encode()
                signature = "v0=" + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
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
            elif remediation_status == "executed":
                # Automatic remediation – nothing else needed
                print(f"Automatic remediation {incident['remediation_id']} already executed.")
            else:
                pytest.fail(f"Unexpected remediation status: {remediation_status}")

            print("Waiting for execution...")
            # Wait for the incident to reach the remediated stage (allow up to 120s)
            start_time = time.time()
            while time.time() - start_time < 120:
                incident = await get_latest_incident(client)
                if (
                    incident
                    and incident["id"] == incident_id
                    and incident.get("stage") == "remediated"
                ):
                    break
                await asyncio.sleep(5)
            assert incident.get("stage") == "remediated", f"Final stage was {incident.get('stage')}, expected remediated"
            assert incident.get("remediation_result"), "Missing remediation result"
            assert incident.get("remediation_status") == "executed", "Remediation status should be executed"
            
            # Verify restarts
            # Give the restart action a moment to propagate
            await asyncio.sleep(30)
            final_restarts = get_demo_api_restarts()
            assert final_restarts > initial_restarts, "Expected demo-api to be restarted"
            print("E2E Test Passed Successfully!")
    finally:
        chaos_proc.terminate()
        try:
            chaos_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chaos_proc.kill()
