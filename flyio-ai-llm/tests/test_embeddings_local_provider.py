"""Real (unmocked) tests for LocalEmbeddingProvider — no API key required.

Unlike the OpenAI/Groq providers, this one needs no external credential to
verify for real, only (on first run in a given environment) a one-time model
download from Hugging Face. It is deliberately NOT mocked here: Phase 2's
whole point is that the mock/openai providers were the only ones ever
executed, and the real providers had never run once.
"""

import math

import pytest

from app.core.config import Settings
from app.services.embeddings.local_provider import LocalEmbeddingProvider
from app.services.embeddings.service import EmbeddingService


@pytest.mark.asyncio
async def test_local_provider_embed_text_returns_correct_dimension():
    """all-MiniLM-L6-v2 (fastembed's ONNX build) outputs 384-dim vectors —
    this must match EMBEDDING_DIMENSION=384 documented in .env.example, since
    QdrantService creates the collection with that configured size, not the
    provider's actual output size.
    """
    provider = LocalEmbeddingProvider()
    vector = await provider.embed_text("Paris is the capital of France.")
    assert len(vector) == 384
    assert all(isinstance(x, float) for x in vector)


@pytest.mark.asyncio
async def test_local_provider_vectors_are_normalized():
    """fastembed's default output is already L2-normalized, which matters for
    Qdrant's COSINE distance collections (see qdrant/service.py ensure_collection).
    """
    provider = LocalEmbeddingProvider()
    vector = await provider.embed_text("A normalization sanity check sentence.")
    norm = math.sqrt(sum(x * x for x in vector))
    assert pytest.approx(norm, abs=0.01) == 1.0


@pytest.mark.asyncio
async def test_local_provider_embed_batch_matches_embed_text():
    """Batch embedding must produce the same vectors (order preserved) as
    embedding each text individually — this is the real behavior StoreService
    depends on when it calls embed_batch() once for all chunks in a request.
    """
    provider = LocalEmbeddingProvider()
    texts = ["Paris is the capital of France.", "Tokyo is the capital of Japan."]

    batch_vectors = await provider.embed_batch(texts)
    individual_vectors = [await provider.embed_text(t) for t in texts]

    assert len(batch_vectors) == 2
    for batch_vec, individual_vec in zip(batch_vectors, individual_vectors):
        assert batch_vec == pytest.approx(individual_vec, abs=1e-5)


@pytest.mark.asyncio
async def test_local_provider_semantic_similarity_is_meaningful():
    """Real behavioral check, not just shape: two sentences about the same
    topic should be measurably closer than two sentences about unrelated
    topics. This is what actually makes retrieval work — Mock*EmbeddingProvider
    (md5-hash-seeded pseudorandom) cannot satisfy this at all, which is
    exactly why the retrieval path had never been genuinely exercised before
    this phase (see Phase 2 plan notes on the mock-embedding threshold issue).
    """
    provider = LocalEmbeddingProvider()
    paris_a = await provider.embed_text("The Eiffel Tower is a famous landmark in Paris, France.")
    paris_b = await provider.embed_text("Paris, France is home to the Louvre Museum and great food.")
    unrelated = await provider.embed_text("Quarterly tax filing deadlines for small businesses.")

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        return dot / (norm_a * norm_b)

    sim_related = cosine(paris_a, paris_b)
    sim_unrelated = cosine(paris_a, unrelated)
    assert sim_related > sim_unrelated
    # Loose bound, not tuned to the exact model version — just confirms the
    # embeddings carry real semantic signal rather than being noise.
    assert sim_related > 0.4


@pytest.mark.asyncio
async def test_embedding_service_resolves_local_provider_from_settings():
    """EMBEDDING_PROVIDER='local' must actually select LocalEmbeddingProvider
    via the factory, not silently fall through to Mock (the `else` branch).
    """
    settings = Settings(
        EMBEDDING_PROVIDER="local",
        EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L6-v2",
        EMBEDDING_DIMENSION=384,
    )
    service = EmbeddingService(settings=settings)
    assert isinstance(service.provider, LocalEmbeddingProvider)

    vector = await service.embed_query("Plan a trip to Paris")
    assert len(vector) == 384


# --- batch_size must be bounded, not fastembed's default of 256 ---

@pytest.mark.asyncio
async def test_embed_batch_passes_bounded_batch_size_to_fastembed():
    """fastembed pads every document in a forward pass to the longest one in
    it, so peak memory scales with batch_size * longest_sequence rather than
    with the average. Handing it a whole store request at the library default
    of 256 measured 155s for one scraped page (28 chunks) and then died with an
    onnxruntime "bad allocation" — an OOM, not merely slow.

    Asserting the argument is actually forwarded, because the failure it
    prevents only reproduces under memory pressure and would otherwise pass
    every functional test right up until it OOMs on a small VM.
    """
    provider = LocalEmbeddingProvider(batch_size=4)
    seen = {}

    class FakeModel:
        def embed(self, texts, batch_size=256, **kwargs):
            seen["batch_size"] = batch_size
            seen["n_texts"] = len(list(texts))
            import numpy as np
            return iter([np.zeros(384) for _ in range(seen["n_texts"])])

    async def fake_get_model():
        return FakeModel()

    provider._get_model = fake_get_model
    await provider.embed_batch(["a", "b", "c", "d", "e"])

    assert seen["batch_size"] == 4, "batch_size was not forwarded; fastembed's 256 default applies"
    assert seen["n_texts"] == 5


def test_batch_size_is_floored_at_one():
    """A zero or negative batch_size would make fastembed's batching degenerate;
    clamp instead of failing at inference time.
    """
    assert LocalEmbeddingProvider(batch_size=0).batch_size == 1
    assert LocalEmbeddingProvider(batch_size=-5).batch_size == 1


def test_embedding_service_wires_configured_batch_size():
    """The setting must actually reach the provider — the default is only
    useful if EmbeddingService passes it through.
    """
    settings = Settings(
        _env_file=None,
        EMBEDDING_PROVIDER="local",
        EMBEDDING_MODEL="BAAI/bge-base-en-v1.5",
        EMBEDDING_BATCH_SIZE=3,
    )
    service = EmbeddingService(settings=settings)
    assert isinstance(service.provider, LocalEmbeddingProvider)
    assert service.provider.batch_size == 3
