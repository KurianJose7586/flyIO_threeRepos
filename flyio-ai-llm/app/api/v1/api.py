"""API v1 router aggregator."""

from fastapi import APIRouter
from app.api.v1.endpoints import generate, health, store

api_router = APIRouter()

# Include health routes
api_router.include_router(health.router)

# Include LLM / Generation routes
api_router.include_router(generate.router)

# Include Store / Vector Ingestion routes
api_router.include_router(store.router)

