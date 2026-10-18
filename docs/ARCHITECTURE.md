# Architecture

SENTINEL is six independently deployable services sitting on top of a
Kubernetes cluster, communicating entirely by polling each other's HTTP
APIs - no message queue, no service mesh. ArgoCD reconciles the cluster
from Git; Terraform provisions the cluster itself. This doc describes the
system as it actually exists today, not the Phase 0 snapshot it used to
describe.

## Components

| Service | Responsibility | Source |
|---|---|---|
| `hello` | Minimal health-check service from the project's bootstrap phase | `services/hello/` |
| `demo-api` | Chaos-injectable target workload (`/debug/*` endpoints simulate memory leaks, CPU spikes, latency, error bursts) | `services/demo_api/` |
| `predictor` | Polls Prometheus, keeps a rolling mean/stddev baseline per metric (CPU, memory, latency, error rate), fires an alert when a metric's z-score crosses a threshold | `services/predictor/` |
| `diagnosis-agent` | Polls predictor's alerts; for each new one, pulls recent Loki logs + ArgoCD deploy history, matches a runbook, and asks a local LLM (Ollama) for a grounded root cause + recommended action | `services/diagnosis_agent/` |
| `remediator` | Polls diagnosis-agent's output; auto-executes restart/scale/rollback when a runbook says it's safe, otherwise posts a Slack approval request and waits; verifies the outcome afterward (Phase 6) | `services/remediator/` |
| `api` | Polls all three of the above and correlates them into one persisted incident record per alert, keyed by `(metric, fired_at)`; the only durable state in the platform - everything else is in-memory | `services/api/` |

Third-party infrastructure (not built by this project, deployed via upstream
images): **Prometheus** (metrics), **Loki + Promtail** (logs), **Grafana**
(dashboards), **Ollama** (local LLM runtime).

## Communication: pull everywhere, one push

Every service-to-service call is the same shape: poll the one upstream of
you on a timer, remember what you've already processed, act on what's new.
`predictor` polls Prometheus; `diagnosis-agent` polls `predictor`;
`remediator` polls `diagnosis-agent`; `api` polls all three. Service
discovery is plain Kubernetes DNS (`http://predictor:8080`, etc.) - no
registry, no mesh.

The one exception is Slack: when `remediator` needs human approval, it
posts an interactive message and then genuinely waits - the only inbound
push in the entire system is Slack's own webhook calling back into
`remediator`'s `/slack/interactions`, HMAC-verified against Slack's
signing secret.

```
  demo-api --metrics--> Prometheus <--poll-- predictor --alert--> diagnosis-agent
                                                                         |
                                            Loki (logs) + ArgoCD (deploys) -- grounds the prompt
                                                                         |
                                                                         v
                                                              Ollama (local LLM)
                                                                         |
                                                                         v
                                                                  diagnosis-agent
                                                                         |
                                                                  (polled by)
                                                                         v
                                                                    remediator
                                                        /                        \
                                      safe + approval_required:false      otherwise
                                               |                                |
                                    Kubernetes API / ArgoCD              Slack approval
                                    (restart / scale / rollback)         (waits for a click)
                                               |                                |
                                               \--------------------------------/
                                                            |
                                                   post-remediation health
                                                   verification (Phase 6)
                                                            |
                                                            v
                                              api (correlates predictor +
                                              diagnosis-agent + remediator
                                              into one incident record)
                                                            |
                                                            v
                                               SQLite (durable) + Prometheus
                                               gauges -> Grafana dashboard
```

## Safety model

Only `restart`, `scale`, and `rollback` are ever auto-executed, and only
when **both** the matched runbook says `approval_required: false` **and**
the LLM's recommended action text matches one of those three categories
(`services/remediator/policy.py`) - a runbook's flag alone can't bypass a
human; the action text has to say one of the three safe words too. Everything
else blocks on a signed Slack approval. `restart`/`scale` act directly via
the Kubernetes API using a dedicated least-privilege service account
(`remediator` is the only workload with write access to the cluster -
everything else shares a read-only one); `rollback` goes through ArgoCD's
own API rather than a raw `kubectl` rollback, since a raw rollback would
fight ArgoCD's `selfHeal: true` sync policy.

## Infrastructure layer

- **Terraform** (`infra/terraform/`) provisions exactly one thing: a local
  two-node **Kind** cluster, via a `null_resource` wrapping the `kind` CLI.
  No cloud provider is configured (the only Terraform provider in use is
  `hashicorp/null`) - this runs entirely on local Docker, not Azure/AWS/GCP.
- **ArgoCD** (`infra/argocd/`) watches `infra/k8s` on `main` and
  continuously reconciles the cluster to match it (`prune: true`,
  `selfHeal: true`) - verified live: a manual `kubectl` edit against a
  running Deployment gets silently reverted within the next reconcile cycle.
  Nobody runs `kubectl apply` by hand against this cluster.
- **CI** runs twice, independently: GitHub Actions (`.github/workflows/ci.yml`)
  and a local Jenkins pipeline (`Jenkinsfile`, `infra/jenkins/`) - both do
  the same thing (black → pylint → pytest with an 80% coverage gate → build
  all 6 images), neither currently promotes a built image's tag into the
  Git-tracked manifests (`scripts/promote-image.sh` does that manually - see
  [docs/DEPLOYMENT.md](./DEPLOYMENT.md#known-gaps)).
- **A cloud deployment is not yet running, but the Terraform for three
  options exists.** `infra/terraform-gke/` (GKE Autopilot),
  `infra/terraform-azure/` (AKS), and `infra/terraform-aws/` (EKS) are each
  a fully separate Terraform root from local Kind, not a flag on it - the
  `google`, `azurerm`, and `aws` providers all authenticate eagerly even
  when unused, which would otherwise force every local `terraform plan` to
  need cloud credentials it has no reason to need. All three validated
  (`terraform validate`, a real `plan` reaching each cloud's own auth check)
  but none applied yet - no cluster has actually been created on any of
  them. Each exists for a different practical reason hit while trying to
  get a real account working: GCP/AWS normally require a credit card for
  billing verification regardless of student status (Azure for Students is
  the one that doesn't, hence AKS); EKS exists because a
  already-confirmed-working AWS Educate account became available. EKS is
  also the most involved of the three - it needs a VPC and IAM roles the
  other two don't, via the community `terraform-aws-modules` rather than
  hand-rolled resources. See
  [docs/DEPLOYMENT.md#deploying-to-gke](./DEPLOYMENT.md#deploying-to-gke),
  [docs/DEPLOYMENT.md#deploying-to-aks](./DEPLOYMENT.md#deploying-to-aks),
  and [docs/DEPLOYMENT.md#deploying-to-eks](./DEPLOYMENT.md#deploying-to-eks).

## Known gaps

See [docs/DEPLOYMENT.md#known-gaps](./DEPLOYMENT.md#known-gaps) for the
full, current list (CI→deploy promotion, git-native rollback credentials,
the currently-inert remediator Ingress). Kept in one place rather than
duplicated here so it can't drift out of sync with itself.
