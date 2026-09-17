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

## Ollama model

The `ollama` deployment ships with no models baked in - pull one into its
pod after it's running, once per cluster (the model lives on the pod's
`emptyDir`, so it does not survive a pod restart in this local setup):

```bash
kubectl -n sentinel exec deploy/ollama -- ollama pull llama3
```

`diagnosis-agent`'s `OLLAMA_MODEL` env var (default `llama3`) must match
whatever model was pulled.

## Slack approvals

remediator only auto-executes restart/scale/rollback for diagnoses whose
runbook explicitly marks `approval_required: false` - everything else waits
on a Slack Approve/Deny click, so a working Slack app is required for any
non-auto remediation to ever complete. Create a Slack app with a bot token
(`chat:write` scope) and Interactivity enabled, pointing its Request URL at
this cluster's `remediator` service (`/slack/interactions` - requires the
service to be reachable from Slack's servers, e.g. via an Ingress and a
public DNS name; this repo does not provision one). Then create the secret
remediator reads its credentials from:

```bash
kubectl -n sentinel create secret generic remediator-slack \
  --from-literal=bot-token=xoxb-... \
  --from-literal=signing-secret=...
```

`remediator`'s `SLACK_CHANNEL` env var (default `#sentinel-incidents`) must
be a channel the bot has been invited to. Without this secret, remediator
still runs and still auto-executes safe actions - only the approval path is
unavailable, and it logs the failure to post rather than crashing.
