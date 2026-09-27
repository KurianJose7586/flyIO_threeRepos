"""Integration and fault-tolerance resilience tests for PostgreSQL event tracking."""

from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient

from app.db.session import DatabaseManager
from app.schemas.search import SearchResult, SearchResultItem
from app.services.tracking_service import TrackingService


@pytest.mark.asyncio
async def test_generate_endpoint_logs_tracking_events(async_client: AsyncClient):
    """Test POST /v1/api/generate dispatches lifecycle events to TrackingService."""
    mock_search = SearchResult(
        found=True,
        data_required=False,
        total_results=1,
        results=[
            SearchResultItem(
                id="doc-track-1",
                score=0.92,
                payload={"title": "Paris Guide"},
                text="Eiffel Tower details",
            )
        ],
        request_id="req_track_gen_01",
        message="Match found",
    )

    logged_events = []

    def mock_log_event(event_type, status="info", message=None, metadata=None, request_id=None):
        logged_events.append((event_type, status, request_id))

    with patch("app.services.qdrant.service.QdrantService.search", new_callable=AsyncMock) as mock_qdrant_search, \
         patch("app.services.tracking_service.TrackingService.log_event", side_effect=mock_log_event):
        
        mock_qdrant_search.return_value = mock_search

        payload = {
            "request_id": "req_track_gen_01",
            "prompt": "Create a 3-day Paris travel itinerary",
        }

        response = await async_client.post("/v1/api/generate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        event_types = [evt[0] for evt in logged_events]
        assert "llm_request_started" in event_types
        assert "qdrant_search_started" in event_types
        assert "qdrant_search_completed" in event_types
        assert "plan_generation_started" in event_types
        assert "plan_generation_completed" in event_types


@pytest.mark.asyncio
async def test_store_endpoint_logs_tracking_events(async_client: AsyncClient):
    """Test POST /v1/api/store dispatches lifecycle events to TrackingService."""
    logged_events = []

    def mock_log_event(event_type, status="info", message=None, metadata=None, request_id=None):
        logged_events.append((event_type, status, request_id))

    with patch("app.services.store_service.QdrantService.upsert_points", new_callable=AsyncMock) as mock_upsert, \
         patch("app.services.store_service.QdrantService.validate_collection", new_callable=AsyncMock) as mock_val, \
         patch("app.services.store_service.QdrantService.ensure_collection", new_callable=AsyncMock) as mock_ens, \
         patch("app.services.tracking_service.TrackingService.log_event", side_effect=mock_log_event):
        
        mock_upsert.return_value = True
        mock_val.return_value = True
        mock_ens.return_value = True

        payload = {
            "request_id": "req_track_store_01",
            "text": "FlyIO microservice architecture for AI LLM vector operations.",
            "title": "Architecture Spec",
        }

        response = await async_client.post("/v1/api/store", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        event_types = [evt[0] for evt in logged_events]
        assert "store_started" in event_types
        assert "embedding_generated" in event_types
        assert "qdrant_insert_started" in event_types
        assert "qdrant_insert_completed" in event_types


@pytest.mark.asyncio
async def test_fault_tolerance_db_outage_does_not_fail_api_response(async_client: AsyncClient):
    """CRITICAL Fault-Tolerance Resilience Test:

    Simulate complete PostgreSQL connection outage during API call.
    Assert that API still returns HTTP 200 OK with valid plan/storage response.
    """
    mock_search = SearchResult(
        found=True,
        data_required=False,
        total_results=1,
        results=[
            SearchResultItem(
                id="doc-resilience-1",
                score=0.95,
                payload={"title": "Tokyo Guide"},
                text="Tokyo sightseeing details",
            )
        ],
        request_id="req_resilience_999",
        message="Match found",
    )

    with patch("app.services.qdrant.service.QdrantService.search", new_callable=AsyncMock) as mock_qdrant_search, \
         patch("app.db.session.DatabaseManager.get_pool", new_callable=AsyncMock) as mock_db_pool:
        
        mock_qdrant_search.return_value = mock_search
        # Simulate complete PostgreSQL DB outage / connection error
        mock_db_pool.side_effect = Exception("FATAL: PostgreSQL database cluster unreachable")

        payload = {
            "request_id": "req_resilience_999",
            "prompt": "Create a 5-day Tokyo travel plan",
        }

        # Request must complete cleanly with HTTP 200 despite DB outage
        response = await async_client.post("/v1/api/generate", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["status"] == "data_found"
        assert data["plan"] is not None
        assert "Tokyo" in data["plan"]["title"]
