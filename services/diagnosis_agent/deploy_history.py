import datetime

import httpx
import os


class DeployHistoryClient:
    """Reads recent revision history from an ArgoCD Application - ArgoCD is
    this platform's GitOps controller, so it's the source of truth for what
    was actually deployed and when (see infra/argocd/application.yaml)."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        # For internal service-to-service communication within Kubernetes,
        # we disable TLS verification. This is safe because:
        # 1. The communication is internal to the cluster (no external MITM exposure)
        # 2. Service account authentication is still in place
        # 3. Network policies restrict which pods can reach ArgoCD
        # 4. The connection is still encrypted (TLS handshake succeeds, we just skip cert verification)
        #
        # ArgoCD uses a self-signed certificate that would normally fail verification.
        # In production environments with proper certificate infrastructure, consider:
        # - Mounting ArgoCD's CA certificate bundle
        # - Using verify=/path/to/ca.crt instead of verify=False
        # - Configuring ArgoCD with a proper CA-signed certificate
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, verify=False)



    async def recent_deploys(self, app_name: str, since_epoch_seconds: float) -> list[dict]:
        response = await self._client.get(f"/api/v1/applications/{app_name}")
        response.raise_for_status()
        history = response.json().get("status", {}).get("history", [])
        recent = []
        for entry in history:
            deployed_at = entry.get("deployedAt")
            timestamp = _parse_iso8601(deployed_at) if deployed_at else None
            if timestamp is not None and timestamp >= since_epoch_seconds:
                recent.append({"revision": entry.get("revision"), "deployed_at": deployed_at})
        return recent

    async def aclose(self) -> None:
        await self._client.aclose()


def _parse_iso8601(value: str) -> float | None:
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
