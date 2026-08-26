import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI
from prometheus_client import REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator

from .config import settings
from .metrics_client import PrometheusClient
from .monitor import RiskMonitor

logging.basicConfig(level=logging.INFO)

prometheus_client = PrometheusClient(settings.prometheus_url)
monitor = RiskMonitor(prometheus_client, settings.target_job)


@asynccontextmanager
async def lifespan(app: FastAPI):
    poll_task = asyncio.create_task(monitor.run_forever())
    try:
        yield
    finally:
        poll_task.cancel()
        await prometheus_client.aclose()


app = FastAPI(title="SENTINEL predictor", version="0.1.0", lifespan=lifespan)

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


@app.get("/risk")
def risk() -> dict:
    return {
        "target": settings.target_job,
        "threshold_sigma": settings.threshold_sigma,
        "overall_risk": monitor.overall_risk(),
        "metrics": monitor.snapshot(),
    }


@app.get("/alerts")
def alerts() -> dict:
    return {"alerts": [asdict(alert) for alert in monitor.alerts]}
