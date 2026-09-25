import httpx


class LokiClient:
    """Thin wrapper around Loki's range-query HTTP API."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def recent_logs(
        self, job: str, start_ns: int, end_ns: int, limit: int = 50
    ) -> list[str]:
        response = await self._client.get(
            "/loki/api/v1/query_range",
            params={
                "query": f'{{job="{job}"}}',
                "start": start_ns,
                "end": end_ns,
                "limit": limit,
                "direction": "backward",
            },
        )
        response.raise_for_status()
        streams = response.json().get("data", {}).get("result", [])
        lines: list[str] = []
        for stream in streams:
            for _, line in stream.get("values", []):
                lines.append(line)
        return lines

    async def aclose(self) -> None:
        await self._client.aclose()
