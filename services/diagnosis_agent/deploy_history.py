import datetime

import httpx


class DeployHistoryClient:
    """Reads recent revision history from an ArgoCD Application - ArgoCD is
    this platform's GitOps controller, so it's the source of truth for what
    was actually deployed and when (see infra/argocd/application.yaml)."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

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
