# API

Phase 0 hello service endpoints:

- `GET /` returns a service identity and greeting.
- `GET /healthz` returns the readiness health status.

## demo-api

Same `/` and `/healthz` as hello, plus chaos-injection controls used by
`scripts/chaos/`:

- `GET /debug/status` returns the current chaos state (memory leaked, CPU
  spike active, latency, error probability).
- `POST /debug/leak-memory` `{chunk_mb}` allocates and retains another chunk
  of memory.
- `POST /debug/cpu-spike` `{duration_seconds, workers}` spins busy-loop
  threads for a fixed duration.
- `POST /debug/latency` `{delay_ms, duration_seconds}` adds artificial
  latency to every other response.
- `POST /debug/error-rate` `{probability, duration_seconds}` randomly returns
  500s for a fraction of requests.
- `POST /debug/reset` clears all chaos state.

## predictor

- `GET /healthz` readiness health status.
- `GET /risk` current rolling mean/std-dev z-score per metric (CPU, memory,
  latency, error rate) polled from Prometheus, plus an overall risk score.
- `GET /alerts` history of internal alerts fired when a metric's z-score
  crossed `THRESHOLD_SIGMA`. Polled by diagnosis-agent; not yet wired to
  remediation.

Both demo-api and predictor also expose `/metrics` (Prometheus format) via
`prometheus-fastapi-instrumentator`.

## diagnosis-agent

- `GET /healthz` readiness health status.
- `GET /runbooks` lists the runbooks loaded from `runbooks/` (id, title,
  metrics covered).
- `GET /diagnoses` history of diagnoses produced so far.
- `POST /diagnose` `{metric, value, mean, stddev, z_score, fired_at}` runs
  the diagnosis pipeline on demand for a given alert (the same shape the
  predictor's `/alerts` entries have) - useful for testing without a live
  predictor/Ollama in the loop.

In the background, diagnosis-agent polls the predictor's `/alerts` every
`POLL_INTERVAL_SECONDS` and diagnoses any alert it hasn't seen yet. For each
new alert it retrieves recent logs from Loki and recent deploy history from
ArgoCD, matches a runbook whose `metrics` cover the alert's metric, and (only
if a runbook matched) prompts Ollama to produce a root cause and recommended
action grounded in that runbook. If no runbook matches the metric, no LLM
call is made and the diagnosis is recorded as ungrounded rather than
invented - see [runbooks/README.md](../runbooks/README.md) for the runbook
schema. Also exposes `/metrics` (Prometheus format).
