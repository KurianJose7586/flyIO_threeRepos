"""Local, offline embedding provider using fastembed (ONNX runtime).

No API key, no network call per request, and no per-token cost — the model
runs on-box. Chosen over sentence-transformers for the same model output
without a torch/CUDA dependency: fastembed is Qdrant's own library, built on
ONNX runtime specifically to avoid pulling in GBs of PyTorch for embedding-only
workloads (https://qdrant.github.io/fastembed/).
"""

import asyncio
from typing import ClassVar, Dict, List

from app.core.errors import LLMProviderError
from app.core.logging import logger
from app.services.embeddings.base import BaseEmbeddingProvider

# EmbeddingService (and therefore this provider) is constructed fresh on every
# request — see LLMService/StoreService, which build a new EmbeddingService()
# per call rather than holding a singleton. A fastembed TextEmbedding instance
# loads real model weights (~8s the first time; still real work on every load
# even once the file is disk-cached), so it must be cached at module level and
# shared across requests/instances, or every single API call would eat that
# cost. Keyed by model name so switching EMBEDDING_MODEL doesn't reuse a stale
# model.
_MODEL_CACHE: Dict[str, "object"] = {}
_MODEL_LOAD_LOCK = asyncio.Lock()


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    """Generates embeddings with a local fastembed (ONNX) model."""

    DEFAULT_MODEL: ClassVar[str] = "sentence-transformers/all-MiniLM-L6-v2"

    # Mirrors Settings.EMBEDDING_BATCH_SIZE so a provider built directly (in a
    # test, say) is bounded too rather than inheriting fastembed's 256.
    DEFAULT_BATCH_SIZE: ClassVar[int] = 8

    def __init__(self, model_name: str = DEFAULT_MODEL, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        self.model_name = model_name
        self.batch_size = max(1, batch_size)

    async def _get_model(self):
        """Return the cached model for self.model_name, loading it once if needed."""
        if self.model_name in _MODEL_CACHE:
            return _MODEL_CACHE[self.model_name]

        async with _MODEL_LOAD_LOCK:
            # Re-check: another request may have loaded it while we waited on the lock.
            if self.model_name in _MODEL_CACHE:
                return _MODEL_CACHE[self.model_name]

            try:
                from fastembed import TextEmbedding
            except ImportError as exc:
                raise LLMProviderError(
                    message="fastembed is not installed; required for EMBEDDING_PROVIDER=local",
                    code="EMBEDDING_CONFIG_ERROR",
                ) from exc

            logger.info(
                f"Loading local embedding model '{self.model_name}' (first use only; cached after)...",
                extra={"event": "local_embedding_model_load"},
            )
            # Model loading (and first-run download) is blocking CPU/IO work —
            # run off the event loop.
            model = await asyncio.to_thread(TextEmbedding, model_name=self.model_name)
            _MODEL_CACHE[self.model_name] = model
            return model

    async def embed_text(self, text: str) -> List[float]:
        """Convert a single text string into a vector embedding."""
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Convert a batch of text strings into vector embeddings.

        fastembed's own batching (not a per-text loop) — it's the whole reason
        to call embed_batch over repeated embed_text.

        batch_size is passed explicitly rather than left to fastembed's default
        of 256. Every document in a forward pass is padded to the longest one in
        it, so peak memory scales with batch_size * longest_sequence. Handing a
        whole store request (28 scraped chunks, longest ~4k chars) to a single
        batch measured 155s and then died with an onnxruntime
        "bad allocation" — the failure mode is an OOM, not just slowness, and a
        larger page would hit it sooner on a small VM.
        """
        if not texts:
            return []

        try:
            model = await self._get_model()
            # model.embed() is synchronous CPU-bound ONNX inference — run off
            # the event loop. Returns a generator of numpy arrays.
            embeddings = await asyncio.to_thread(
                lambda: list(model.embed(texts, batch_size=self.batch_size))
            )
            return [vec.tolist() for vec in embeddings]
        except LLMProviderError:
            raise
        except Exception as exc:
            # Matches the network-error handling convention in openai_provider.py:
            # don't override `code`, so this falls back to LLMProviderError's
            # class default (LLM_PROVIDER_ERROR).
            logger.error(f"Local embedding generation failed: {exc}", extra={"event": "local_embedding_error"})
            raise LLMProviderError(message=f"Local embedding provider error: {exc}") from exc
