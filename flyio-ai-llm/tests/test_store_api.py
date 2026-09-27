"""Tests for LLM Store API endpoints, StoreService chunking/storage logic, and Qdrant integration."""

from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient

from app.core.errors import InvalidRequestError, QdrantUnavailableError
from app.schemas.store import StoreDocumentItem, StoreRequest
from app.services.embeddings.service import EmbeddingService
from app.services.store_service import StoreService, chunk_text, generate_deterministic_point_id


# --- 1. Unit Tests for chunk_text & Overlap Assertion ---

def test_chunk_text_small_text():
    """Text smaller than chunk_size should return single chunk."""
    text = "Short text under limit."
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_empty_text():
    """Empty or whitespace text should return empty list."""
    assert chunk_text("", chunk_size=100) == []
    assert chunk_text("   \n\t  ", chunk_size=100) == []


def test_chunk_text_overlap_characters_repeat():
    """Explicit test asserting chunk_overlap characters repeat between consecutive chunks."""
    text = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    chunk_size = 25
    overlap = 8

    chunks = chunk_text(text, chunk_size=chunk_size, chunk_overlap=overlap)
    assert len(chunks) > 1

    for idx in range(len(chunks) - 1):
        c1 = chunks[idx]
        c2 = chunks[idx + 1]
        # Assert that the trailing overlap characters of chunk 1 appear in chunk 2
        tail = c1[-overlap:]
        assert tail in c2, f"Overlap text '{tail}' from chunk {idx} not found in chunk {idx+1} '{c2}'"


# --- 2. Unit Tests for StoreService & Batch Embedding ---

@pytest.mark.asyncio
async def test_embed_batch_mock_provider():
    """Test EmbeddingService.embed_batch returns batched vectors.

    Builds explicit Settings rather than relying on ambient config: the mock
    provider's vector width follows EMBEDDING_DIMENSION, and Settings reads a
    developer's local .env by default — so hardcoding a dimension here made
    this test assert whatever happened to be in that .env (it failed with 384
    against a local file) instead of the behavior under test, which is that
    embed_batch returns one correctly-sized vector per input.
    """
    from app.core.config import Settings

    settings = Settings(_env_file=None, EMBEDDING_PROVIDER="mock", EMBEDDING_DIMENSION=768)
    svc = EmbeddingService(settings=settings)
    texts = ["Chunk one text", "Chunk two text", "Chunk three text"]
    vectors = await svc.embed_batch(texts)
    assert len(vectors) == 3
    assert all(len(v) == settings.EMBEDDING_DIMENSION for v in vectors)


@pytest.mark.asyncio
async def test_store_service_single_text_processing():
    """Test StoreService processes top-level text input into points and invokes Qdrant upsert."""
    mock_qdrant_svc = AsyncMock()
    mock_qdrant_svc.upsert_points.return_value = True

    service = StoreService(qdrant_service=mock_qdrant_svc)

    req = StoreRequest(
        text="Fly.io enables running microVMs near your users globally.",
        title="Fly.io Intro",
        source_url="https://fly.io/docs",
        metadata={"category": "tech"},
    )

    resp = await service.process_store_request(req, request_id="req_test_001")

    assert resp.success is True
    assert resp.request_id == "req_test_001"
    assert resp.status == "stored"
    assert resp.stored_count == 1
    assert len(resp.document_ids) == 1
    mock_qdrant_svc.upsert_points.assert_called_once()


@pytest.mark.asyncio
async def test_store_service_idempotent_point_id_generation():
    """Test that sending identical document content generates identical deterministic point IDs."""
    id1 = generate_deterministic_point_id("doc_100", 1, "Sample chunk text")
    id2 = generate_deterministic_point_id("doc_100", 1, "Sample chunk text")
    assert id1 == id2, "Point IDs for identical document/chunk must be strictly deterministic for idempotency"


# --- 3. Integration Tests for /v1/api/store Endpoint ---

