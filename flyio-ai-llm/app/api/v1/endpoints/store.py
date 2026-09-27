"""Store API endpoint for document ingestion, chunking, and embedding storage pipeline."""

from fastapi import APIRouter, Depends, status
from app.api.security import api_key_header
from app.core.config import Settings, get_settings
from app.core.context import get_request_id, set_request_id
from app.core.logging import logger
from app.schemas.store import StoreRequest, StoreResponse
from app.services.store_service import StoreService

# dependencies=[Depends(api_key_header)] adds the Swagger "Authorize"
# button for this router — see app/api/security.py. Actual enforcement is
# ServiceAuthMiddleware; this line does not enforce anything on its own.
router = APIRouter(tags=["LLM / Store"], dependencies=[Depends(api_key_header)])


def get_store_service(settings: Settings = Depends(get_settings)) -> StoreService:
    """Dependency injection for StoreService."""
    return StoreService(settings=settings)


@router.post(
    "/api/store",
    response_model=StoreResponse,
    status_code=status.HTTP_200_OK,
    summary="Chunk, Vectorize, and Ingest Documents into Qdrant Knowledge Base",
    description=(
        "Entry point for document ingestion. Accepts document text or pre-structured document lists, "
        "chunks text into overlapping segments, generates batched vector embeddings, "
        "and atomically stores vector points and metadata into Qdrant."
    ),
    responses={
        200: {"description": "Documents chunked and stored successfully"},
        400: {"description": "Malformed request payload or collection validation mismatch"},
        422: {"description": "Validation error"},
        503: {"description": "Vector DB / embedding provider unavailable"},
    },
)
async def store_documents(
    request: StoreRequest,
    store_service: StoreService = Depends(get_store_service),
) -> StoreResponse:
    """Process incoming documents through the store pipeline."""
    effective_req_id = request.request_id or get_request_id() or "none"
    set_request_id(effective_req_id)

    logger.info(
        f"Received store request: request_id={effective_req_id}",
        extra={"event": "api_store_received", "request_id": effective_req_id},
    )

    response = await store_service.process_store_request(
        request=request,
        request_id=effective_req_id,
    )
    return response


# Alias /v1/store provided for backward compatibility with legacy client routing conventions.
@router.post(
    "/store",
    response_model=StoreResponse,
    include_in_schema=False,
)
async def store_documents_alias(
    request: StoreRequest,
    store_service: StoreService = Depends(get_store_service),
) -> StoreResponse:
    """Alias for /v1/api/store."""
    return await store_documents(request, store_service)
