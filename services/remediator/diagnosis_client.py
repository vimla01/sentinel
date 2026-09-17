import httpx


class DiagnosisAgentClient:
    """Thin wrapper around diagnosis-agent's HTTP API."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def get_diagnoses(self) -> list[dict]:
        response = await self._client.get("/diagnoses")
        response.raise_for_status()
        return response.json().get("diagnoses", [])

    async def aclose(self) -> None:
        await self._client.aclose()
