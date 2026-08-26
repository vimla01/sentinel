import httpx


class PrometheusClient:
    """Thin wrapper around the Prometheus HTTP query API."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def instant_query(self, promql: str) -> float | None:
        response = await self._client.get("/api/v1/query", params={"query": promql})
        response.raise_for_status()
        result = response.json().get("data", {}).get("result", [])
        if not result:
            return None
        return float(result[0]["value"][1])

    async def aclose(self) -> None:
        await self._client.aclose()
