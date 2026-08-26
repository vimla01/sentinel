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
  crossed `THRESHOLD_SIGMA` - not yet wired to diagnosis/remediation.

Both demo-api and predictor also expose `/metrics` (Prometheus format) via
`prometheus-fastapi-instrumentator`.
