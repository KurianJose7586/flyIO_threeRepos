"""Tests for QdrantService operations: health, collection management, and vector search."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import Settings
from app.core.errors import QdrantUnavailableError
from app.services.qdrant.service import QdrantService


@pytest.fixture
def mock_qdrant_client():
    """Create a mock AsyncQdrantClient."""
    client = MagicMock()
    client.get_collections = AsyncMock()
    client.collection_exists = AsyncMock()
    client.create_collection = AsyncMock()
    client.query_points = AsyncMock()
    client.search = AsyncMock()
    return client


@pytest.fixture
def qdrant_service(mock_qdrant_client, test_settings: Settings):
    """Instantiate QdrantService with mocked client."""
    return QdrantService(client=mock_qdrant_client, settings=test_settings)


@pytest.mark.asyncio
async def test_qdrant_health_check_success(qdrant_service, mock_qdrant_client):
    """Test health check when collection exists."""
    col_mock = MagicMock()
    col_mock.name = "test_flyio_knowledge_base"
    mock_resp = MagicMock()
    mock_resp.collections = [col_mock]
    mock_qdrant_client.get_collections.return_value = mock_resp

    health = await qdrant_service.check_health()
    assert health.connected is True
    assert health.status == "connected"
    assert health.collection_exists is True


@pytest.mark.asyncio
async def test_qdrant_health_check_failure(qdrant_service, mock_qdrant_client):
    """Test health check when client throws network error."""
    mock_qdrant_client.get_collections.side_effect = Exception("Connection refused")

    health = await qdrant_service.check_health()
    assert health.connected is False
    assert health.status == "unavailable"
    assert health.collection_exists is False


@pytest.mark.asyncio
async def test_ensure_collection_already_exists(qdrant_service, mock_qdrant_client):
    """Test ensure_collection preserves existing collection without recreating."""
    mock_qdrant_client.collection_exists.return_value = True

    result = await qdrant_service.ensure_collection("test_col", 1536)
    assert result is True
    mock_qdrant_client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_collection_creates_if_missing(qdrant_service, mock_qdrant_client):
    """Test ensure_collection creates collection if not found."""
    mock_qdrant_client.collection_exists.return_value = False
    mock_qdrant_client.create_collection.return_value = True

    result = await qdrant_service.ensure_collection("test_col", 1536)
    assert result is True
    mock_qdrant_client.create_collection.assert_called_once()


@pytest.mark.asyncio
async def test_search_data_found(qdrant_service, mock_qdrant_client):
    """Test search returning vector items above threshold."""
    point = MagicMock()
    point.id = "doc-1"
    point.score = 0.89
    point.payload = {"text": "Architecture details for Fly.io", "source": "docs"}

    response_mock = MagicMock()
    response_mock.points = [point]
    mock_qdrant_client.query_points.return_value = response_mock

    result = await qdrant_service.search(query_vector=[0.1] * 1536)
    assert result.found is True
    assert result.data_required is False
    assert len(result.results) == 1
    assert result.results[0].id == "doc-1"
    assert result.results[0].score == 0.89
    assert result.results[0].text == "Architecture details for Fly.io"


@pytest.mark.asyncio
async def test_search_data_not_found(qdrant_service, mock_qdrant_client):
    """Test search returning empty points list."""
    response_mock = MagicMock()
    response_mock.points = []
    mock_qdrant_client.query_points.return_value = response_mock

    result = await qdrant_service.search(query_vector=[0.1] * 1536)
    assert result.found is False
    assert result.data_required is True
    assert len(result.results) == 0


@pytest.mark.asyncio
async def test_search_qdrant_failure(qdrant_service, mock_qdrant_client):
    """Test search error raises QdrantUnavailableError."""
    mock_qdrant_client.query_points.side_effect = Exception("Qdrant service timeout")

    with pytest.raises(QdrantUnavailableError):
        await qdrant_service.search(query_vector=[0.1] * 1536)
