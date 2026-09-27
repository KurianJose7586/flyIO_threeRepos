"""Embedding service abstraction layer."""

from typing import List, Optional
from app.core.config import Settings, get_settings
from app.core.logging import logger
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.local_provider import LocalEmbeddingProvider
from app.services.embeddings.mock_provider import MockEmbeddingProvider
from app.services.embeddings.openai_provider import OpenAIEmbeddingProvider


class EmbeddingService:
    """Service providing text embeddings with pluggable provider support."""

    def __init__(
        self,
        provider: Optional[BaseEmbeddingProvider] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or self._resolve_provider()

    def _resolve_provider(self) -> BaseEmbeddingProvider:
        """Resolve embedding provider instance based on application settings."""
        provider_name = self.settings.EMBEDDING_PROVIDER.lower()
        if provider_name == "openai":
            logger.info("Using OpenAI embedding provider", extra={"event": "embedding_provider_init"})
            return OpenAIEmbeddingProvider(
                api_key=self.settings.EMBEDDING_API_KEY,
                model=self.settings.EMBEDDING_MODEL,
                dimension=self.settings.EMBEDDING_DIMENSION,
            )
        elif provider_name == "local":
            logger.info("Using local (fastembed/ONNX) embedding provider", extra={"event": "embedding_provider_init"})
            return LocalEmbeddingProvider(
                model_name=self.settings.EMBEDDING_MODEL or LocalEmbeddingProvider.DEFAULT_MODEL,
                batch_size=self.settings.EMBEDDING_BATCH_SIZE,
            )
        else:
            logger.info("Using Mock embedding provider", extra={"event": "embedding_provider_init"})
            return MockEmbeddingProvider(dimension=self.settings.EMBEDDING_DIMENSION)

    async def embed_query(self, query: str) -> List[float]:
        """Convert a search query into an embedding vector."""
        return await self.provider.embed_text(query)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Convert a batch of text strings into vector embeddings."""
        return await self.provider.embed_batch(texts)

