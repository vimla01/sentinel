import httpx
import pytest
from fastapi.testclient import TestClient

from services.diagnosis_agent.deploy_history import DeployHistoryClient
from services.diagnosis_agent.diagnosis import DiagnosisEngine
from services.diagnosis_agent.loki_client import LokiClient
from services.diagnosis_agent.main import app
from services.diagnosis_agent.ollama_client import OllamaClient
from services.diagnosis_agent.retriever import match_runbook, tokenize
from services.diagnosis_agent.runbooks import load_runbooks

client = TestClient(app)

_ALERT = {
    "metric": "memory_bytes",
    "value": 500_000_000.0,
    "mean": 100_000_000.0,
    "stddev": 5_000_000.0,
    "z_score": 80.0,
    "fired_at": 1700000000.0,
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _mock_transport(base_url: str, handler):
    return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))


def test_load_runbooks_parses_frontmatter_and_body() -> None:
    runbooks = load_runbooks("runbooks")

    assert len(runbooks) >= 10
    ids = {rb.id for rb in runbooks}
    assert "memory-leak-unbounded-growth" in ids
    assert "error-rate-bad-deploy" in ids

    leak = next(rb for rb in runbooks if rb.id == "memory-leak-unbounded-growth")
    assert leak.metrics == ["memory_bytes"]
    assert leak.approval_required is False
    assert leak.safe_actions == ["restart the affected pod"]
    assert "Detection Signals" in leak.body


def test_load_runbooks_covers_every_predictor_metric() -> None:
    runbooks = load_runbooks("runbooks")
    covered_metrics = {metric for rb in runbooks for metric in rb.metrics}

    assert covered_metrics == {"cpu_percent", "memory_bytes", "latency_seconds", "error_rate"}


def test_match_runbook_requires_metric_match() -> None:
    runbooks = load_runbooks("runbooks")

    match = match_runbook("memory_bytes", "", runbooks)
    assert match is not None
    assert "memory_bytes" in match.metrics

    assert match_runbook("nonexistent_metric", "", runbooks) is None


def test_match_runbook_ranks_by_context_overlap() -> None:
    runbooks = load_runbooks("runbooks")

    leak_context = "memory grows steadily every interval leak unbounded"
    match = match_runbook("memory_bytes", leak_context, runbooks)
    assert match.id == "memory-leak-unbounded-growth"

    cache_context = "cache eviction lru maxsize staircase plateau"
    match = match_runbook("memory_bytes", cache_context, runbooks)
    assert match.id == "memory-unbounded-cache-growth"


def test_tokenize_lowercases_and_strips_punctuation() -> None:
    assert tokenize("CPU-Saturation: Busy Loop!") == ["cpu", "saturation", "busy", "loop"]


@pytest.mark.anyio
async def test_diagnosis_engine_withholds_diagnosis_when_no_runbook_matches() -> None:
    async def ollama_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("LLM must not be called when no runbook is matched")

    loki = LokiClient("http://loki:3100")
    loki._client = _mock_transport("http://loki:3100", lambda r: httpx.Response(200, json={"data": {"result": []}}))
    deploys = DeployHistoryClient("http://argocd:80")
    deploys._client = _mock_transport("http://argocd:80", lambda r: httpx.Response(200, json={"status": {"history": []}}))
    ollama = OllamaClient("http://ollama:11434", "llama3")
    ollama._client = _mock_transport("http://ollama:11434", ollama_handler)

    engine = DiagnosisEngine(
        runbooks=[],
        loki=loki,
        deploys=deploys,
        ollama=ollama,
        target_job="demo-api",
        argocd_app="sentinel",
        log_lookback_seconds=300,
        deploy_lookback_seconds=3600,
        log_line_limit=50,
    )

    diagnosis = await engine.diagnose(_ALERT)

    assert diagnosis.grounded is False
    assert diagnosis.runbook_id is None
    assert "memory_bytes" in diagnosis.root_cause
    assert diagnosis.safe_actions == []
    assert diagnosis.approval_required is True
    assert engine.diagnoses == [diagnosis]


@pytest.mark.anyio
async def test_diagnosis_engine_cites_matched_runbook() -> None:
    runbooks = load_runbooks("runbooks")

    def ollama_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": (
                    "Root Cause: memory grows steadily with no traffic correlation.\n"
                    "Recommended Action: restart the affected pod\n"
                    "Runbook Cited: memory-leak-unbounded-growth\n"
                )
            },
        )

    leak_logs = {
        "data": {
            "result": [
                {"values": [["1700000000000000000", "memory grows steadily every interval, leak unbounded"]]}
            ]
        }
    }
    loki = LokiClient("http://loki:3100")
    loki._client = _mock_transport("http://loki:3100", lambda r: httpx.Response(200, json=leak_logs))
    deploys = DeployHistoryClient("http://argocd:80")
    deploys._client = _mock_transport("http://argocd:80", lambda r: httpx.Response(200, json={"status": {"history": []}}))
    ollama = OllamaClient("http://ollama:11434", "llama3")
    ollama._client = _mock_transport("http://ollama:11434", ollama_handler)

    engine = DiagnosisEngine(
        runbooks=runbooks,
        loki=loki,
        deploys=deploys,
        ollama=ollama,
        target_job="demo-api",
        argocd_app="sentinel",
        log_lookback_seconds=300,
        deploy_lookback_seconds=3600,
        log_line_limit=50,
    )

    diagnosis = await engine.diagnose(_ALERT)

    assert diagnosis.grounded is True
    assert diagnosis.runbook_id == "memory-leak-unbounded-growth"
    assert "steadily" in diagnosis.root_cause
    assert diagnosis.recommended_action == "restart the affected pod"
    assert diagnosis.safe_actions == ["restart the affected pod"]
    assert diagnosis.approval_required is False


@pytest.mark.anyio
async def test_diagnosis_engine_degrades_gracefully_when_loki_and_argo_unreachable() -> None:
    runbooks = load_runbooks("runbooks")

    def ollama_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "Root Cause: x\nRecommended Action: y\n"})

    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    loki = LokiClient("http://loki:3100")
    loki._client = _mock_transport("http://loki:3100", failing_handler)
    deploys = DeployHistoryClient("http://argocd:80")
    deploys._client = _mock_transport("http://argocd:80", failing_handler)
    ollama = OllamaClient("http://ollama:11434", "llama3")
    ollama._client = _mock_transport("http://ollama:11434", ollama_handler)

    engine = DiagnosisEngine(
        runbooks=runbooks,
        loki=loki,
        deploys=deploys,
        ollama=ollama,
        target_job="demo-api",
        argocd_app="sentinel",
        log_lookback_seconds=300,
        deploy_lookback_seconds=3600,
        log_line_limit=50,
    )

    diagnosis = await engine.diagnose(_ALERT)

    assert diagnosis.grounded is True
    assert diagnosis.logs == []
    assert diagnosis.deploys == []


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_runbooks_endpoint_lists_loaded_runbooks() -> None:
    response = client.get("/runbooks")
    assert response.status_code == 200
    body = response.json()
    assert len(body["runbooks"]) >= 10
    assert all({"id", "title", "metrics"} <= entry.keys() for entry in body["runbooks"])


def test_diagnoses_endpoint_starts_empty() -> None:
    response = client.get("/diagnoses")
    assert response.status_code == 200
    assert response.json() == {"diagnoses": []}
