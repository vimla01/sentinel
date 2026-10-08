import logging
import httpx

logger = logging.getLogger("remediator.argocd")


class ArgocdClient:
    """Manages ArgoCD Application reconciliation and rollback.
    A raw kubectl-level rollback fights ArgoCD's `selfHeal: true` policy.
    To ensure changes persist, the remediation can be committed directly to
    Git via GitClient and reconciled via ArgoCD sync, representing the desired
    state natively in Git."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def get_previous_revision(self, app_name: str) -> dict:
        response = await self._client.get(f"/api/v1/applications/{app_name}")
        response.raise_for_status()
        history = response.json().get("status", {}).get("history", [])
        if len(history) < 2:
            raise ValueError(f"no previous revision to roll back to for app={app_name}")
        return history[-2]

    async def sync(self, app_name: str, revision: str | None = None) -> dict:
        payload: dict = {"prune": True}
        if revision:
            payload["revision"] = revision
        try:
            response = await self._client.post(
                f"/api/v1/applications/{app_name}/sync",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logger.warning("argocd sync failed for app=%s: %s", app_name, exc)
            return {}

    async def rollback(
        self,
        app_name: str,
        target_revision: str | None = None,
        git_client=None,
        target_deployment: str | None = None,
    ) -> dict:
        previous = await self.get_previous_revision(app_name)
        prev_rev = (
            target_revision or previous.get("revision") or str(previous.get("id"))
        )

        git_commit = None
        if git_client and git_client.is_git_repo():
            try:
                git_commit = git_client.rollback_deployment(
                    target_deployment or "demo-api", prev_rev
                )
                logger.info(
                    "git-native rollback committed: %s for %s",
                    git_commit,
                    target_deployment,
                )
            except Exception as exc:
                logger.warning(
                    "git-native rollback commit failed: %s; falling back to direct sync",
                    exc,
                )

        # Trigger ArgoCD sync to reconcile from Git
        await self.sync(app_name, revision=git_commit)

        # Call rollback API for backward compatibility with ArgoCD deployments
        try:
            rollback_response = await self._client.post(
                f"/api/v1/applications/{app_name}/rollback",
                json={"id": previous.get("id")},
            )
            rollback_response.raise_for_status()
        except httpx.HTTPError:
            pass

        return {
            "rolled_back_to": previous,
            "revision": git_commit or prev_rev,
        }

    async def aclose(self) -> None:
        await self._client.aclose()
