import httpx
import pytest
from fastapi.testclient import TestClient

from services.api.db import IncidentStore, incident_id, stage
from services.api.diagnosis_client import DiagnosisAgentClient
from services.api.main import app
from services.api.predictor_client import PredictorClient
from services.api.remediator_client import RemediatorClient
from services.api.sync import IncidentSync, incident_stage_level

client = TestClient(app)

_ALERT = {
    "metric": "memory_bytes",
    "value": 5e8,
    "mean": 1e8,
    "stddev": 5e6,
    "z_score": 80.0,
    "fired_at": 1700000000.0,
}

_DIAGNOSIS = {
    "alert": _ALERT,
    "grounded": True,
    "runbook_id": "memory-leak-unbounded-growth",
    "root_cause": "memory grows steadily",
    "recommended_action": "restart the affected pod",
    "created_at": 1700000005.0,
}

_REMEDIATION_AUTO = {
    "id": "rem-1",
    "alert": _ALERT,
    "runbook_id": "memory-leak-unbounded-growth",
    "category": "restart",
    "auto": True,
    "status": "executed",
    "result": "restarted deployment/demo-api",
    "resolved_at": 1700000010.0,
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _mock_transport(base_url: str, handler):
    return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))


def _syncer(alerts=None, diagnoses=None, remediations=None, max_history: int = 50) -> tuple[IncidentSync, IncidentStore]:
    alerts = alerts if alerts is not None else []
    diagnoses = diagnoses if diagnoses is not None else []
    remediations = remediations if remediations is not None else []

    predictor = PredictorClient("http://predictor:8080")
    predictor._client = _mock_transport(
        "http://predictor:8080", lambda r: httpx.Response(200, json={"alerts": alerts})
    )
    diagnosis = DiagnosisAgentClient("http://diagnosis-agent:8080")
    diagnosis._client = _mock_transport(
        "http://diagnosis-agent:8080", lambda r: httpx.Response(200, json={"diagnoses": diagnoses})
    )
    remediator = RemediatorClient("http://remediator:8080")
    remediator._client = _mock_transport(
        "http://remediator:8080", lambda r: httpx.Response(200, json={"remediations": remediations})
    )
    store = IncidentStore(":memory:")
    return IncidentSync(predictor, diagnosis, remediator, store, max_history=max_history), store


def test_incident_id_is_metric_and_fired_at() -> None:
    assert incident_id("memory_bytes", 1700000000.0) == "memory_bytes:1700000000.0"


def test_stage_derivation_precedence() -> None:
    assert stage({"remediation_status": "executed"}) == "remediated"
    assert stage({"remediation_status": "failed"}) == "failed"
    assert stage({"remediation_status": "denied"}) == "denied"
    assert stage({"remediation_status": "awaiting_approval"}) == "awaiting_approval"
    assert stage({"remediation_status": None, "diagnosed_at": 123.0}) == "diagnosed"
    assert stage({"remediation_status": None, "diagnosed_at": None}) == "predicted"


@pytest.mark.anyio
async def test_sync_ingests_predicted_only_alert() -> None:
    syncer, store = _syncer(alerts=[_ALERT])
    updated = await syncer.sync_once()

    assert updated == 1
    incident = store.latest()
    assert incident["metric"] == "memory_bytes"
    assert incident["stage"] == "predicted"
    assert incident["diagnosed_at"] is None


@pytest.mark.anyio
async def test_sync_seeds_predicted_row_when_diagnosis_arrives_first() -> None:
    """diagnosis-agent and predictor are polled independently - a diagnosis
    can show up before its own alert does within the same cycle, and the
    store must not lose it."""
    syncer, store = _syncer(alerts=[], diagnoses=[_DIAGNOSIS])
    updated = await syncer.sync_once()

    assert updated == 1
    incident = store.latest()
    assert incident["stage"] == "diagnosed"
    assert incident["runbook_id"] == "memory-leak-unbounded-growth"
    assert incident["root_cause"] == "memory grows steadily"


@pytest.mark.anyio
async def test_full_lifecycle_across_three_sync_cycles() -> None:
    syncer, store = _syncer(alerts=[_ALERT])
    await syncer.sync_once()
    assert store.latest()["stage"] == "predicted"

    syncer._diagnosis._client = _mock_transport(
        "http://diagnosis-agent:8080", lambda r: httpx.Response(200, json={"diagnoses": [_DIAGNOSIS]})
    )
    await syncer.sync_once()
    assert store.latest()["stage"] == "diagnosed"

    awaiting = {**_REMEDIATION_AUTO, "status": "awaiting_approval", "resolved_at": None}
    syncer._remediator._client = _mock_transport(
        "http://remediator:8080", lambda r: httpx.Response(200, json={"remediations": [awaiting]})
    )
    await syncer.sync_once()
    incident = store.latest()
    assert incident["stage"] == "awaiting_approval"

    executed = {**_REMEDIATION_AUTO, "status": "executed"}
    syncer._remediator._client = _mock_transport(
        "http://remediator:8080", lambda r: httpx.Response(200, json={"remediations": [executed]})
    )
    await syncer.sync_once()
    incident = store.latest()
    assert incident["stage"] == "remediated"
    assert incident["remediation_result"] == "restarted deployment/demo-api"

    assert incident_id(_ALERT["metric"], _ALERT["fired_at"]) == incident["id"]
    assert len(store.history(limit=10)) == 1


def _gauge_incident_ids() -> set[str]:
    # incident_stage_level is a module-level (process-global) Prometheus
    # gauge, so other tests' label combinations may still be present here -
    # only assert about the ids this test itself cares about, never equality
    # against the whole registry.
    return {
        sample.labels["incident_id"]
        for metric in incident_stage_level.collect()
        for sample in metric.samples
        if sample.name == "sentinel_incident_stage_level"
    }


@pytest.mark.anyio
async def test_gauge_removed_when_incident_ages_out_of_max_history() -> None:
    """The store persists every incident forever (it's the audit trail),
    but the Prometheus gauge is deliberately bounded to max_history series -
    an incident that ages out of that window must have its gauge series
    removed, not left stale in the registry forever."""
    old_alert = {**_ALERT, "fired_at": 1.0}
    new_alert = {**_ALERT, "fired_at": 2.0}
    old_id = incident_id(old_alert["metric"], old_alert["fired_at"])
    new_id = incident_id(new_alert["metric"], new_alert["fired_at"])

    syncer, store = _syncer(alerts=[old_alert], max_history=1)
    await syncer.sync_once()
    assert old_id in _gauge_incident_ids()

    syncer._predictor._client = _mock_transport(
        "http://predictor:8080", lambda r: httpx.Response(200, json={"alerts": [old_alert, new_alert]})
    )
    await syncer.sync_once()

    # Both incidents are still durably persisted...
    assert len(store.history(limit=10)) == 2
    # ...but the older one's gauge series is gone once it ages out of the
    # (max_history=1) tracking window, while the new one is present.
    current = _gauge_incident_ids()
    assert old_id not in current
    assert new_id in current


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_latest_incident_404_when_empty() -> None:
    response = client.get("/api/v1/incidents/latest")
    assert response.status_code == 404


def test_incident_history_empty() -> None:
    response = client.get("/api/v1/incidents")
    assert response.status_code == 200
    assert response.json() == {"incidents": []}


def test_incident_detail_404_for_unknown_id() -> None:
    response = client.get("/api/v1/incidents/does-not-exist")
    assert response.status_code == 404
