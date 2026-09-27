"""Tests for structured error handling and custom exceptions."""

from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient

from app.core.errors import QdrantUnavailableError


@pytest.mark.asyncio
async def test_qdrant_service_failure_error_mapping(async_client: AsyncClient):
    """Test that QdrantUnavailableError correctly maps to HTTP 503 with structured JSON."""
    with patch("app.services.qdrant.service.QdrantService.search", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = QdrantUnavailableError("Database unreachable")

        payload = {
            "request_id": "req_err_01",
            "prompt": "Trigger vector search error",
        }
        response = await async_client.post("/v1/api/generate", json=payload)
        assert response.status_code == 503
        data = response.json()
        assert data["success"] is False
        assert data["request_id"] == "req_err_01"
        assert data["error"]["code"] == "QDRANT_UNAVAILABLE"
        assert "Database unreachable" in data["error"]["message"]


@pytest.mark.asyncio
async def test_404_not_found_handling(async_client: AsyncClient):
    """Test 404 error returns structured ErrorResponse."""
    response = await async_client.get("/v1/non_existent_route")
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "NOT_FOUND"
