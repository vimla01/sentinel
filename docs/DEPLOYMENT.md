# Deployment

## Local Kind

Install Docker, Kind, kubectl, Terraform, and a POSIX shell such as Git Bash or WSL.

```bash
make apply
make bootstrap
```

Terraform creates the cluster. The bootstrap script installs ArgoCD and creates the root Application; ArgoCD then reconciles `infra/k8s` from Git. Build the local image and load it into Kind before syncing the hello service:

```bash
docker build -t sentinel/hello:dev services/hello
kind load docker-image sentinel/hello:dev --name sentinel
kubectl -n argocd get application sentinel
```

The final `kubectl` command is inspection only. Changes to workloads belong in Git and are reconciled by ArgoCD.

## Ollama model & Persistent Storage

The `ollama` deployment uses a dedicated PersistentVolumeClaim (`ollama-models`, `infra/k8s/apps/ollama/pvc.yaml`) mounted at `/root/.ollama`. Kind's default `local-path-provisioner` provisions the volume automatically.

Because storage is persistent, the model only needs to be pulled **once per cluster lifetime** and survives pod restarts, evictions, and deployments:

```bash
kubectl -n sentinel exec deploy/ollama -- ollama pull llama3.2:1b
```

`diagnosis-agent`'s `OLLAMA_MODEL` env var (default `llama3.2:1b`) must match whatever model was pulled. Don't substitute `tinyllama` here even though it's smaller/faster: live-testing against a real cluster showed it's too weak for this task - it doesn't reliably extract a grounded root cause from the runbook, it pattern-matches the prompt's own formatting and echoes it back (observed with both the plain-text and Ollama's grammar-constrained JSON mode). `llama3.2:1b` is still small enough for a CPU-only Kind node, genuinely understands the task, and matches what this README already claims ("Ollama + Llama 3").

## Grafana & Observability Datasources

Grafana is provisioned with both Prometheus and Loki datasources declaratively in `infra/k8s/apps/grafana/datasource-config.yaml`:
- **Prometheus**: `http://prometheus:9090` (default TSDB for metrics and timeline gauges)
- **Loki**: `http://loki:3100` (log aggregation engine queried by `diagnosis-agent` and Grafana Explore)

## Git-Native Remediation

To prevent ArgoCD's automated sync (`selfHeal: true`, `prune: true`) from immediately undoing out-of-band rollbacks or replica scaling, `remediator` integrates a `GitClient` (`services/remediator/git_client.py`).

When an approval-governed rollback executes:
1. `remediator` queries ArgoCD's deploy history to find the previous known-good commit.
2. It restores the target deployment manifests from that revision and commits the change to the Git repository.
3. It triggers an ArgoCD sync (`POST /api/v1/applications/{app}/sync`).
4. ArgoCD reconciles the cluster to the new Git commit. Because the desired state is represented in Git, `selfHeal: true` will never revert the remediation.

Configure `GIT_REPO_PATH` in `remediator`'s environment if running with a mounted repository.

## Slack Approvals & External Reachability

`remediator` auto-executes restart/scale for safe runbook actions. Anything requiring approval dispatches an interactive Slack message with Approve/Deny buttons and awaits HMAC-signed callbacks at `/slack/interactions`.

### Webhook Ingress & Tunnel Setup

1. **In-Cluster Routing**: `infra/k8s/apps/remediator/ingress.yaml` routes external requests from `/slack/interactions` to `service/remediator:8080`, and `infra/k8s/network-policies.yaml` allows ingress traffic.
2. **Local Development Reachability**: Slack cloud servers (`api.slack.com`) require a public HTTPS endpoint to deliver interactivity webhooks to a local Kind cluster. Run the development tunnel helper:

```bash
bash scripts/slack_tunnel.sh
```

Then start a tunnel using Cloudflare or ngrok:
```bash
# Cloudflare Tunnel (free, no account required)
cloudflared tunnel --url http://localhost:8082

# Or ngrok
ngrok http 8082
```

3. **Slack App Configuration**:
   - In your Slack App settings under **Interactivity & Shortcuts**, toggle **Interactivity** to ON.
   - Set the **Request URL** to `https://<your-tunnel-subdomain>/slack/interactions`.
   - Save changes.

4. **Secret Creation**:
   Provision the credentials secret in the `sentinel` namespace:

```bash
kubectl -n sentinel create secret generic remediator-slack \
  --from-literal=bot-token=xoxb-... \
  --from-literal=signing-secret=...
```

`remediator`'s `SLACK_CHANNEL` env var (default `#sentinel-incidents`) must be a channel the bot has been invited to. Without this secret, remediator still runs and auto-executes safe actions; only the approval path is skipped.

## Known Gaps

Three things look done but have a real, honest limitation. Each is
documented here rather than silently fixed, because closing them properly
needs either a decision (auto-committing from CI to a shared repo) or
credentials only you can create (a real GitHub deploy key/PAT).

### CI builds images; nothing deploys them

Both `ci.yml` and `Jenkinsfile` build, test, and push images - but nothing
updates the `image:` tag in `infra/k8s/apps/*/deployment.yaml` and commits
that back to Git, so ArgoCD never picks up a new build automatically. The
two halves (CI building, ArgoCD deploying) are disconnected; every
Deployment still points at a static `sentinel/x:dev` tag loaded locally via
`kind load docker-image`.

`scripts/promote-image.sh` closes this manually without taking the riskier
step of having CI auto-commit to `main` on its own (especially with another
contributor actively pushing to this repo - an unreviewed bot commit landing
mid-collaboration is exactly the kind of surprise worth avoiding). It only
edits `infra/k8s` locally and prints a diff; it never commits or pushes:

```bash
scripts/promote-image.sh api ghcr.io/vimla01/sentinel/api:abc1234
# or, to promote every service to the current commit's images at once:
scripts/promote-image.sh all ghcr.io/vimla01/sentinel

git add infra/k8s && git commit -m "deploy: promote image(s)" && git push
```

Review the diff before committing. ArgoCD picks it up on the next sync once
pushed.

### Git-native rollback has no credentials to actually push with

`services/remediator/git_client.py` can commit a rollback/scale change
directly to a local clone at `GIT_REPO_PATH` - but nothing in
`infra/k8s/apps/remediator/deployment.yaml` mounts a writable clone or push
credentials into the pod. The code path is real and tested
(`tests/test_remediator.py::test_engine_git_native_rollback`), but there's
no secret/volume wiring it up to a real repo yet. To actually enable it:

1. Create a deploy key or fine-grained PAT with push access to this repo
   (GitHub → Settings → Developer settings).
2. `kubectl -n sentinel create secret generic remediator-git --from-literal=token=ghp_...`
3. Add an init container (or startup step) to `remediator`'s Deployment that
   clones the repo into an `emptyDir` using that credential, and set
   `GIT_REPO_PATH` to that mount path.

Until that's wired up, rollback still works via ArgoCD's own rollback API
(`services/remediator/argocd_client.py`) - the git-native path is a
not-yet-connected enhancement, not a missing fallback.

### The remediator Ingress resource is currently inert

`infra/k8s/apps/remediator/ingress.yaml` exists, but no ingress controller
is installed anywhere in this cluster setup - so nothing implements it. This
isn't blocking the Slack demo: the
[tunnel setup above](#slack-approvals--external-reachability) reaches
`remediator` directly via `kubectl port-forward`, bypassing Ingress
entirely, since a local Kind cluster isn't publicly routable regardless of
whether an ingress controller is present.

To make the Ingress resource do something real (for a non-local
environment): install `ingress-nginx`'s Kind-specific manifest, add
`extraPortMappings` for 80/443 to
`infra/terraform/modules/local-cluster/kind-config.yaml` with
`node-labels: ingress-ready=true` on the control-plane node, and point a
real DNS name + TLS cert (e.g. via cert-manager) at it instead of a
temporary tunnel URL. None of this has been tested against a live cluster
here - there's no running `sentinel` Kind cluster in this environment to
verify it against, so treat it as a documented next step, not a verified one.

## Incident history persistence

`api` is the service in this platform with durable incident state: it persists the correlated incident timeline to SQLite on a `PersistentVolumeClaim` (`api-data`, `infra/k8s/apps/api/pvc.yaml`) rather than keeping it in memory. If the `api` pod cannot write to its mounted path, it falls back to an in-memory store and logs a warning.
