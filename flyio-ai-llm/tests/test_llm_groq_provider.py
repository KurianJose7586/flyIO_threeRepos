"""Real (unmocked) tests against the live Groq API.

Skipped automatically when no GROQ_API_KEY_FOR_TESTS is set — this hits a
real external API and costs a real (free-tier) request, so it must not
block anyone else's `pytest` run or a future CI job that has no key
configured. Run explicitly with:

    GROQ_API_KEY_FOR_TESTS=gsk_... pytest tests/test_llm_groq_provider.py
"""

import json
import os

import pytest

from app.core.config import Settings
from app.schemas.generate import TravelPlan
from app.services.llm.openai_provider import OpenAILLMProvider
from app.services.llm.service import LLMService
from app.services.prompt_builder import PromptBuilder

GROQ_KEY = os.environ.get("GROQ_API_KEY_FOR_TESTS", "")

pytestmark = pytest.mark.skipif(
    not GROQ_KEY,
    reason="GROQ_API_KEY_FOR_TESTS not set — skipping real Groq API tests",
)


@pytest.mark.asyncio
async def test_groq_provider_returns_valid_json_matching_travel_plan_schema():
    """The real, whole-point-of-this-phase check: does a real LLM response
    (not MockLLMProvider's canned JSON) actually satisfy TravelPlan via the
    same parse path LLMService uses, including response_format=json_object?
    """
    provider = OpenAILLMProvider(
        api_key=GROQ_KEY,
        model="openai/gpt-oss-120b",
        base_url="https://api.groq.com/openai/v1",
    )
    builder = PromptBuilder()
    system_prompt = builder.build_system_prompt()
    context = (
        "Paris is the capital of France. The Eiffel Tower, Louvre Museum, and "
        "Notre-Dame Cathedral are top attractions. Best visited in spring."
    )
    user_prompt = builder.build_user_prompt("Plan a 3-day trip to Paris", context)

    raw_response = await provider.generate(
        prompt=user_prompt,
        context=context,
        system_prompt=system_prompt,
    )

    # Must be parseable JSON at all (not markdown-wrapped, not conversational text).
    parsed = json.loads(raw_response)
    assert isinstance(parsed, dict)

    # Must actually satisfy the schema LLMService parses responses into.
    plan = TravelPlan.model_validate(parsed)
    assert "Paris" in plan.title or any("Paris" in d.name for d in plan.destinations)
    assert len(plan.destinations) > 0


@pytest.mark.asyncio
async def test_llm_service_end_to_end_with_real_groq_and_real_qdrant():
    """Full Workflow A (see FlyIO_Project_Context.md) with every mock removed:
    real local (fastembed) embeddings, real in-memory Qdrant (real vector
    math, not a stub), and a real Groq completion — store, then generate,
    exactly as Admin -> LLM Store -> LLM Generate would in production.

    QDRANT_SEARCH_SCORE_THRESHOLD is set explicitly here (0.40, slightly
    below config.py's own now-adjusted default of 0.45) so this test doesn't
    silently depend on whatever the global default happens to be. Measured
    directly: cosine similarity between "Plan a 3-day trip to Paris" and a
    genuinely-relevant stored Paris paragraph, using this real local model,
    is ~0.54 — the *previous* 0.70 default was tuned around OpenAI's
    embeddings (which tend to report higher absolute cosine similarity for
    related query/passage pairs) and silently failed real retrieval with the
    local provider. config.py's default was lowered to 0.45 in this same PR
    for exactly that reason.
    """
    from qdrant_client import AsyncQdrantClient

    from app.services.qdrant.service import QdrantService

    settings = Settings(
        LLM_PROVIDER="groq",
        LLM_API_KEY=GROQ_KEY,
        LLM_MODEL="openai/gpt-oss-120b",
        EMBEDDING_PROVIDER="local",
        EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L6-v2",
        EMBEDDING_DIMENSION=384,
        QDRANT_COLLECTION_NAME="e2e_groq_test_kb",
        QDRANT_SEARCH_SCORE_THRESHOLD=0.40,
        DATABASE_ENABLED=False,
    )

    client = AsyncQdrantClient(":memory:")
    qdrant_svc = QdrantService(client=client, settings=settings)
    await qdrant_svc.ensure_collection("e2e_groq_test_kb")

    from app.services.embeddings.service import EmbeddingService
    from app.services.store_service import StoreService
    from app.schemas.store import StoreRequest

    embedding_svc = EmbeddingService(settings=settings)
    store_svc = StoreService(qdrant_service=qdrant_svc, embedding_service=embedding_svc, settings=settings)
    await store_svc.process_store_request(
        StoreRequest(
            text=(
                "Paris is the capital of France. The Eiffel Tower, Louvre Museum, "
                "and Notre-Dame Cathedral are must-see attractions. The city is "
                "known for its cafes, art, and romantic atmosphere."
            ),
            title="Paris Travel Guide",
            destination="Paris",
            source_url="https://example.com/paris",
        ),
        request_id="req_groq_e2e_store",
    )

    llm_svc = LLMService(qdrant_service=qdrant_svc, embedding_service=embedding_svc, settings=settings)
    from app.schemas.generate import GenerateRequest

    response = await llm_svc.process_generate_request(
        GenerateRequest(prompt="Plan a 3-day trip to Paris"),
        request_id="req_groq_e2e_generate",
    )

    assert response.data_found is True
    assert response.status == "data_found"
    assert response.plan is not None
    assert isinstance(response.plan, TravelPlan)
    assert len(response.plan.destinations) > 0
