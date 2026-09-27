"""Tests for POST /v1/api/store batch limits — Phase 4.3.

Before this, a single request with no cap on document count or combined
text size could exhaust memory building the embedding batch, or blow an
API-metered embedding provider's per-call cost/payload limit in one shot.
See StoreService._enforce_batch_limits and Settings.STORE_MAX_DOCUMENTS /
STORE_MAX_TOTAL_CHARS.
"""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.core.errors import InvalidRequestError
from app.schemas.store import StoreDocumentItem, StoreRequest
from app.services.store_service import StoreService


def _tiny_limits_settings(**overrides) -> Settings:
    """Small limits so tests don't need to build huge payloads to exceed them."""
    return Settings(STORE_MAX_DOCUMENTS=3, STORE_MAX_TOTAL_CHARS=100, **overrides)


@pytest.mark.asyncio
async def test_document_count_within_limit_is_accepted():
    settings = _tiny_limits_settings()
    mock_qdrant_svc = AsyncMock()
    mock_qdrant_svc.upsert_points.return_value = True
    service = StoreService(qdrant_service=mock_qdrant_svc, settings=settings)

    req = StoreRequest(
        documents=[StoreDocumentItem(text="short") for _ in range(3)],  # == limit, not over
    )
    resp = await service.process_store_request(req, request_id="req_limit_ok")
    assert resp.success is True
    assert resp.stored_count == 3


@pytest.mark.asyncio
async def test_document_count_over_limit_is_rejected():
    settings = _tiny_limits_settings()
    mock_qdrant_svc = AsyncMock()
    service = StoreService(qdrant_service=mock_qdrant_svc, settings=settings)

    req = StoreRequest(documents=[StoreDocumentItem(text="short") for _ in range(4)])  # > limit of 3

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.process_store_request(req, request_id="req_limit_over")

    assert exc_info.value.status_code == 400
    assert "4 document(s)" in exc_info.value.message
    assert "limit of 3" in exc_info.value.message
    # Rejected before any I/O — Qdrant must never be touched.
    mock_qdrant_svc.ensure_collection.assert_not_called()
    mock_qdrant_svc.upsert_points.assert_not_called()


@pytest.mark.asyncio
async def test_total_chars_over_limit_is_rejected_even_with_one_document():
    """A single oversized document must be caught too, not just many small ones."""
    settings = _tiny_limits_settings()  # STORE_MAX_TOTAL_CHARS=100
    mock_qdrant_svc = AsyncMock()
    service = StoreService(qdrant_service=mock_qdrant_svc, settings=settings)

    req = StoreRequest(documents=[StoreDocumentItem(text="x" * 200)])  # one doc, way over char limit

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.process_store_request(req, request_id="req_limit_chars")

    assert exc_info.value.status_code == 400
    assert "200 total characters" in exc_info.value.message
    mock_qdrant_svc.ensure_collection.assert_not_called()


@pytest.mark.asyncio
async def test_top_level_text_convenience_field_counts_toward_limits():
    """The top-level text/content convenience path becomes one implicit
    document in process_store_request — the limit check must count it too,
    not just len(request.documents), or it would be a trivial bypass.
    """
    settings = _tiny_limits_settings()
    mock_qdrant_svc = AsyncMock()
    service = StoreService(qdrant_service=mock_qdrant_svc, settings=settings)

    req = StoreRequest(text="x" * 200)  # no `documents` at all, still over char limit

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.process_store_request(req, request_id="req_limit_top_level")

    assert "200 total characters" in exc_info.value.message


@pytest.mark.asyncio
async def test_store_endpoint_batch_limit_returns_400():
    """End-to-end through the real HTTP layer: exceeding the limit must
    surface as a 400 in the standard ErrorResponse envelope, not a 500 or
    an unhandled exception.

    Deliberately does NOT use the shared async_client fixture: that fixture
    builds its own FastAPI app instance and overrides get_settings on it —
    there is no way to reach into that instance's dependency_overrides from
    a test, and app.main's module-level `app` singleton is a *different*
    instance, so overriding it here would silently do nothing. Builds a
    fresh app the same way async_client's fixture does, with a tiny
    STORE_MAX_DOCUMENTS so this doesn't need a huge literal payload to
    exceed the real default of 100.
    """
    from httpx import ASGITransport
    from app.core.config import get_settings
    from app.main import create_app
    from tests.conftest import TEST_SERVICE_API_KEY

    tiny_settings = Settings(
        LLM_PROVIDER="mock", EMBEDDING_PROVIDER="mock",
        QDRANT_URL="http://mock-qdrant:6333", QDRANT_COLLECTION_NAME="test_flyio_knowledge_base",
        DATABASE_URL="postgresql://test:test@127.0.0.1:1/test_flyio_ai",
        STORE_MAX_DOCUMENTS=2,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: tiny_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"X-Service-API-Key": TEST_SERVICE_API_KEY},
    ) as client:
        response = await client.post(
            "/v1/api/store",
            json={"documents": [{"text": "one"}, {"text": "two"}, {"text": "three"}]},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_REQUEST"
    assert "3 document(s)" in data["error"]["message"]


def test_default_batch_limits_are_reasonable():
    """Sanity check the real defaults (not the tiny test overrides above) are
    actually in place, so this feature isn't accidentally a no-op in
    production because Settings() itself doesn't carry the new fields.
    """
    settings = Settings()
    assert settings.STORE_MAX_DOCUMENTS == 100
    assert settings.STORE_MAX_TOTAL_CHARS == 500_000
