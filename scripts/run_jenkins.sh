#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/infra/jenkins/docker-compose.yml"

command -v docker >/dev/null || { echo "ERROR: docker is required" >&2; exit 1; }

# Detect host docker socket group ID so Jenkins user inside container can access docker.sock
if [ -S /var/run/docker.sock ]; then
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
else
    echo "ERROR: /var/run/docker.sock not found. Ensure Docker daemon is running." >&2
    exit 1
fi
export DOCKER_GID

ACTION="${1:-start}"

case "${ACTION}" in
    start|up)
        echo "=========================================================="
        echo "Starting Local Jenkins for SENTINEL (Stage A)"
        echo "Host Docker GID: ${DOCKER_GID}"
        echo "=========================================================="
        docker compose -f "${COMPOSE_FILE}" up -d --build
        echo "Waiting for Jenkins to initialize on http://localhost:8080..."
        sleep 5
        echo ""
        echo "Jenkins is starting. Once ready, retrieve the initial admin password with:"
        echo "  docker exec sentinel-jenkins cat /var/jenkins_home/secrets/initialAdminPassword"
        echo "Access UI: http://localhost:8080"
        ;;
    stop|down)
        echo "Stopping Jenkins container..."
        docker compose -f "${COMPOSE_FILE}" down
        ;;
    logs)
        docker compose -f "${COMPOSE_FILE}" logs -f jenkins
        ;;
    password)
        docker exec sentinel-jenkins cat /var/jenkins_home/secrets/initialAdminPassword 2>/dev/null || echo "Jenkins is still initializing or password already changed."
        ;;
    status)
        docker compose -f "${COMPOSE_FILE}" ps
        ;;
    *)
        echo "Usage: $0 [start|stop|logs|password|status]"
        exit 1
        ;;
esac
