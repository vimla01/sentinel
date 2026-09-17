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
