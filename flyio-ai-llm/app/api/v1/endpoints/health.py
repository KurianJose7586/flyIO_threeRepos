"""Health check endpoints for flyio-ai-llm service and Qdrant integration."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.context import get_request_id
from app.db.session import DatabaseManager
from app.schemas.health import HealthResponse, PostgresHealthResponse, QdrantHealthResponse
from app.services.qdrant.service import QdrantService

router = APIRouter(tags=["Health"])


def get_qdrant_service(settings: Settings = Depends(get_settings)) -> QdrantService:
    """Dependency provider for QdrantService."""
    return QdrantService(settings=settings)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Basic Service Health Check",
    description="Returns service status, version, and running environment.",
)
async def service_health(
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Verify that the API microservice is running."""
    req_id = get_request_id() or "none"
    return HealthResponse(
        status="healthy",
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc).isoformat(),
        request_id=req_id,
    )


@router.get(
    "/health/postgres",
    response_model=PostgresHealthResponse,
    summary="PostgreSQL Event Tracking Health Check",
    description=(
        "Actively verifies connectivity to the PostgreSQL event-tracking database. "
        "TrackingService suppresses all database errors so the main API never fails "
        "due to a tracking outage — this endpoint is the way to detect that outage."
    ),
    responses={
        200: {"description": "PostgreSQL is reachable (or tracking is intentionally disabled)"},
        503: {"description": "PostgreSQL is enabled but unreachable", "model": PostgresHealthResponse},
    },
)
async def postgres_health(
    settings: Settings = Depends(get_settings),
) -> PostgresHealthResponse:
    """Verify live PostgreSQL connectivity for event tracking."""
    health_result = await DatabaseManager.check_health(settings=settings)
    if health_result.status == "unavailable":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_result.model_dump(),
        )  # type: ignore[return-value]
    return health_result


@router.get(
    "/health/qdrant",
    response_model=QdrantHealthResponse,
    summary="Qdrant Vector DB Health Check",
    description="Actively verifies connectivity to the Qdrant instance and checks collection state.",
    responses={
        200: {"description": "Qdrant is reachable"},
        503: {"description": "Qdrant is unreachable", "model": QdrantHealthResponse},
    },
)
async def qdrant_health(
    qdrant_service: QdrantService = Depends(get_qdrant_service),
) -> QdrantHealthResponse:
    """Verify live Qdrant vector database connectivity and configuration."""
    health_result = await qdrant_service.check_health()
    if not health_result.connected:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_result.model_dump(),
        )  # type: ignore[return-value]
    return health_result
