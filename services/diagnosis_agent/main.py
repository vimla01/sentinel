import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

import httpx
from fastapi import FastAPI
from prometheus_client import REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel

from .config import settings
from .deploy_history import DeployHistoryClient
from .diagnosis import DiagnosisEngine
from .loki_client import LokiClient
from .ollama_client import OllamaClient
from .predictor_client import PredictorClient
from .runbooks import load_runbooks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("diagnosis_agent.main")

predictor_client = PredictorClient(settings.predictor_url)
loki_client = LokiClient(settings.loki_url)
deploy_client = DeployHistoryClient(settings.argocd_url)
ollama_client = OllamaClient(settings.ollama_url, settings.ollama_model)
runbooks = load_runbooks(settings.runbooks_dir)
engine = DiagnosisEngine(
    runbooks=runbooks,
    loki=loki_client,
    deploys=deploy_client,
    ollama=ollama_client,
    target_job=settings.target_job,
    argocd_app=settings.argocd_app,
    log_lookback_seconds=settings.log_lookback_seconds,
    deploy_lookback_seconds=settings.deploy_lookback_seconds,
    log_line_limit=settings.log_line_limit,
    max_diagnoses=settings.max_diagnoses,
)

_seen_alerts: set[tuple[str, float]] = set()


async def _poll_predictor_forever() -> None:
    while True:
        try:
            alerts = await predictor_client.get_alerts()
        except httpx.HTTPError as exc:
            logger.warning("predictor poll failed error=%s", exc)
            alerts = []

        for alert in alerts:
            key = (alert.get("metric"), alert.get("fired_at"))
            if key in _seen_alerts:
                continue
            _seen_alerts.add(key)
            try:
                await engine.diagnose(alert)
            except Exception:
                logger.exception("diagnosis failed for alert=%s", alert)

        await asyncio.sleep(settings.poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    poll_task = asyncio.create_task(_poll_predictor_forever())
    try:
        yield
    finally:
        poll_task.cancel()
        await predictor_client.aclose()
        await loki_client.aclose()
        await deploy_client.aclose()
        await ollama_client.aclose()


app = FastAPI(title="SENTINEL diagnosis-agent", version="0.1.0", lifespan=lifespan)

# metrics.default() re-registers the same collector names on every call, which
# raises if another instrumented FastAPI app already did so in this process
# (e.g. the test suite importing multiple services together).
_instrumentator = Instrumentator()
if "http_requests_total" not in REGISTRY._names_to_collectors:
    _instrumentator.instrument(app)
_instrumentator.expose(app)


class AlertIn(BaseModel):
    metric: str
    value: float
    mean: float
    stddev: float
    z_score: float
    fired_at: float


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/runbooks")
def runbooks_list() -> dict:
    return {
        "runbooks": [
            {"id": rb.id, "title": rb.title, "metrics": rb.metrics} for rb in runbooks
        ]
    }


@app.get("/diagnoses")
def diagnoses() -> dict:
    return {"diagnoses": [asdict(d) for d in engine.diagnoses]}


@app.post("/diagnose")
async def diagnose(alert: AlertIn) -> dict:
    diagnosis = await engine.diagnose(alert.model_dump())
    return asdict(diagnosis)
