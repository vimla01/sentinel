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

## Deploying to GKE

This is a genuinely separate path from local Kind, not a flag on the same
one. `infra/terraform-gke/` is its own Terraform root (not a toggle inside
`infra/terraform/`) deliberately: the `google` provider authenticates
eagerly at plan/apply time even for a resource that ends up unused, which
would have required GCP credentials just to run a local `terraform plan` -
keeping it a separate root means the local Kind workflow above is
completely unaffected by any of this (verified: `terraform plan` in
`infra/terraform/` still shows zero `google` provider involvement).

**One-time setup:**
```bash
gcloud auth application-default login
gcloud services enable container.googleapis.com --project=<your-project-id>
```

**Provision the cluster** (GKE Autopilot - Google manages node pools, so
there's no node sizing/count to configure):
```bash
make gke-apply GCP_PROJECT_ID=<your-project-id>
make gke-bootstrap
```
`gke-bootstrap` runs Terraform's own `next_step` output - it chains
`gcloud container clusters get-credentials` (points `kubectl` at the new
cluster) with `scripts/bootstrap-argocd.sh sentinel gke` (the `gke` arg
skips the Kind-specific `kubectl config use-context "kind-*"` call, since
`gcloud` already set the right context).

**Images: `kind load docker-image` doesn't exist on GKE.** Every
Deployment currently points at `sentinel/<service>:dev`, a tag that only
exists because it's loaded directly into Kind's nodes - GKE nodes can only
pull from a real registry. Before ArgoCD can bring any workload up on GKE:

1. Confirm the GHCR packages CI already builds (`ghcr.io/vimla01/sentinel/<service>:<git-sha>`)
   are public, or create an `imagePullSecret` from a GitHub PAT with
   `read:packages` and reference it in each Deployment - not yet done or
   verified here.
2. Promote each service's manifest to point at a real tag:
   ```bash
   scripts/promote-image.sh all ghcr.io/vimla01/sentinel
   ```
3. Commit and push - ArgoCD only deploys what's in Git.

**One upside of the real cluster**: Slack's webhook can reach `remediator`
through GKE's own LoadBalancer/Ingress directly - no `cloudflared` tunnel
needed, unlike the local Kind setup
([Slack Approvals](#slack-approvals--external-reachability) above still
applies for anyone running this locally).

**Tear down** (this costs real money while it's up):
```bash
make gke-destroy GCP_PROJECT_ID=<your-project-id>
```

## Deploying to AKS

A separate Terraform root again (`infra/terraform-azure/`), for the same
reason as GKE: `azurerm` authenticates eagerly too, so it can't be a toggle
inside the local Kind setup without risking everyone's local `terraform
plan`.

This path exists specifically for **Azure for Students**
(`azure.microsoft.com/free/students`) - $100 credit, no credit card
required with a valid academic email, unlike GCP/AWS free trials which both
require one for billing verification regardless of whether you're a student.

**One-time setup:**
```bash
az login
```

**Provision the cluster** (AKS's control plane is free, unlike EKS - only
the node pool's VM is billed; defaults to one small `Standard_B2s` node to
stay well within a student credit):
```bash
make azure-apply
make azure-bootstrap
```
`azure-bootstrap` chains `az aks get-credentials` with
`scripts/bootstrap-argocd.sh sentinel azure` (same `kind`-context-skip
mechanism the `gke` arg uses).

**Images**: same caveat as GKE - `kind load docker-image` doesn't exist on
AKS either. Promote the manifests to real registry tags first:
```bash
scripts/promote-image.sh all ghcr.io/vimla01/sentinel
```
then commit and push, since ArgoCD only deploys what's in Git. Confirm the
GHCR packages are public, or configure an `imagePullSecret` from a GitHub
PAT - not yet done or verified here.

**Tear down** (this uses real credit while it's up):
```bash
make azure-destroy
```

## Deploying to EKS

A third separate Terraform root (`infra/terraform-aws/`), same reasoning as
the other two. EKS is meaningfully more involved than GKE Autopilot or AKS -
it needs a VPC with multi-AZ subnets plus IAM roles for the control plane
and node group, none of which the other two clouds required. This uses the
community `terraform-aws-modules/vpc` and `terraform-aws-modules/eks`
modules rather than hand-rolling that infrastructure - they're the de facto
standard for EKS on Terraform, referenced in AWS's own docs, and
dramatically reduce the chance of misconfiguration on something this
complex.

**Cost note that doesn't apply to GKE/AKS**: EKS's control plane itself is
billed (~$0.10/hour, ~$73/month) independent of node costs - GKE Autopilot's
and AKS's control planes are both free. Destroy this promptly after use,
not just when convenient.

**One-time setup:**
```bash
aws configure
```

**Provision the cluster** (single small `t3.small` node, to stretch a
limited credit):
```bash
make aws-apply
make aws-bootstrap
```
`aws-bootstrap` chains `aws eks update-kubeconfig` with
`scripts/bootstrap-argocd.sh sentinel aws`.

**Images**: same caveat as GKE/AKS - no `kind load` equivalent on EKS either:
```bash
scripts/promote-image.sh all ghcr.io/vimla01/sentinel
```
then commit and push.

**Tear down** (do this as soon as you're done - the control plane bills by
the hour regardless of whether anything is running on it):
```bash
make aws-destroy
```

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
