#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${1:-sentinel}"
CLUSTER_PROVIDER="${2:-kind}"
ARGOCD_VERSION="${ARGOCD_VERSION:-stable}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v kubectl >/dev/null || { echo "kubectl is required" >&2; exit 1; }

if [ "${CLUSTER_PROVIDER}" = "kind" ]; then
  command -v kind >/dev/null || { echo "kind is required" >&2; exit 1; }
  kubectl config use-context "kind-${CLUSTER_NAME}"
else
  # gke (or any other provider): the caller already ran
  # `gcloud container clusters get-credentials`, which sets the current
  # context itself - no "kind-<name>" guess to make here.
  echo "Using current kubectl context: $(kubectl config current-context)"
fi
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd --server-side --force-conflicts -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
kubectl wait --for=condition=available --timeout=180s deployment/argocd-server -n argocd
kubectl apply -f "${REPO_ROOT}/infra/argocd/project.yaml"
kubectl -n argocd patch cm argocd-cm --type merge -p '{"data":{"resource.customizations.health.networking.k8s.io_Ingress":"hs = {}\nhs.status = \"Healthy\"\nreturn hs\n"}}'
kubectl apply -f "${REPO_ROOT}/infra/argocd/application.yaml"

echo "ArgoCD is bootstrapped for ${CLUSTER_NAME}."
echo "Inspect: kubectl -n argocd get applications.argoproj.io sentinel"