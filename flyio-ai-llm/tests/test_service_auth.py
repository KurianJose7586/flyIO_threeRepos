"""Tests for ServiceAuthMiddleware (app/middlewares/service_auth.py).

Note on response shape: a 401 from this middleware is a raw
{"detail": "..."} body, not this service's usual ErrorResponse envelope
({success, request_id, error: {code, message, details}} — see
app/schemas/error.py). That's deliberate, not an oversight: this mirrors
flyio-scraper-service's ServiceAuthMiddleware response shape exactly (per
explicit direction to match the scraper's auth convention), at the cost of
being structurally different from every other error response this service
returns. Admin's client code should treat a 401 from either service the
same way regardless.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app
from app.schemas.health import PostgresHealthResponse, QdrantHealthResponse
from tests.conftest import TEST_SERVICE_API_KEY


@pytest.mark.asyncio
async def test_missing_api_key_returns_401(async_client: AsyncClient):
    """A guarded /v1/* route with no X-Service-API-Key header must be rejected."""
    response = await async_client.post(
        "/v1/api/generate",
        json={"prompt": "Plan a trip"},
        headers={"X-Service-API-Key": ""},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing X-Service-API-Key header."}


@pytest.mark.asyncio
async def test_wrong_api_key_returns_401(async_client: AsyncClient):
    """A guarded /v1/* route with an incorrect key must be rejected."""
    response = await async_client.post(
        "/v1/api/generate",
        json={"prompt": "Plan a trip"},
        headers={"X-Service-API-Key": "wrong-key-entirely"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid service API key."}


@pytest.mark.asyncio
async def test_correct_api_key_is_not_rejected_by_auth(async_client: AsyncClient):
    """The shared async_client fixture already sends the correct key on every
    request (see conftest.py) — this is the control case proving that a
    valid key genuinely passes the middleware, not just that a wrong one
    fails.

    QdrantService.search is mocked purely so this test doesn't pay for a
    real network attempt against test_settings' fake QDRANT_URL hostname —
    matches the existing convention in test_generate_api.py. The actual
    search/plan-generation outcome isn't this test's concern (that's what
    test_generate_api.py is for) — only that auth didn't block the request.
    """
    from app.schemas.search import SearchResult

    with patch("app.services.qdrant.service.QdrantService.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = SearchResult(
            found=False, data_required=True, total_results=0, results=[],
            request_id="req_test", message="No data found",
        )
        response = await async_client.post("/v1/api/generate", json={"prompt": "Plan a trip"})
    assert response.status_code != 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/health/qdrant",
        "/health/postgres",
        "/v1/health",
        "/v1/health/qdrant",
        "/v1/health/postgres",
    ],
)
async def test_health_paths_are_public_with_no_key(async_client: AsyncClient, path: str):
    """Health checks (bare and /v1-prefixed — see main.py's dual registration)
    must stay reachable by load balancers/orchestrators that don't carry a
    service key, regardless of SERVICE_API_KEY being configured.

    /health/qdrant and /health/postgres do a real backend connectivity check
    by design (see Phase 1) — mocked here since this test is only about
    whether *auth* lets the request through, not backend connectivity
    (already covered for real by test_health.py and
    test_embeddings_local_provider.py's Postgres/Qdrant tests). Doing a real
    check here against test_settings' fake QDRANT_URL hostname costs several
    seconds of DNS resolution per call for no signal this test needs.
    """
    with patch(
        "app.services.qdrant.service.QdrantService.check_health", new_callable=AsyncMock
    ) as mock_qdrant, patch(
        "app.db.session.DatabaseManager.check_health", new_callable=AsyncMock
    ) as mock_pg:
        mock_qdrant.return_value = QdrantHealthResponse(
            status="connected", connected=True, qdrant_url="http://mock-qdrant:6333",
            collection_name="test_kb", collection_exists=True, timestamp="2026-08-15T00:00:00Z",
        )
        mock_pg.return_value = PostgresHealthResponse(
            status="connected", connected=True, database_enabled=True, timestamp="2026-08-15T00:00:00Z",
        )
        response = await async_client.get(path, headers={"X-Service-API-Key": ""})
    assert response.status_code != 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
async def test_docs_paths_are_public_with_no_key(async_client: AsyncClient, path: str):
    """Anyone should be able to browse the API docs without a service key."""
    response = await async_client.get(path, headers={"X-Service-API-Key": ""})
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_unset_service_api_key_rejects_every_key(monkeypatch: pytest.MonkeyPatch):
    """If SERVICE_API_KEY is unset/empty, a guarded request must be rejected
    no matter what key is sent — including a plausible-looking non-empty one
    (not just an empty one, which `if not provided_key: return 401` already
    catches on its own regardless of this check — see service_auth.py's
    module docstring on why that distinction matters for what this test is
    actually proving). This is what exercises the explicit
    `not settings.SERVICE_API_KEY` branch specifically, rather than a case
    hmac.compare_digest alone would already reject.
    """
    monkeypatch.setenv("SERVICE_API_KEY", "")
    get_settings.cache_clear()
    try:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/api/generate",
                json={"prompt": "Plan a trip"},
                headers={"X-Service-API-Key": "some-plausible-looking-key"},
            )
            assert response.status_code == 401
            assert response.json() == {"detail": "Invalid service API key."}
    finally:
        get_settings.cache_clear()


def test_conftest_service_api_key_is_non_empty():
    """Sanity check on the test fixture itself: if this were ever empty, every
    other test in this file (and every /v1/* test in the whole suite, via
    async_client) would be silently exercising the fail-closed path instead
    of genuine auth success — the opposite of what most of them intend to test.
    """
    assert TEST_SERVICE_API_KEY
