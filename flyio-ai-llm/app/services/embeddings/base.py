"""Abstract base class for embedding providers."""

from abc import ABC, abstractmethod
from typing import List


class BaseEmbeddingProvider(ABC):
    """Protocol / interface for text embedding providers."""

    @abstractmethod
    async def embed_text(self, text: str) -> List[float]:
        """Convert input text string into a dense vector embedding."""
        pass

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Convert a batch of text strings into vector embeddings."""
        return [await self.embed_text(txt) for txt in texts]

