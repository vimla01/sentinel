# SENTINEL

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-Ready-326CE5.svg)](https://kubernetes.io/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://docker.com/)

Self-healing infrastructure platform that predicts failures before they happen, diagnoses incidents with a local LLM, and remediates them automatically - with human approval for anything risky.

## Overview

SENTINEL is an AI-powered SRE layer that sits on top of a Kubernetes platform. Instead of waiting for services to crash and alerting a human to dig through logs, SENTINEL watches metrics continuously, predicts failure before it occurs, pulls the relevant logs and deploy history, and asks a local LLM to diagnose the root cause, grounded in a library of real runbooks, not guesswork. Known-safe fixes are applied automatically; anything riskier is routed to a human for one-click approval.

**Stack:** Kubernetes (orchestration), Prometheus + Loki (observability), Ollama (LLM diagnosis), ArgoCD (GitOps), Terraform (IaC)

## Features

**Predictive Detection**
- Time-series anomaly detection on CPU, memory, latency, and error-rate metrics
- Flags failure risk minutes before a crash, not after
- Trained on real chaos-test data, not just clean baselines

**AI Incident Diagnosis**
- Local LLM (Ollama) reads recent logs, metrics, and deploy history when an alert fires
- RAG layer grounds diagnosis in a curated set of runbooks - no hallucinated fixes
- Outputs a plain-language root cause and a recommended remediation

**Autonomous Remediation**
- Known-safe actions (restart, scale, rollback) execute automatically via the Kubernetes API
- Risky actions trigger a Slack message with Approve/Deny buttons - nothing destructive happens without a human in the loop
- Full incident timeline (predicted → diagnosed → remediated) logged and visualized

**Platform Foundation**
- GitOps deployment via ArgoCD - no manual `kubectl apply`
- CI/CD pipeline (Jenkins/GitHub Actions) - lint, test, build, deploy
- Infrastructure as Code with Terraform - the whole cluster is reproducible from scratch
- Structured logging, metrics, and dashboards for every layer

**Zero Vendor Lock-in**
- 100% open-source components
- Local LLM inference - no external API calls or per-token cost
- Run anywhere: local, on-premises, or cloud

## Architecture

```
     App Deployments (K8s)
              │
              ▼
   ┌───────────────────── ┐
   │     Prometheus       │──── metrics
   └──────────┬───────────┘
              │
              ▼
   ┌─────────────────────┐
   │ Anomaly Detection   │──── predicts failure before it happens
   │      Model          │
   └──────────┬──────────┘
              │ alert fires
              ▼
   ┌─────────────────────┐        ┌─────────────┐
   │   Loki (logs) +     │───────▶│  LLM Agent  │
   │  Deploy History     │        │  (Ollama +   │
   └─────────────────────┘        │  RAG runbooks)│
                                    └──────┬───────┘
                                           │ diagnosis
                              ┌────────────┴────────────┐
                              ▼                         ▼
                     Safe fix → auto-remediate   Risky fix → Slack approval
                     (K8s API / ArgoCD rollback)   (human clicks Approve/Deny)
                              │                         │
                              └────────────┬────────────┘
                                           ▼
                                  Grafana Dashboard
                            (full incident timeline, logged)
```

**Key design:**
- Prediction, diagnosis, and remediation are decoupled services - each can be tested and improved independently
- Local LLM inference - no external API calls, fully self-contained
- Human-in-the-loop by default for any action beyond restart/scale/rollback
- Every incident produces a timestamped, auditable timeline from prediction to resolution

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Orchestration** | Kubernetes (Kind/Minikube or cloud) |
| **GitOps** | ArgoCD |
| **CI/CD** | Jenkins / GitHub Actions |
| **IaC** | Terraform |
| **Metrics** | Prometheus |
| **Logs** | Loki + Promtail |
| **Dashboards** | Grafana |
| **Anomaly detection** | scikit-learn / Prophet |
| **LLM diagnosis agent** | Ollama + Llama 3 (RAG over runbooks) |
| **Remediation** | Kubernetes API (restart, scale) / ArgoCD rollback API |
| **Human approval** | Slack bot with interactive buttons |
| **Incident timeline** | SQLite-backed gateway (`services/api`) + Prometheus gauges |

## Quick Start

### Local Development

```bash
git clone https://github.com/vimla01/sentinel.git
cd sentinel

make apply
make bootstrap

# Build and load the service images into Kind
make build
kind load docker-image sentinel/hello:dev --name sentinel
kind load docker-image sentinel/demo-api:dev --name sentinel
kind load docker-image sentinel/predictor:dev --name sentinel
kind load docker-image sentinel/diagnosis-agent:dev --name sentinel
kind load docker-image sentinel/remediator:dev --name sentinel
kind load docker-image sentinel/api:dev --name sentinel

# Check GitOps reconciliation (inspection only)
kubectl -n argocd get application sentinel
```

Terraform creates the local Kind cluster. The bootstrap script installs ArgoCD and registers the root Application; all Kubernetes resources after bootstrap are managed through Git and reconciled by ArgoCD.

### Simulate an Incident

```bash
kubectl -n sentinel port-forward svc/demo-api 8080:8080 &
kubectl -n sentinel port-forward svc/predictor 8000:8080 &

# Watch the predictor's live risk score in one terminal...
python scripts/chaos/watch.py --predictor-url http://localhost:8000

# ...while injecting a slow memory leak in another
python scripts/chaos/inject_memory_leak.py --base-url http://localhost:8080 --chunk-mb 30 --steps 10
```

See [scripts/chaos/README.md](./scripts/chaos/README.md) for the full set of
injectable failure modes (CPU spike, latency, error rate).

### Check the Predictor's Risk Assessment

```bash
curl http://localhost:8000/risk
curl http://localhost:8000/alerts
```

`/risk` returns the current rolling mean/std-dev z-score per metric
(CPU, memory, latency, error rate) and an overall risk score. `/alerts`
returns the internal alert history fired when a metric's z-score crosses
`THRESHOLD_SIGMA`.

### Get a Grounded Diagnosis

```bash
kubectl -n sentinel port-forward svc/diagnosis-agent 8001:8080 &

curl http://localhost:8001/runbooks
curl http://localhost:8001/diagnoses
```

diagnosis-agent polls the predictor's `/alerts` in the background. For each
new alert it pulls recent logs (Loki) and deploy history (ArgoCD), retrieves
the runbook covering that metric from [runbooks/](./runbooks), and prompts
Ollama for a root cause and recommended action grounded in that runbook. If
no runbook covers the metric, it records the diagnosis as ungrounded instead
of asking the LLM to guess. See
[docs/API.md](./docs/API.md#diagnosis-agent) for the full endpoint list,
including `POST /diagnose` for triggering a diagnosis on demand.

### Approve or Deny a Remediation

```bash
kubectl -n sentinel port-forward svc/remediator 8002:8080 &

curl http://localhost:8002/remediations
```

remediator polls diagnosis-agent's `/diagnoses` in the background. A
diagnosis whose runbook marks `approval_required: false` and recommends
restart, scale, or rollback auto-executes immediately via the Kubernetes API
(restart/scale) or ArgoCD's rollback API. Anything else posts a message with
Approve/Deny buttons to Slack and waits - nothing runs until a human clicks
one. See [docs/API.md](./docs/API.md#remediator) for the full endpoint list
and [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#slack-approvals) for the
one-time Slack app setup this requires.

### Check the Incident Timeline

```bash
kubectl -n sentinel port-forward svc/api 8003:8080 &

curl http://localhost:8003/api/v1/incidents/latest
curl http://localhost:8003/api/v1/incidents
```

`api` polls predictor, diagnosis-agent, and remediator in the background and
correlates their independent, ephemeral histories - keyed by the same
`(metric, fired_at)` pair all three already use - into one persisted
incident per alert: `predicted → diagnosed → awaiting_approval → (denied |
remediated | failed)`, with a timestamp for each stage it's reached so far.
This is the one durable record in the platform; every other service's
history resets on restart. See [docs/API.md](./docs/API.md#api) for the
full endpoint list, and the "Incident Timeline" Grafana dashboard
(`dashboards/incident-timeline.json`) for the visual, per-incident view of
the same data.

## Project Structure

```
sentinel/
├── services/
│   ├── hello/              # Phase 0 health-check service
│   ├── demo_api/           # Chaos-injectable target service (/debug/*)
│   ├── predictor/          # Rolling-threshold anomaly detection + inference service
│   ├── diagnosis-agent/    # Ollama + RAG diagnosis service
│   ├── remediator/         # K8s API (restart/scale) + ArgoCD rollback, Slack approval
│   └── api/                # Gateway correlating predictor/diagnosis-agent/remediator into a persisted incident timeline
├── runbooks/               # Markdown runbooks used for RAG grounding
├── infra/
│   ├── terraform/          # Cluster + infra provisioning
│   └── k8s/                 # Manifests for all services
├── dashboards/              # Grafana dashboard configs
├── scripts/
│   └── chaos/                # Failure-injection scripts for testing
├── tests/
└── docs/
```

## Development

```bash
# Setup
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt pytest-cov black pylint httpx anyio

# Run demo-api and the predictor locally
uvicorn services.demo_api.main:app --port 8080 --reload
PROMETHEUS_URL=http://localhost:9090 uvicorn services.predictor.main:app --port 8000 --reload

# Run tests with coverage (Automated in CI)
make test
# which runs: python -m pytest tests -q --cov=services --cov-report=term-missing --cov-report=xml --cov-fail-under=80

# Code formatting and Linting (Automated in CI)
make lint
# which runs: python -m black --check services/ && python -m pylint services/

# Run Real E2E Integration Test (Manual/Integration Environment only)
# Prerequisites: Live Kind cluster and Ollama must be running
# Note: This test exercises the real Slack HMAC approval mechanism for any remediations requiring approval.
make test-integration
# which runs: python -m pytest tests/test_integration_e2e.py -v

# Run Diagnosis-Agent Load Test (Manual)
# Note: TinyLlama on CPU-only nodes is known to have request latencies >60s. 
# This manual test exposes the real LLM latency limitations.
make test-load
# which runs: python scripts/load_test_diagnosis.py
```

## Deployment

### Development
```bash
make test
make lint
make apply
make bootstrap
```

### Production
```bash
terraform -chdir=infra/terraform apply
argocd app sync sentinel
kubectl rollout status deployment/sentinel-api
```

See [DEPLOYMENT.md](./docs/DEPLOYMENT.md) for production setup details.

## Design Notes

**Predictive Detection**
- Rolling statistical thresholds (mean + standard deviation) as a baseline
- Optional upgrade path to Prophet/LSTM for teams with more time
- Trained on real chaos-test data so it learns actual pre-failure patterns, not synthetic noise

**Diagnosis Grounding**
- RAG over a curated runbook library - 10-15 known incident types, written by the team
- LLM diagnosis is constrained to cite a matched runbook, reducing hallucinated remediation steps
- Every diagnosis is logged alongside the raw logs/metrics that produced it, for auditability

**Human-in-the-Loop Safety**
- Restart, scale, and rollback are pre-approved as safe and execute automatically
- Anything outside that list requires explicit Slack approval before executing
- No destructive or irreversible action ever runs without a human decision

**Observability**
- Every incident - prediction, diagnosis, and remediation — is timestamped and visualized as a single timeline in Grafana
- Query history and remediation actions are logged for later review

## Roadmap

- Expand runbook library beyond initial 10-15 scenarios
- LSTM-based anomaly detection for more nuanced failure patterns
- Multi-cluster support
- Cost-aware remediation (factor in scaling cost, not just health)
- Post-incident report auto-generation
- Feedback loop: human approval/denial data used to retrain the predictor

## Documentation

- [API Reference](./docs/API.md) - Full endpoint documentation
- [Architecture](./docs/ARCHITECTURE.md) - System design details
- [Runbooks Guide](./docs/RUNBOOKS.md) - How to write and add new runbooks
- [Deployment](./docs/DEPLOYMENT.md) - Production setup guide
- [Contributing](./CONTRIBUTING.md) - How to contribute

## Why This Project

Most infrastructure tooling either monitors (Prometheus/Grafana) or automates (ArgoCD/Terraform) - rarely both, and almost never with reasoning in between. SENTINEL exists to answer a harder question: can a system not just detect that something is wrong, but explain *why*, ground that explanation in real operational knowledge, and act on it safely?

SENTINEL implements the full loop - prediction, diagnosis, and remediation - directly, rather than wrapping a commercial observability platform, focusing on practical integration of time-series ML, retrieval-augmented LLM reasoning, and GitOps-native infrastructure automation.
