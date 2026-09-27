"""Tests for LLM service, embedding abstraction, provider layers, and TravelPlan generation."""

import json
from unittest.mock import AsyncMock
import pytest

from app.core.config import Settings
from app.schemas.generate import GenerateRequest, TravelPlan
from app.schemas.search import SearchResult, SearchResultItem
from app.services.embeddings.mock_provider import MockEmbeddingProvider
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.openai_provider import OpenAILLMProvider
from app.services.llm.service import LLMService


@pytest.mark.asyncio
async def test_mock_embedding_provider():
    """Verify mock embedding provider generates unit normalized vector of expected dimension."""
    provider = MockEmbeddingProvider(dimension=1536)
    vector = await provider.embed_text("Test query string")
    assert len(vector) == 1536
    norm = sum(x * x for x in vector)
    assert pytest.approx(norm, 0.01) == 1.0


@pytest.mark.asyncio
async def test_mock_llm_provider():
    """Verify mock LLM provider returns synthetic plan JSON."""
    provider = MockLLMProvider()
    response = await provider.generate(prompt="Build Paris trip plan", context="Paris guide context")
    plan_dict = json.loads(response)
    assert "Paris" in plan_dict["title"]
    assert len(plan_dict["destinations"]) > 0


def test_llm_service_resolves_groq_provider_via_openai_compatible_client():
    """LLM_PROVIDER='groq' must resolve to OpenAILLMProvider pointed at Groq's
    base_url — no separate provider class exists for it (Groq is OpenAI-API-
    compatible), so this is what actually determines whether a 'groq' typo
    or unwired config value would silently fall through to MockLLMProvider
    (the `else` branch) instead of erroring or hitting Groq. No network call.
    """
    settings = Settings(LLM_PROVIDER="groq", LLM_API_KEY="gsk_test_key", LLM_MODEL="openai/gpt-oss-120b")
    service = LLMService(settings=settings)
    assert isinstance(service.provider, OpenAILLMProvider)
    assert service.provider.base_url == "https://api.groq.com/openai/v1"
    assert service.provider.model == "openai/gpt-oss-120b"
    assert service.provider.api_key == "gsk_test_key"


@pytest.mark.asyncio
async def test_llm_service_data_found_workflow(test_settings: Settings):
    """Verify LLMService returns 'data_found' with TravelPlan when Qdrant contains matching knowledge."""
    mock_qdrant = AsyncMock()
    mock_qdrant.search.return_value = SearchResult(
        found=True,
        data_required=False,
        total_results=1,
        results=[
            SearchResultItem(
                id="doc-123",
                score=0.92,
                payload={"title": "Paris Travel Guide", "text": "Eiffel Tower and Louvre recommendations"},
                text="Eiffel Tower and Louvre recommendations",
            )
        ],
        request_id="req_test_01",
        message="Found 1 match",
    )

    mock_embeddings = AsyncMock()
    mock_embeddings.embed_query.return_value = [0.05] * 1536

    llm_service = LLMService(
        qdrant_service=mock_qdrant,
        embedding_service=mock_embeddings,
        settings=test_settings,
    )

    request = GenerateRequest(
        request_id="req_test_01",
        prompt="Create a 3-day Paris itinerary with top sights",
        metadata={"priority": "high"},
    )

    response = await llm_service.process_generate_request(request, request_id="req_test_01")
    assert response.success is True
    assert response.status == "data_found"
    assert response.data_found is True
    assert response.data_required is False
    assert len(response.results) == 1
    assert response.results[0].id == "doc-123"
    assert response.plan is not None
    assert isinstance(response.plan, TravelPlan)
    assert len(response.plan.destinations) > 0


@pytest.mark.asyncio
async def test_llm_service_retry_success_workflow(test_settings: Settings):
    """Verify LLMService retries once when first attempt returns invalid JSON and succeeds on retry."""
    mock_qdrant = AsyncMock()
    mock_qdrant.search.return_value = SearchResult(
        found=True,
        data_required=False,
        total_results=1,
        results=[
            SearchResultItem(
                id="doc-123",
                score=0.90,
                payload={"title": "Tokyo Travel Guide"},
                text="Tokyo spots",
            )
        ],
        request_id="req_retry_01",
        message="Found 1 match",
    )

    mock_embeddings = AsyncMock()
    mock_embeddings.embed_query.return_value = [0.05] * 1536

    # Wrap provider generate in AsyncMock spy
    mock_llm_provider = MockLLMProvider(fail_first_n_times=1)
    original_generate = mock_llm_provider.generate
    spy_generate = AsyncMock(side_effect=original_generate)
    mock_llm_provider.generate = spy_generate

    llm_service = LLMService(
        qdrant_service=mock_qdrant,
        embedding_service=mock_embeddings,
        provider=mock_llm_provider,
        settings=test_settings,
    )

    request = GenerateRequest(
        request_id="req_retry_01",
        prompt="Plan a trip to Tokyo",
    )

    response = await llm_service.process_generate_request(request, request_id="req_retry_01")
    assert response.success is True
    assert response.status == "data_found"
    assert response.data_found is True
    assert response.plan is not None

    # Assert 2 LLM calls were made and the 2nd call used build_retry_system_prompt()
    assert spy_generate.call_count == 2
    retry_call_system_prompt = spy_generate.call_args_list[1].kwargs.get("system_prompt")
    assert "Your previous response was not valid JSON" in retry_call_system_prompt


