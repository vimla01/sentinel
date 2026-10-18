
## Pre-demo setup 

Activate the project venv first — the chaos scripts need `httpx`, which the
system Python doesn't have, and a bare shell may not even have a `python`
command (only `python3`) until the venv is active:

```bash
python3 -m venv venv   # skip if venv/ already exists
source venv/bin/activate
pip install -r requirements.txt pytest-cov black pylint httpx anyio
```

```bash
make apply && make bootstrap        # cluster + ArgoCD, ~1 min
make build && make load             # all 6 images, several min the first time
kubectl -n argocd get application sentinel   # wait for Synced + Healthy
kubectl -n sentinel exec deploy/ollama -- ollama pull llama3.2:1b   # ~1-2 min, one-time
```

**Reset to a clean slate right before presenting.** Every service's history
is in-memory except `api`'s (persisted to SQLite), so after any amount of
testing/practice the Incident Timeline panel ends up cluttered with dozens
of old incidents - the state-timeline panel genuinely becomes unreadable
with that many rows crammed in (verified: don't skip this). The order below
matters - restarting everything in one shot causes a Kubernetes
rolling-update race where a fresh pod can briefly reach an old, not-yet-
terminated upstream pod and reabsorb its stale data, so each step needs to
fully settle before the next:

```bash
kubectl -n sentinel rollout restart deployment/predictor
kubectl -n sentinel rollout status deployment/predictor --timeout=60s

kubectl -n sentinel rollout restart deployment/diagnosis-agent
kubectl -n sentinel rollout status deployment/diagnosis-agent --timeout=60s

kubectl -n sentinel rollout restart deployment/remediator
kubectl -n sentinel rollout status deployment/remediator --timeout=60s

# api last, and wipe its persisted db - the only durable state in the platform
kubectl -n sentinel exec deploy/api -- rm -f /data/incidents.db
kubectl -n sentinel rollout restart deployment/api
kubectl -n sentinel rollout status deployment/api --timeout=60s
```

Verify it's actually clean before moving on:
```bash
curl localhost:18004/api/v1/incidents   # expect {"incidents":[]}
```

Then open 6 terminal tabs with port-forwards running. **These die if the
pod they're attached to restarts** - know how to re-run one quickly, it
takes two seconds:

```bash
kubectl -n sentinel port-forward svc/demo-api 18080:8080 &
kubectl -n sentinel port-forward svc/predictor 18001:8080 &
kubectl -n sentinel port-forward svc/diagnosis-agent 18002:8080 &
kubectl -n sentinel port-forward svc/remediator 18003:8080 &
kubectl -n sentinel port-forward svc/api 18004:8080 &
kubectl -n sentinel port-forward svc/grafana 18030:3000 &
```

Trigger one diagnosis manually a minute before you go live, so Ollama is
warmed up and the first real one in front of people doesn't look slow:

```bash
curl -X POST localhost:18002/diagnose -H "Content-Type: application/json" -d '{
  "metric": "memory_bytes", "value": 500000000, "mean": 100000000,
  "stddev": 5000000, "z_score": 80.0, "fired_at": 1.0
}'
```

## The live walkthrough

### 1. Baseline - nothing's wrong

```bash
curl localhost:18001/risk
```
Say: point out `overall_risk` is low and every metric shows `"alerting": false`.

### 2. Break it - inject a real memory leak

Needs the venv active (`source venv/bin/activate` from Pre-demo setup) -
`python` and `httpx` won't resolve in a bare shell otherwise:

```bash
python scripts/chaos/inject_memory_leak.py --base-url http://localhost:18080 --chunk-mb 30 --steps 10
```
Let it run for ~5-8 steps live while narrating - each step is 15s apart,
good pacing for talking over it. This is a real bug pattern, not a toy: a
slow, unbounded leak with no plateau.

### 3. Predictor's watching this on its own

```bash
curl localhost:18001/alerts
```
Say: point out a fresh `memory_bytes` alert with a high `z_score`. One
sentence on the math if asked: rolling mean/stddev over the last N samples,
z-score = how many standard deviations the new value is from that baseline,
alert fires once it crosses the configured threshold (default 3σ), with a
cooldown so one sustained leak fires once, not every poll cycle.

### 4. Diagnosis-agent picked it up by itself

```bash
curl localhost:18002/diagnoses | python3 -m json.tool
```
Say: read out the `root_cause` and `recommended_action` of the most recent
entry - it's genuinely coherent prose now, grounded in the matched runbook.
**Be upfront about latency**: this takes 30-50 seconds on a CPU-only node;
a real deployment would run this on a GPU or a bigger box.

### 5. It either fixes it or asks a human - this is the core promise

```bash
curl localhost:18003/remediations | python3 -m json.tool
```
Say: find an entry with `"auto": true, "status": "resolved", "result":
"restarted deployment/demo-api"` - that's a real Kubernetes API call, made
by a dedicated least-privilege service account, with its own
post-remediation health check confirming it actually worked (`resolved`,
not just `executed`) - not a simulation. Then find a different entry with
`"auto": false, "status": "awaiting_approval"` and explain the Slack path:
HMAC-verified webhook, posts an Approve/Deny message, blocks until a human
clicks one. Mention a real Slack button click needs a tunnel
(`scripts/slack_tunnel.sh` + cloudflared) pointed at this cluster - not
required for this demo, but real and tested.

### 6. One correlated record ties it all together

```bash
curl localhost:18004/api/v1/incidents/latest | python3 -m json.tool
```
This is the centerpiece: one JSON object showing
`predicted -> diagnosed -> remediated -> resolved`, each with its own
timestamp.

### 7. And visually, in Grafana

Open `localhost:18030`, log in `admin` / `admin`, open **Incident Timeline**
- state-timeline panel, one row per tracked incident, colored by stage.

## If something breaks live

- **Port-forward dies** (it will, if a pod restarts): just
  `kubectl -n sentinel port-forward svc/<name> <port>:8080` again. Don't
  apologize, it's routine.
- **Diagnosis is slow**: that's real CPU-only LLM inference, not a bug -
  say so plainly.
- **"Is this really autonomous, or did you just trigger it?"**: diagnosis-agent
  and remediator both run their own background poll loops independent of any
  manual curl - the manual `/diagnose` and `/remediate` endpoints exist for
  testing, the real path is the poll loop picking up predictor's/diagnosis-agent's
  alerts on its own.
- **Asked about the CI -> deploy loop**: be honest, it's a known gap - CI
  builds and tests images, but nothing auto-promotes an image tag into the
  Git-tracked manifests yet. `scripts/promote-image.sh` does it manually
  pending that decision. Good "here's what I'd build next" answer, not a
  hidden hole.
- **Asked why `llama3.2:1b` and not something bigger**: smallest model that
  reliably understands the task on a CPU-only node - verified live that
  `tinyllama` just echoed the prompt back instead of answering; this one
  actually reasons about the runbook.
- **"Is this deployed on the cloud / Azure / GCP?"**: not yet live, but the
  deployment path is real and validated, not just talked about -
  `infra/terraform-gke/` (GKE Autopilot) and `infra/terraform-azure/` (AKS)
  are both complete Terraform roots; `terraform validate` passes on both and
  `terraform plan` reaches each cloud's own real authentication check,
  proving the infrastructure-as-code is correct. What's blocking the actual
  cluster is account verification (GCP/AWS free trials require a credit
  card regardless of student status; Azure for Students' SheerID
  verification flagged the account on a risk check) - an external,
  procedural blocker, not a gap in the engineering. `make gke-apply` /
  `make azure-apply` is genuinely one command away from a live cluster the
  moment either account clears. See
  [docs/DEPLOYMENT.md#deploying-to-gke](./DEPLOYMENT.md#deploying-to-gke)
  and [docs/DEPLOYMENT.md#deploying-to-aks](./DEPLOYMENT.md#deploying-to-aks).
