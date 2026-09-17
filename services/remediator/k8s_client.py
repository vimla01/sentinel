import datetime
import os
from pathlib import Path

import httpx

_SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")


class K8sClient:
    """Thin wrapper around the Kubernetes API server's apps/v1 Deployment
    endpoints. Only knows how to do the two things remediator ever
    auto-executes against the cluster directly - restart (via a template
    annotation, the same mechanism `kubectl rollout restart` uses) and scale
    - since those are the only safe actions this platform hardcodes."""

    def __init__(
        self,
        base_url: str,
        token: str,
        namespace: str,
        timeout: float = 10.0,
        verify: bool | str = True,
    ) -> None:
        self._namespace = namespace
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            verify=verify,
            headers={"Authorization": f"Bearer {token}"},
        )

    @classmethod
    def in_cluster(cls, namespace: str, timeout: float = 10.0) -> "K8sClient":
        host = os.environ["KUBERNETES_SERVICE_HOST"]
        port = os.environ["KUBERNETES_SERVICE_PORT"]
        token = (_SA_DIR / "token").read_text().strip()
        return cls(
            base_url=f"https://{host}:{port}",
            token=token,
            namespace=namespace,
            timeout=timeout,
            verify=str(_SA_DIR / "ca.crt"),
        )

    async def restart_deployment(self, name: str) -> dict:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                    }
                }
            }
        }
        response = await self._client.patch(
            f"/apis/apps/v1/namespaces/{self._namespace}/deployments/{name}",
            json=patch,
            headers={"Content-Type": "application/strategic-merge-patch+json"},
        )
        response.raise_for_status()
        return response.json()

    async def scale_deployment(self, name: str, step: int, max_replicas: int) -> dict:
        current = await self._get_replicas(name)
        target = min(current + step, max_replicas)
        response = await self._client.patch(
            f"/apis/apps/v1/namespaces/{self._namespace}/deployments/{name}/scale",
            json={"spec": {"replicas": target}},
            headers={"Content-Type": "application/merge-patch+json"},
        )
        response.raise_for_status()
        return response.json()

    async def _get_replicas(self, name: str) -> int:
        response = await self._client.get(
            f"/apis/apps/v1/namespaces/{self._namespace}/deployments/{name}/scale"
        )
        response.raise_for_status()
        return int(response.json().get("spec", {}).get("replicas", 1))

    async def aclose(self) -> None:
        await self._client.aclose()
