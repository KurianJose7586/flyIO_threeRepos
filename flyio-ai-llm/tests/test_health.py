"""Tests for service, Qdrant, and PostgreSQL health endpoints."""

from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient

from app.schemas.health import PostgresHealthResponse, QdrantHealthResponse


@pytest.mark.asyncio
async def test_service_health_endpoint(async_client: AsyncClient):
    """Test basic service health check endpoint."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "flyio-ai-llm"
    assert "version" in data
    assert "timestamp" in data
    assert "request_id" in data


@pytest.mark.asyncio
async def test_v1_service_health_endpoint(async_client: AsyncClient):
    """Test versioned v1 service health check endpoint."""
    response = await async_client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_qdrant_health_connected(async_client: AsyncClient):
    """Test Qdrant health check when vector database is reachable."""
    mock_health = QdrantHealthResponse(
        status="connected",
        connected=True,
        qdrant_url="http://mock-qdrant:6333",
        collection_name="test_flyio_knowledge_base",
        collection_exists=True,
        vector_size=1536,
        request_id="req_test",
        timestamp="2026-08-15T00:00:00Z",
        details="Connected",
    )

    with patch("app.services.qdrant.service.QdrantService.check_health", new_callable=AsyncMock) as mock_check:
        mock_check.return_value = mock_health
        response = await async_client.get("/health/qdrant")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["connected"] is True
        assert data["collection_exists"] is True


@pytest.mark.asyncio
async def test_qdrant_health_unavailable(async_client: AsyncClient):
    """Test Qdrant health check when vector database is unreachable."""
    mock_health = QdrantHealthResponse(
        status="unavailable",
        connected=False,
        qdrant_url="http://mock-qdrant:6333",
        collection_name="test_flyio_knowledge_base",
        collection_exists=False,
        vector_size=1536,
        request_id="req_test",
        timestamp="2026-08-15T00:00:00Z",
        details="Failed to connect to Qdrant",
    )

    with patch("app.services.qdrant.service.QdrantService.check_health", new_callable=AsyncMock) as mock_check:
        mock_check.return_value = mock_health
        response = await async_client.get("/health/qdrant")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unavailable"
        assert data["connected"] is False


@pytest.mark.asyncio
async def test_postgres_health_connected(async_client: AsyncClient):
    """Test PostgreSQL health check when the database is reachable."""
    mock_health = PostgresHealthResponse(
        status="connected",
        connected=True,
        database_enabled=True,
        request_id="req_test",
        timestamp="2026-08-15T00:00:00Z",
        details="Connected. Event tracking is active.",
    )

    with patch("app.db.session.DatabaseManager.check_health", new_callable=AsyncMock) as mock_check:
        mock_check.return_value = mock_health
        response = await async_client.get("/health/postgres")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["connected"] is True


@pytest.mark.asyncio
async def test_postgres_health_unavailable_returns_503(async_client: AsyncClient):
    """Test PostgreSQL health check returns 503 when enabled but unreachable —
    this is the outage TrackingService's fail-safe suppression otherwise hides.
    """
    mock_health = PostgresHealthResponse(
        status="unavailable",
        connected=False,
        database_enabled=True,
        request_id="req_test",
        timestamp="2026-08-15T00:00:00Z",
        details="PostgreSQL is unreachable: connection refused",
    )

    with patch("app.db.session.DatabaseManager.check_health", new_callable=AsyncMock) as mock_check:
        mock_check.return_value = mock_health
        response = await async_client.get("/health/postgres")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unavailable"
        assert data["connected"] is False


@pytest.mark.asyncio
async def test_postgres_health_disabled_returns_200_not_503(async_client: AsyncClient):
    """A deliberately-disabled tracking DB (DATABASE_ENABLED=false) is a
    configuration choice, not an outage, and must not be reported as one.
    """
    mock_health = PostgresHealthResponse(
        status="disabled",
        connected=False,
        database_enabled=False,
        request_id="req_test",
        timestamp="2026-08-15T00:00:00Z",
        details="PostgreSQL event tracking is disabled or DATABASE_URL is not configured.",
    )

    with patch("app.db.session.DatabaseManager.check_health", new_callable=AsyncMock) as mock_check:
        mock_check.return_value = mock_health
        response = await async_client.get("/health/postgres")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disabled"


@pytest.mark.asyncio
async def test_postgres_health_real_check_against_unreachable_db():
    """Unmocked end-to-end check (not going through the HTTP layer, so it isn't
    fighting the async_client fixture's dependency override): with a closed
    loopback port as DATABASE_URL, DatabaseManager.check_health() must resolve
    quickly (not hang) and report 'unavailable' rather than a false 'connected'.
    """
    from app.core.config import Settings
    from app.db.session import DatabaseManager

    unreachable_settings = Settings(
        DATABASE_ENABLED=True,
        DATABASE_URL="postgresql://u:p@127.0.0.1:1/db",
    )
    result = await DatabaseManager.check_health(settings=unreachable_settings)
    assert result.status == "unavailable"
    assert result.connected is False
    assert result.database_enabled is True
