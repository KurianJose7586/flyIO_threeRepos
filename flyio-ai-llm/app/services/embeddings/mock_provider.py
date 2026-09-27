"""Mock embedding provider generating deterministic vector representations."""

import hashlib
import math
from typing import List
from app.services.embeddings.base import BaseEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Generates deterministic, normalized mock embeddings without external network calls."""

    def __init__(self, dimension: int = 1536) -> None:
        self.dimension = dimension

    async def embed_text(self, text: str) -> List[float]:
        """Generate a deterministic normalized float vector of length `dimension`."""
        if not text:
            return [0.0] * self.dimension

        # Generate seed from md5 hash
        seed = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
        
        # Simple pseudo-random linear congruential generator for reproducibility
        vector: List[float] = []
        state = seed
        for _ in range(self.dimension):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            val = (state / 0x7FFFFFFF) * 2.0 - 1.0
            vector.append(val)

        # Normalize vector to unit length for cosine similarity
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0:
            vector = [x / norm for x in vector]

        return vector

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate deterministic normalized vector embeddings for a list of text strings."""
        return [await self.embed_text(txt) for txt in texts]

