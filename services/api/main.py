import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from prometheus_client import REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator

from .air_quality import fetch_air_quality, fetch_station_trend
from .config import settings
from .dashboard_ui import get_dashboard_html
from .db import IncidentStore
from .diagnosis_client import DiagnosisAgentClient
from .predictor_client import PredictorClient
from .remediator_client import RemediatorClient
from .sync import IncidentSync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api.main")


def _build_store() -> IncidentStore:
    try:
        Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        return IncidentStore(settings.db_path)
    except OSError:
        logger.warning(
            "cannot open db_path=%s; falling back to an in-memory store (not persisted across restarts)",
            settings.db_path,
        )
        return IncidentStore(":memory:")


predictor_client = PredictorClient(settings.predictor_url)
diagnosis_client = DiagnosisAgentClient(settings.diagnosis_agent_url)
remediator_client = RemediatorClient(settings.remediator_url)
store = _build_store()
syncer = IncidentSync(
    predictor=predictor_client,
    diagnosis=diagnosis_client,
    remediator=remediator_client,
    store=store,
    max_history=settings.max_history,
)


async def _poll_forever() -> None:
    while True:
        await syncer.sync_once()
        try:
            await fetch_air_quality()
        except Exception as exc:
            logger.debug("background air quality poll error: %s", exc)
        await asyncio.sleep(settings.poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    poll_task = asyncio.create_task(_poll_forever())
    try:
        yield
    finally:
        poll_task.cancel()
        await predictor_client.aclose()
        await diagnosis_client.aclose()
        await remediator_client.aclose()
        store.close()


app = FastAPI(title="SENTINEL api", version="0.1.0", lifespan=lifespan)

# metrics.default() re-registers the same collector names on every call, which
# raises if another instrumented FastAPI app already did so in this process
# (e.g. the test suite importing multiple services together).
_instrumentator = Instrumentator()
if "http_requests_total" not in REGISTRY._names_to_collectors:
    _instrumentator.instrument(app)
_instrumentator.expose(app)


@app.get("/")
def index() -> dict:
    return {
        "service": "SENTINEL API Gateway",
        "sdg_project": "Mumbai Air Quality Telemetry (UN SDG 3: Good Health and Well-being)",
        "dashboard_url": "/dashboard",
        "air_quality_api": "/api/v1/air-quality",
        "air_quality_latest": "/api/v1/air-quality/latest",
        "incidents_api": "/api/v1/incidents/latest",
        "incidents_latest": "/incidents/latest",
        "metrics": "/metrics",
        "health": "/healthz",
    }


@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard() -> str:
    return get_dashboard_html()


@app.get("/api/v1/air-quality")
@app.get("/api/v1/air-quality/latest")
async def air_quality_latest(force_refresh: bool = False) -> dict:
    return await fetch_air_quality(force_refresh=force_refresh)


@app.get("/api/v1/air-quality/history")
async def air_quality_history(
    station: str = "Bandra", force_refresh: bool = False
) -> dict:
    return await fetch_station_trend(station_name=station, force_refresh=force_refresh)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/incidents/latest")
@app.get("/api/v1/incidents/latest")
def latest_incident() -> dict:
    incident = store.latest()
    if incident is None:
        raise HTTPException(status_code=404, detail="no incidents recorded yet")
    return incident


@app.get("/api/v1/incidents")
def incident_history(limit: int = 50) -> dict:
    return {"incidents": store.history(limit=min(limit, settings.max_history))}


@app.get("/api/v1/incidents/{incident_id}")
def incident_detail(incident_id: str) -> dict:
    incident = store.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


@app.post("/api/v1/incidents/sync")
async def sync_now() -> dict:
    try:
        updated = await syncer.sync_once()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"synced": updated}
