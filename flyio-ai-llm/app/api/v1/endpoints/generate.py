"""Generate API endpoint for LLM retrieval and plan generation workflow."""

from fastapi import APIRouter, Depends, status
from app.api.security import api_key_header
from app.core.config import Settings, get_settings
from app.core.context import get_request_id, set_request_id
from app.core.logging import logger
from app.schemas.generate import GenerateRequest, GenerateResponse
from app.services.llm.service import LLMService

# dependencies=[Depends(api_key_header)] adds the Swagger "Authorize"
# button for this router — see app/api/security.py. Actual enforcement is
# ServiceAuthMiddleware; this line does not enforce anything on its own.
router = APIRouter(tags=["LLM / AI"], dependencies=[Depends(api_key_header)])


def get_llm_service(settings: Settings = Depends(get_settings)) -> LLMService:
    """Dependency injection for LLMService."""
    return LLMService(settings=settings)


@router.post(
    "/api/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate AI Travel Plan & Retrieval Workflow",
    description=(
        "Entry point for the AI/LLM planning engine. Accepts a prompt, vectorizes it via EmbeddingService, "
        "and queries Qdrant to determine whether relevant source data exists. "
        "Returns status='data_found' with a structured TravelPlan (destinations, attractions, hotels, daily schedule, budget, tips) "
        "or status='data_required' if source data scraping is needed."
    ),
    responses={
        200: {"description": "Workflow executed successfully (data found or required)"},
        400: {"description": "Malformed request payload"},
        422: {"description": "Validation error"},
        503: {"description": "Vector DB / LLM provider unavailable"},
    },
)
async def generate(
    request: GenerateRequest,
    llm_service: LLMService = Depends(get_llm_service),
) -> GenerateResponse:
    """Process incoming prompt through the Day 2 retrieval workflow."""
    # If the client passed an explicit request_id in body, prioritize it
    effective_req_id = request.request_id or get_request_id() or "none"
    set_request_id(effective_req_id)

    logger.info(
        f"Received generate request: request_id={effective_req_id}",
        extra={"event": "api_generate_received", "request_id": effective_req_id},
    )

    response = await llm_service.process_generate_request(
        request=request,
        request_id=effective_req_id,
    )
    return response


# Also alias /generate for flexibility
@router.post(
    "/generate",
    response_model=GenerateResponse,
    include_in_schema=False,
)
async def generate_alias(
    request: GenerateRequest,
    llm_service: LLMService = Depends(get_llm_service),
) -> GenerateResponse:
    """Alias for /api/generate."""
    return await generate(request, llm_service)
