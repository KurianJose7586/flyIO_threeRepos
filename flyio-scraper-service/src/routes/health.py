"""
Health check route — GET /health

No authentication required. Returns service uptime status and
current background queue depth so the caller can tell if the
service is alive and how busy it is.
"""
from datetime import datetime, timezone

from fastapi import APIRouter

from src.queue.worker import queue_size
from src.schemas.models import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service Health & Queue Status",
    description="Returns service uptime status and the current number of scraping jobs pending in the queue. No authentication required.",
)
async def health():
    return {
        "status":     "ok",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "queue_size": queue_size(),
    }

