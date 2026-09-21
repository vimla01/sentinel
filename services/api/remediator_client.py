import httpx


class RemediatorClient:
    """Thin wrapper around remediator's HTTP API."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def get_remediations(self) -> list[dict]:
        response = await self._client.get("/remediations")
        response.raise_for_status()
        return response.json().get("remediations", [])

    async def aclose(self) -> None:
        await self._client.aclose()