@pytest.mark.asyncio
async def test_llm_service_retry_and_fallback_generation_failed(test_settings: Settings):
    """Verify LLMService returns 'generation_failed' fallback when both initial attempt and retry fail JSON validation."""
    mock_qdrant = AsyncMock()
    mock_qdrant.search.return_value = SearchResult(
        found=True,
        data_required=False,
        total_results=1,
        results=[
            SearchResultItem(
                id="doc-456",
                score=0.88,
                payload={"title": "Rome Guide"},
                text="Rome attractions",
            )
        ],
        request_id="req_fail_01",
        message="Found 1 match",
    )

    mock_embeddings = AsyncMock()
    mock_embeddings.embed_query.return_value = [0.05] * 1536

    # Mock provider configured to always fail (always return invalid JSON)
    mock_llm_provider = MockLLMProvider(fail_first_n_times=999)

    llm_service = LLMService(
        qdrant_service=mock_qdrant,
        embedding_service=mock_embeddings,
        provider=mock_llm_provider,
        settings=test_settings,
    )

    request = GenerateRequest(
        request_id="req_fail_01",
        prompt="Plan a trip to Rome INVALID_JSON_TEST",
    )

    response = await llm_service.process_generate_request(request, request_id="req_fail_01")
    assert response.success is True
    assert response.status == "generation_failed"
    assert response.data_found is True
    assert response.data_required is False
    assert response.plan is None
    assert response.message == "Plan generation failed to produce valid structured output."
    assert len(response.results) == 1


@pytest.mark.asyncio
async def test_llm_service_data_required_workflow(test_settings: Settings):
    """Verify LLMService returns 'data_required' when Qdrant has no matching context."""
    mock_qdrant = AsyncMock()
    mock_qdrant.search.return_value = SearchResult(
        found=False,
        data_required=True,
        total_results=0,
        results=[],
        request_id="req_test_02",
        message="No data found",
    )

    mock_embeddings = AsyncMock()
    mock_embeddings.embed_query.return_value = [0.05] * 1536

    llm_service = LLMService(
        qdrant_service=mock_qdrant,
        embedding_service=mock_embeddings,
        settings=test_settings,
    )

    request = GenerateRequest(
        request_id="req_test_02",
        prompt="Unknown destination query",
    )

    response = await llm_service.process_generate_request(request, request_id="req_test_02")
    assert response.success is True
    assert response.status == "data_required"
    assert response.data_found is False
    assert response.data_required is True
    assert len(response.results) == 0
    assert response.plan is None


# --- Server-side JSON-mode rejection must be retried, not escape as an error ---

def test_provider_classifies_json_validate_failed_as_parse_error():
    """Groq rejects the model's malformed JSON at the API boundary (HTTP 400
    json_validate_failed) rather than handing back the bad text. That is a
    content failure, not a transport failure, and must surface as a parse-type
    error so LLMService's corrective retry applies — otherwise the same model
    mistake is retried or not purely depending on which provider detected it.
    """
    import httpx
    from app.services.llm.openai_provider import OpenAILLMProvider

    rejected = httpx.Response(
        status_code=400,
        json={"error": {"code": "json_validate_failed", "message": "Failed to generate JSON.",
                        "failed_generation": '{"title": bad}'}},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    assert OpenAILLMProvider._is_json_validation_failure(rejected) is True

    # A genuine transport/config error must NOT be reclassified as retryable.
    unauthorized = httpx.Response(
        status_code=401,
        json={"error": {"code": "invalid_api_key", "message": "Invalid API Key"}},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    assert OpenAILLMProvider._is_json_validation_failure(unauthorized) is False


@pytest.mark.asyncio
async def test_generation_retried_when_provider_rejects_first_json(test_settings: Settings):
    """End-to-end through LLMService: a provider that rejects its own JSON on
    the FIRST call must still produce a plan via the corrective retry.

    Regression guard for two coupled bugs: the provider raised a non-retryable
    error for a retryable condition, and the first generate() sat outside the
    try block, so that failure escaped LLMService entirely instead of retrying.
    """
    from app.services.llm.mock_provider import MockLLMProvider

    mock_qdrant = AsyncMock()
    mock_qdrant.search.return_value = SearchResult(
        found=True, data_required=False, total_results=1,
        results=[SearchResultItem(id="d1", score=0.9, payload={"title": "Nara"}, text="Nara has deer.")],
        request_id="req_json_retry", message="Found",
    )
    mock_embeddings = AsyncMock()
    mock_embeddings.embed_query.return_value = [0.05] * 768

    good = MockLLMProvider()
    calls = {"n": 0}

    class RejectsFirstJSON:
        async def generate(self, prompt, context=None, system_prompt=None, metadata=None):
            calls["n"] += 1
            if calls["n"] == 1:
                # Exactly what OpenAILLMProvider now raises for HTTP 400 json_validate_failed.
                raise ValueError("LLM provider returned invalid JSON (HTTP 400): json_validate_failed")
            return await good.generate(prompt, context, system_prompt, metadata)

    service = LLMService(
        qdrant_service=mock_qdrant, embedding_service=mock_embeddings,
        provider=RejectsFirstJSON(), settings=test_settings,
    )
    response = await service.process_generate_request(
        GenerateRequest(prompt="Plan a day in Nara"), request_id="req_json_retry"
    )

    assert calls["n"] == 2, "the corrective retry never fired"
    assert response.status == "data_found"
    assert response.plan is not None
