#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# SENTINEL - Manual image promotion helper
# ==============================================================================
# Closes the gap between "CI builds and pushes an image" and "ArgoCD deploys
# it": CI never updates the Git-tracked manifests on its own (deliberately -
# auto-committing to main from CI is a bigger decision than this script should
# make for you, especially with another contributor actively pushing to this
# repo). This script only edits infra/k8s locally and prints a diff. It never
# commits or pushes - review the diff, then commit and push yourself.
#
# Usage:
#   scripts/promote-image.sh <service> <full-image-ref>
#   scripts/promote-image.sh api ghcr.io/vimla01/sentinel/api:abc1234
#
#   scripts/promote-image.sh all ghcr.io/vimla01/sentinel
#     (promotes every service to <registry>/<service>:<current-git-sha>)
# ==============================================================================

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICES=(hello demo-api predictor diagnosis-agent remediator api)

usage() {
  echo "Usage: $0 <service|all> <image-ref>" >&2
  echo "  service:   one of ${SERVICES[*]}, or 'all'" >&2
  echo "  image-ref: full image ref for a single service (e.g. ghcr.io/org/repo/api:sha123)," >&2
  echo "             or a registry prefix when service='all' (each service keeps its own" >&2
  echo "             name, tagged with the current git short SHA)" >&2
  exit 1
}

[ $# -eq 2 ] || usage
TARGET="$1"
IMAGE_REF="$2"

promote_one() {
  local service="$1" image="$2"
  local deployment="${REPO_ROOT}/infra/k8s/apps/${service}/deployment.yaml"
  if [ ! -f "$deployment" ]; then
    echo "no deployment.yaml for service=${service}" >&2
    return 1
  fi
  sed -i -E "s#image: sentinel/${service}:[A-Za-z0-9._-]+#image: ${image}#" "$deployment"
  echo "promoted ${service} -> ${image}"
}

if [ "$TARGET" = "all" ]; then
  SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
  for svc in "${SERVICES[@]}"; do
    promote_one "$svc" "${IMAGE_REF}/${svc}:${SHA}"
  done
elif printf '%s\n' "${SERVICES[@]}" | grep -qx "$TARGET"; then
  promote_one "$TARGET" "$IMAGE_REF"
else
  echo "unknown service '${TARGET}' (expected one of: ${SERVICES[*]}, or 'all')" >&2
  exit 1
fi

echo
echo "----------------------------------------------------------------------"
echo "Nothing committed or pushed. Review the diff below, then:"
echo "  git add infra/k8s && git commit -m 'deploy: promote image(s)' && git push"
echo "----------------------------------------------------------------------"
git -C "$REPO_ROOT" --no-pager diff -- infra/k8s
