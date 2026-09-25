import logging
import httpx
import asyncio

logger = logging.getLogger(__name__)


class OllamaClient:
    """Thin wrapper around a local Ollama server's generate API with retries and logging."""

    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        timeout_config = httpx.Timeout(timeout, connect=5.0)
        self._base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_config)
        self._model = model

    async def generate(self, prompt: str) -> str:
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    f"Ollama Request (Attempt {attempt}/{max_retries}) - URL: {self._base_url}/api/generate, Model: {self._model}"
                )
                response = await self._client.post(
                    "/api/generate",
                    json={"model": self._model, "prompt": prompt, "stream": False},
                )
                response.raise_for_status()
                try:
                    data = response.json()
                    return data.get("response", "")
                except ValueError:
                    logger.error(
                        f"Malformed JSON response from Ollama: {response.text}"
                    )
                    if attempt == max_retries:
                        raise
            except httpx.RequestError as e:
                logger.error(f"Transient network error communicating with Ollama: {e}")
                if attempt == max_retries:
                    raise
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error from Ollama: {e.response.status_code} - {e.response.text}"
                )
                if attempt == max_retries:
                    raise

            await asyncio.sleep(2**attempt)

        return ""

    async def aclose(self) -> None:
        await self._client.aclose()
