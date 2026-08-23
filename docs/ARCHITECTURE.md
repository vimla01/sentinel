# Architecture

Phase 0 establishes a local Kind cluster, ArgoCD as the GitOps controller, and a least-privilege hello service. Terraform owns cluster lifecycle; ArgoCD owns Kubernetes application resources.
