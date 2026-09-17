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
  crossed `THRESHOLD_SIGMA`. Polled by diagnosis-agent.

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

## remediator

- `GET /healthz` readiness health status.
- `GET /remediations` history of remediations attempted so far (auto and
  approval-required alike), each with its category, whether it auto-executed,
  status (`executed`/`failed`/`awaiting_approval`/`denied`), and result.
- `POST /remediate` `{alert, grounded, runbook_id, recommended_action,
  approval_required, safe_actions, ...}` runs the remediation policy on a
  diagnosis on demand (the same shape a diagnosis-agent `/diagnoses` entry
  has) - useful for testing without a live diagnosis-agent in the loop.
- `POST /slack/interactions` Slack's interactivity webhook target - receives
  the Approve/Deny button click, verifies the request signature
  (`SLACK_SIGNING_SECRET`), and executes or denies the corresponding
  remediation.

In the background, remediator polls diagnosis-agent's `/diagnoses` every
`POLL_INTERVAL_SECONDS` and processes any grounded diagnosis it hasn't seen
yet. A diagnosis auto-executes only if its runbook explicitly marked
`approval_required: false` **and** its recommended action is one of the three
hardcoded safe categories - restart, scale, rollback (see
`services/remediator/policy.py`). Restart and scale act directly on the
`TARGET_DEPLOYMENT` via the Kubernetes API; rollback goes through ArgoCD's
own rollback API rather than a raw Kubernetes rollback, since this platform
is GitOps-managed and a raw rollback would fight ArgoCD's `selfHeal` sync
policy. Everything else - including any diagnosis whose runbook requires
approval, regardless of what its action text says - posts a Slack message
with Approve/Deny buttons and waits; nothing executes until a human clicks
one. Also exposes `/metrics` (Prometheus format).