@pytest.mark.asyncio
async def test_store_endpoint_single_text_success(async_client: AsyncClient):
    """Test POST /v1/api/store with top-level text string succeeds."""
    with patch("app.services.store_service.QdrantService.upsert_points", new_callable=AsyncMock) as mock_upsert, \
         patch("app.services.store_service.QdrantService.validate_collection", new_callable=AsyncMock) as mock_val, \
         patch("app.services.store_service.QdrantService.ensure_collection", new_callable=AsyncMock) as mock_ens:
        mock_upsert.return_value = True
        mock_val.return_value = True
        mock_ens.return_value = True

        payload = {
            "request_id": "req_api_store_1",
            "text": "FlyIO microservice architecture separates API frontend, scraper, and LLM vector engine.",
            "title": "Architecture Overview",
            "source_url": "https://fly.io/docs/architecture",
            "metadata": {"author": "FlyIO Team"},
        }

        response = await async_client.post("/v1/api/store", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["request_id"] == "req_api_store_1"
        assert data["status"] == "stored"
        assert data["stored_count"] >= 1
        assert len(data["document_ids"]) >= 1
        assert data["points"][0]["chunk_index"] == 1
        assert data["metadata"]["author"] == "FlyIO Team"


@pytest.mark.asyncio
async def test_store_endpoint_alias_route(async_client: AsyncClient):
    """Test POST /v1/store alias route returns expected stored result."""
    with patch("app.services.store_service.QdrantService.upsert_points", new_callable=AsyncMock) as mock_upsert, \
         patch("app.services.store_service.QdrantService.validate_collection", new_callable=AsyncMock) as mock_val, \
         patch("app.services.store_service.QdrantService.ensure_collection", new_callable=AsyncMock) as mock_ens:
        mock_upsert.return_value = True
        mock_val.return_value = True
        mock_ens.return_value = True

        payload = {
            "content": "Alias route test content for backward compatibility routing.",
            "title": "Alias Test",
        }

        response = await async_client.post("/v1/store", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["status"] == "stored"


@pytest.mark.asyncio
async def test_store_endpoint_structured_documents_success(async_client: AsyncClient):
    """Test POST /v1/api/store with pre-structured documents list."""
    with patch("app.services.store_service.QdrantService.upsert_points", new_callable=AsyncMock) as mock_upsert, \
         patch("app.services.store_service.QdrantService.validate_collection", new_callable=AsyncMock) as mock_val, \
         patch("app.services.store_service.QdrantService.ensure_collection", new_callable=AsyncMock) as mock_ens:
        mock_upsert.return_value = True
        mock_val.return_value = True
        mock_ens.return_value = True

        payload = {
            "request_id": "req_api_store_2",
            "documents": [
                {
                    "id": "kb_doc_101",
                    "text": "FlyIO microservice vector storage guidelines.",
                    "title": "KB Guide 101",
                    "destination": "Paris",
                    "category": "guide",
                    "source_url": "https://kb.fly.io/101",
                    "metadata": {"tag": "guide"},
                },
                {
                    "id": "kb_doc_102",
                    "content": "FastAPI and Qdrant integration specs.",
                    "title": "KB Guide 102",
                    "category": "specs",
                    "metadata": {"tag": "specs"},
                },
            ],
            "collection_name": "custom_flyio_kb",
        }

        response = await async_client.post("/v1/api/store", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["stored_count"] == 2
        assert data["collection_name"] == "custom_flyio_kb"


@pytest.mark.asyncio
async def test_store_endpoint_validation_error_empty_payload(async_client: AsyncClient):
    """Test POST /v1/api/store returns HTTP 422 when neither documents nor text is provided."""
    payload = {
        "metadata": {"source": "admin"},
    }
    response = await async_client.post("/v1/api/store", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_store_endpoint_collection_validation_failure(async_client: AsyncClient):
    """Test POST /v1/api/store returns HTTP 400 when collection validation fails (missing/mismatched)."""
    with patch("app.services.store_service.QdrantService.validate_collection", new_callable=AsyncMock) as mock_val:
        mock_val.side_effect = InvalidRequestError(
            message="Collection 'non_existent_kb' does not exist in vector database.",
            details={"collection_name": "non_existent_kb"},
        )

        payload = {
            "text": "Valid document text to test collection validation failure.",
            "collection_name": "non_existent_kb",
        }

        response = await async_client.post("/v1/api/store", json=payload)
        assert response.status_code == 400
        data = response.json()

        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_REQUEST"
        assert "non_existent_kb" in data["error"]["message"]


@pytest.mark.asyncio
async def test_store_endpoint_qdrant_failure(async_client: AsyncClient):
    """Test POST /v1/api/store returns HTTP 503 when Qdrant database write fails."""
    with patch("app.services.store_service.QdrantService.validate_collection", new_callable=AsyncMock) as mock_val, \
         patch("app.services.store_service.QdrantService.ensure_collection", new_callable=AsyncMock) as mock_ens, \
         patch("app.services.store_service.QdrantService.upsert_points", new_callable=AsyncMock) as mock_upsert:
        mock_val.return_value = True
        mock_ens.return_value = True
        mock_upsert.side_effect = QdrantUnavailableError(
            message="Vector database storage write failed",
            details={"error": "Connection refused"},
        )

        payload = {
            "text": "Valid document text to trigger Qdrant failure handling.",
        }

        response = await async_client.post("/v1/api/store", json=payload)
        assert response.status_code == 503
        data = response.json()

        assert data["success"] is False
        assert data["error"]["code"] == "QDRANT_UNAVAILABLE"
        assert "Vector database storage write failed" in data["error"]["message"]




@pytest.mark.asyncio
async def test_store_duplicate_request_idempotency_live_qdrant(test_settings):
    """Live integration test against in-memory Qdrant instance asserting duplicate store requests overwrite points without duplicating."""
    from qdrant_client import AsyncQdrantClient
    from app.services.qdrant.service import QdrantService

    client = AsyncQdrantClient(":memory:")
    qdrant_svc = QdrantService(client=client, settings=test_settings)
    await qdrant_svc.ensure_collection(test_settings.QDRANT_COLLECTION_NAME)

    store_svc = StoreService(qdrant_service=qdrant_svc, settings=test_settings)

    # 1. First store request
    req1 = StoreRequest(
        text="Original document content version 1.",
        title="Doc V1",
        source_url="https://fly.io/docs/v1",
        metadata={"version": 1},
    )
    resp1 = await store_svc.process_store_request(req1, request_id="req_dup_1")
    assert resp1.success is True
    assert resp1.stored_count == 1

    # Verify collection count = 1 and initial payload
    col_info1 = await client.get_collection(test_settings.QDRANT_COLLECTION_NAME)
    assert col_info1.points_count == 1

    point_id = resp1.document_ids[0]
    retrieved_1 = await client.retrieve(test_settings.QDRANT_COLLECTION_NAME, ids=[point_id])
    assert retrieved_1[0].payload["title"] == "Doc V1"
    assert retrieved_1[0].payload["metadata"]["version"] == 1

    # 2. Second duplicate store request (same text & source_url, updated title and metadata)
    req2 = StoreRequest(
        text="Original document content version 1.",
        title="Doc V2 Updated",
        source_url="https://fly.io/docs/v1",
        metadata={"version": 2},
    )
    resp2 = await store_svc.process_store_request(req2, request_id="req_dup_2")

    # Assertions:
    # 1. stored_count is identical both times
    assert resp2.stored_count == resp1.stored_count == 1

    # 2. No duplicate points exist in collection (point count before vs after second request is unchanged)
    col_info2 = await client.get_collection(test_settings.QDRANT_COLLECTION_NAME)
    assert col_info2.points_count == col_info1.points_count == 1

    # 3. Payload content is correctly overwritten, not appended
    retrieved_2 = await client.retrieve(test_settings.QDRANT_COLLECTION_NAME, ids=[point_id])
    assert retrieved_2[0].payload["title"] == "Doc V2 Updated"
    assert retrieved_2[0].payload["metadata"]["version"] == 2

