import httpx


class OllamaClient:
    """Thin wrapper around a local Ollama server's generate API."""

    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._model = model

    async def generate(self, prompt: str) -> str:
        response = await self._client.post(
            "/api/generate",
            json={"model": self._model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        return response.json().get("response", "")

    async def aclose(self) -> None:
        await self._client.aclose()
