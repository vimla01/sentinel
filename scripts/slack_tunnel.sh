#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# SENTINEL - Slack Webhook Local Reachability Tunnel Helper
# ==============================================================================
# This script enables external reachability for Slack interactive callbacks
# (/slack/interactions) in local Kind / development environments.
#
# Prerequisites:
# 1. Kind cluster running with the remediator service deployed
# 2. Slack App created at https://api.slack.com/apps with Interactivity enabled
# 3. Optional: cloudflared or ngrok installed for public webhook tunneling
# ==============================================================================

LOCAL_PORT="${LOCAL_PORT:-8082}"
NAMESPACE="${NAMESPACE:-sentinel}"
SERVICE="${SERVICE:-remediator}"

echo "=== SENTINEL Slack Webhook Tunnel ==="
echo "Forwarding service/${SERVICE} in namespace '${NAMESPACE}' to localhost:${LOCAL_PORT}..."

# Start port-forward in background
kubectl port-forward -n "${NAMESPACE}" "svc/${SERVICE}" "${LOCAL_PORT}:8080" &
PF_PID=$!

trap "echo 'Stopping port-forward (PID: ${PF_PID})...'; kill ${PF_PID} 2>/dev/null || true" EXIT INT TERM

sleep 2

# Check if port forward is responding
if curl -s "http://127.0.0.1:${LOCAL_PORT}/healthz" >/dev/null; then
    echo "✓ remediator is reachable locally at http://127.0.0.1:${LOCAL_PORT}"
else
    echo "WARNING: remediator health check failed. Ensure the pod is running."
fi

echo ""
echo "----------------------------------------------------------------------"
echo "HOW TO EXPOSE LOCALLY FOR SLACK INTERACTIVITY:"
echo "----------------------------------------------------------------------"
echo "Option A (Cloudflare Tunnel - recommended, free, no account needed):"
echo "  cloudflared tunnel --url http://localhost:${LOCAL_PORT}"
echo ""
echo "Option B (ngrok):"
echo "  ngrok http ${LOCAL_PORT}"
echo ""
echo "Then copy the generated HTTPS URL (e.g. https://xyz.trycloudflare.com)"
echo "and configure your Slack App Interactivity Request URL as:"
echo "  https://<your-tunnel-domain>/slack/interactions"
echo "----------------------------------------------------------------------"
echo ""
echo "Tunnel proxy running. Press Ctrl+C to stop."
wait "${PF_PID}"
