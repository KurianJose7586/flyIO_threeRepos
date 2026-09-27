"""Tests for /v1/api/generate endpoint."""

from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient

from app.schemas.search import SearchResult, SearchResultItem
from app.services.llm.mock_provider import MockLLMProvider


@pytest.mark.asyncio
async def test_generate_endpoint_valid_request_data_found(async_client: AsyncClient):
    """Test POST /v1/api/generate when relevant documents are found in vector DB and plan is generated."""
    mock_search = SearchResult(
        found=True,
        data_required=False,
        total_results=1,
        results=[
            SearchResultItem(
                id="point-1",
                score=0.91,
                payload={"title": "Paris Travel Guide"},
                text="Eiffel Tower visiting details",
            )
        ],
        request_id="req_custom_101",
        message="Found 1 match",
    )

    with patch("app.services.qdrant.service.QdrantService.search", new_callable=AsyncMock) as mock_qdrant_search:
        mock_qdrant_search.return_value = mock_search

        payload = {
            "request_id": "req_custom_101",
            "prompt": "Create a 3-day Paris travel plan",
            "metadata": {"user": "admin", "env": "prod"},
        }
        response = await async_client.post("/v1/api/generate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["request_id"] == "req_custom_101"
        assert data["status"] == "data_found"
        assert data["data_found"] is True
        assert data["data_required"] is False
        assert len(data["results"]) == 1
        assert data["plan"] is not None
        assert "Paris" in data["plan"]["title"]
        assert len(data["plan"]["destinations"]) > 0
        assert data["metadata"]["user"] == "admin"


@pytest.mark.asyncio
async def test_generate_endpoint_generation_failed_fallback(async_client: AsyncClient):
    """Test POST /v1/api/generate returns HTTP 200 generation_failed status when LLM parse fails."""
    mock_search = SearchResult(
        found=True,
        data_required=False,
        total_results=1,
        results=[
            SearchResultItem(
                id="point-99",
                score=0.89,
                payload={"title": "Guide"},
                text="Text snippet",
            )
        ],
        request_id="req_fail_api_01",
        message="Found 1 match",
    )

    with patch("app.services.qdrant.service.QdrantService.search", new_callable=AsyncMock) as mock_qdrant_search, \
         patch("app.services.llm.service.LLMService._resolve_provider") as mock_resolve_provider:
        
        mock_qdrant_search.return_value = mock_search
        mock_resolve_provider.return_value = MockLLMProvider(fail_first_n_times=999)

        payload = {
            "request_id": "req_fail_api_01",
            "prompt": "Plan trip INVALID_JSON_TEST",
        }
        response = await async_client.post("/v1/api/generate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["status"] == "generation_failed"
        assert data["data_found"] is True
        assert data["data_required"] is False
        assert data["plan"] is None
        assert data["message"] == "Plan generation failed to produce valid structured output."


@pytest.mark.asyncio
async def test_generate_endpoint_data_required(async_client: AsyncClient):
    """Test POST /v1/api/generate when no documents match, triggering data_required."""
    mock_search = SearchResult(
        found=False,
        data_required=True,
        total_results=0,
        results=[],
        request_id="req_custom_102",
        message="No matches found",
    )

    with patch("app.services.qdrant.service.QdrantService.search", new_callable=AsyncMock) as mock_qdrant_search:
        mock_qdrant_search.return_value = mock_search

        payload = {
            "request_id": "req_custom_102",
            "prompt": "Obscure unpublished API details",
        }
        response = await async_client.post("/v1/api/generate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["status"] == "data_required"
        assert data["data_found"] is False
        assert data["data_required"] is True
        assert len(data["results"]) == 0
        assert data["plan"] is None


@pytest.mark.asyncio
async def test_generate_endpoint_missing_prompt(async_client: AsyncClient):
    """Test validation error when prompt is missing."""
    payload = {"request_id": "req_invalid_01"}
    response = await async_client.post("/v1/api/generate", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_generate_endpoint_empty_prompt(async_client: AsyncClient):
    """Test validation error when prompt is whitespace/empty."""
    payload = {"prompt": "   "}
    response = await async_client.post("/v1/api/generate", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_ERROR"
