"""Tests for request ID generation and middleware propagation."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_request_id_generated_when_missing(async_client: AsyncClient):
    """Test that a request ID is automatically generated if not supplied."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    req_id = response.headers["X-Request-ID"]
    assert req_id.startswith("req_")

    data = response.json()
    assert data["request_id"] == req_id


@pytest.mark.asyncio
async def test_request_id_propagated_from_header(async_client: AsyncClient):
    """Test that an incoming X-Request-ID header is preserved and returned."""
    custom_id = "req_custom_99999"
    response = await async_client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id

    data = response.json()
    assert data["request_id"] == custom_id
