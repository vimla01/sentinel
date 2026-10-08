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
kubectl -n sentinel exec deploy/ollama -- ollama pull tinyllama
```

`diagnosis-agent`'s `OLLAMA_MODEL` env var (default `tinyllama`) must match whatever model was pulled.

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

## Incident history persistence

`api` is the service in this platform with durable incident state: it persists the correlated incident timeline to SQLite on a `PersistentVolumeClaim` (`api-data`, `infra/k8s/apps/api/pvc.yaml`) rather than keeping it in memory. If the `api` pod cannot write to its mounted path, it falls back to an in-memory store and logs a warning.
