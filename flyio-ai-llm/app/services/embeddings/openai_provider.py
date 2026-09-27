"""OpenAI-compatible embedding provider using HTTP client."""

from typing import List, Optional
import httpx

from app.core.errors import LLMProviderError
from app.core.logging import logger
from app.services.embeddings.base import BaseEmbeddingProvider


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """Generates embeddings via OpenAI or OpenAI-compatible REST API."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str = "https://api.openai.com/v1",
        dimension: Optional[int] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.dimension = dimension

    async def embed_text(self, text: str) -> List[float]:
        """Call OpenAI embeddings endpoint."""
        if not self.api_key:
            raise LLMProviderError(
                message="EMBEDDING_API_KEY is not configured for OpenAI provider",
                code="EMBEDDING_CONFIG_ERROR",
            )

        payload = {
            "input": text,
            "model": self.model,
        }
        if self.dimension:
            payload["dimensions"] = self.dimension

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    json=payload,
                    headers=headers,
                )

            if response.status_code != 200:
                logger.error(
                    f"OpenAI embedding request failed: status={response.status_code} body={response.text}",
                    extra={"event": "openai_embedding_error"},
                )
                raise LLMProviderError(
                    message=f"OpenAI embedding error: HTTP {response.status_code}",
                    details={"response": response.text},
                )

            data = response.json()
            return data["data"][0]["embedding"]

        except httpx.RequestError as exc:
            logger.error(f"Network error during OpenAI embedding: {exc}", extra={"event": "openai_embedding_network_error"})
            raise LLMProviderError(message=f"Network error connecting to embedding provider: {str(exc)}")

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Call OpenAI embeddings endpoint for a batch of text strings."""
        if not texts:
            return []
        if not self.api_key:
            raise LLMProviderError(
                message="EMBEDDING_API_KEY is not configured for OpenAI provider",
                code="EMBEDDING_CONFIG_ERROR",
            )

        payload = {
            "input": texts,
            "model": self.model,
        }
        if self.dimension:
            payload["dimensions"] = self.dimension

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    json=payload,
                    headers=headers,
                )

            if response.status_code != 200:
                logger.error(
                    f"OpenAI batch embedding request failed: status={response.status_code} body={response.text}",
                    extra={"event": "openai_embedding_batch_error"},
                )
                raise LLMProviderError(
                    message=f"OpenAI embedding error: HTTP {response.status_code}",
                    details={"response": response.text},
                )

            data = response.json()
            # OpenAI returns items sorted by index key
            items = sorted(data["data"], key=lambda item: item["index"])
            return [item["embedding"] for item in items]

        except httpx.RequestError as exc:
            logger.error(f"Network error during OpenAI batch embedding: {exc}", extra={"event": "openai_embedding_network_error"})
            raise LLMProviderError(message=f"Network error connecting to embedding provider: {str(exc)}")

