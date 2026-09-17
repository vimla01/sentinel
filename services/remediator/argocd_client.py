import httpx


class ArgocdClient:
    """Rolls back an ArgoCD-managed Application to its previous synced
    revision. A raw kubectl-level rollback would fight ArgoCD's `selfHeal:
    true` sync policy (infra/argocd/application.yaml), so remediation goes
    through ArgoCD's own rollback API instead - the same source of truth
    diagnosis-agent's DeployHistoryClient already reads."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def rollback(self, app_name: str) -> dict:
        response = await self._client.get(f"/api/v1/applications/{app_name}")
        response.raise_for_status()
        history = response.json().get("status", {}).get("history", [])
        if len(history) < 2:
            raise ValueError(f"no previous revision to roll back to for app={app_name}")
        previous = history[-2]
        rollback_response = await self._client.post(
            f"/api/v1/applications/{app_name}/rollback",
            json={"id": previous.get("id")},
        )
        rollback_response.raise_for_status()
        return {"rolled_back_to": previous}

    async def aclose(self) -> None:
        await self._client.aclose()
