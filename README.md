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
                     (K8s API / Argo Workflows)   (human clicks Approve/Deny)
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
| **Remediation** | Argo Workflows / Kubernetes API |
| **Human approval** | Slack bot with interactive buttons |

## Quick Start

### Local Development

```bash
git clone https://github.com/vimla01/sentinel.git
cd sentinel

terraform -chdir=infra/terraform apply
kubectl apply -f infra/k8s/

# Services ready:
# Grafana:      http://localhost:3000
# Prometheus:   http://localhost:9090
# Diagnosis API: http://localhost:8000/docs
```

### Simulate an Incident

```bash
# Trigger a chaos test to watch the full loop run
python scripts/chaos/inject_memory_leak.py --service demo-api
```

### Check an Incident's Diagnosis

```bash
curl http://localhost:8000/api/v1/incidents/latest
```

Response includes the predicted risk score, root-cause diagnosis, matched runbook, and remediation action taken.

## Project Structure

```
sentinel/
├── services/
│   ├── predictor/         # Anomaly detection model + inference service
│   ├── diagnosis-agent/   # Ollama + RAG diagnosis service
│   ├── remediator/        # K8s API actions + Argo Workflows
│   └── api/               # FastAPI gateway, incident history
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
pip install -r requirements.txt

# Run the diagnosis agent locally
uvicorn services.diagnosis-agent.main:app --reload

# Run tests
pytest tests/ -v --cov=services

# Code formatting
black services/
pylint services/
```

## Deployment

### Development
```bash
kind create cluster
kubectl apply -f infra/k8s/
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
