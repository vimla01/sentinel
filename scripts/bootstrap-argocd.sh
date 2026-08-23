#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${1:-sentinel}"
ARGOCD_VERSION="${ARGOCD_VERSION:-stable}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v kubectl >/dev/null || { echo "kubectl is required" >&2; exit 1; }
command -v kind >/dev/null || { echo "kind is required" >&2; exit 1; }

kubectl config use-context "kind-${CLUSTER_NAME}"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
kubectl wait --for=condition=available --timeout=180s deployment/argocd-server -n argocd
kubectl apply -f "${REPO_ROOT}/infra/argocd/project.yaml"
kubectl apply -f "${REPO_ROOT}/infra/argocd/application.yaml"

echo "ArgoCD is bootstrapped for ${CLUSTER_NAME}."
echo "Inspect: kubectl -n argocd get applications.argoproj.io sentinel"
