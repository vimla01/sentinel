import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from urllib.parse import parse_qs

import httpx
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator

from .argocd_client import ArgocdClient
from .config import settings
from .diagnosis_client import DiagnosisAgentClient
from .engine import RemediationEngine
from .k8s_client import K8sClient
from .slack_client import SlackClient, verify_signature

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("remediator.main")


def _build_k8s_client() -> K8sClient:
    try:
        return K8sClient.in_cluster(settings.k8s_namespace)
    except (KeyError, FileNotFoundError):
        logger.warning(
            "not running in-cluster; K8s actions will fail until deployed there"
        )
        return K8sClient(
            base_url="https://kubernetes.default.svc",
            token="",
            namespace=settings.k8s_namespace,
        )


diagnosis_client = DiagnosisAgentClient(settings.diagnosis_agent_url)
k8s_client = _build_k8s_client()
argocd_client = ArgocdClient(settings.argocd_url)
slack_client = SlackClient(settings.slack_bot_token)
engine = RemediationEngine(
    k8s=k8s_client,
    argocd=argocd_client,
    slack=slack_client,
    target_deployment=settings.target_deployment,
    argocd_app=settings.argocd_app,
    slack_channel=settings.slack_channel,
    scale_step=settings.scale_step,
    max_replicas=settings.max_replicas,
    max_remediations=settings.max_remediations,
)

_seen_diagnoses: set[tuple[str, float]] = set()


async def _poll_diagnosis_agent_forever() -> None:
    while True:
        try:
            diagnoses = await diagnosis_client.get_diagnoses()
        except httpx.HTTPError as exc:
            logger.warning("diagnosis-agent poll failed error=%s", exc)
            diagnoses = []

        for diagnosis in diagnoses:
            alert = diagnosis.get("alert", {})
            key = (alert.get("metric"), alert.get("fired_at"))
            if key in _seen_diagnoses:
                continue
            _seen_diagnoses.add(key)
            try:
                await engine.process_diagnosis(diagnosis)
            except Exception:
                logger.exception(
                    "remediation processing failed for diagnosis=%s", diagnosis
                )

        await asyncio.sleep(settings.poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    poll_task = asyncio.create_task(_poll_diagnosis_agent_forever())
    try:
        yield
    finally:
        poll_task.cancel()
        await diagnosis_client.aclose()
        await k8s_client.aclose()
        await argocd_client.aclose()
        await slack_client.aclose()


app = FastAPI(title="SENTINEL remediator", version="0.1.0", lifespan=lifespan)

# metrics.default() re-registers the same collector names on every call, which
# raises if another instrumented FastAPI app already did so in this process
# (e.g. the test suite importing multiple services together).
_instrumentator = Instrumentator()
if "http_requests_total" not in REGISTRY._names_to_collectors:
    _instrumentator.instrument(app)
_instrumentator.expose(app)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/remediations")
def remediations() -> dict:
    return {"remediations": [asdict(r) for r in engine.remediations]}


@app.post("/remediate")
async def remediate(diagnosis: dict) -> dict:
    remediation = await engine.process_diagnosis(diagnosis)
    if remediation is None:
        raise HTTPException(
            status_code=400,
            detail="diagnosis is not grounded or has no recommended action",
        )
    return asdict(remediation)


@app.post("/slack/interactions")
async def slack_interactions(request: Request) -> dict:
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not verify_signature(
        settings.slack_signing_secret, timestamp, body.decode("utf-8"), signature
    ):
        raise HTTPException(status_code=401, detail="invalid slack signature")

    form = parse_qs(body.decode("utf-8"))
    payload_values = form.get("payload")
    if not payload_values:
        raise HTTPException(status_code=400, detail="missing payload")
    payload = json.loads(payload_values[0])

    action = payload["actions"][0]
    remediation_id = action["value"]
    approved = action["action_id"] == "approve"
    user = payload.get("user", {})
    actor = user.get("username") or user.get("id", "unknown")

    try:
        remediation = await engine.resolve(remediation_id, approved, actor)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown remediation id")

    return {"status": remediation.status}
