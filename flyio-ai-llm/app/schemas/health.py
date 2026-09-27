"""Health check schemas."""

from typing import Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Basic service health response."""

    status: str = Field(..., example="healthy")
    service: str = Field(..., example="flyio-ai-llm")
    version: str = Field(..., example="0.1.0")
    environment: str = Field(..., example="development")
    timestamp: str = Field(..., example="2026-08-15T04:10:00Z")
    request_id: Optional[str] = Field(default=None, example="req_12345")


class PostgresHealthResponse(BaseModel):
    """PostgreSQL event-tracking connectivity health check response."""

    status: str = Field(..., description="'connected', 'unavailable', or 'disabled'", example="connected")
    connected: bool = Field(..., description="Boolean flag for easy polling")
    database_enabled: bool = Field(..., description="Value of the DATABASE_ENABLED setting")
    request_id: Optional[str] = Field(default=None, example="req_12345")
    timestamp: str = Field(..., example="2026-08-15T04:10:00Z")
    details: Optional[str] = Field(default=None, example="Connected. Event tracking is active.")


class QdrantHealthResponse(BaseModel):
    """Detailed Qdrant vector database health check response."""

    status: str = Field(..., description="'connected' or 'unavailable'", example="connected")
    connected: bool = Field(..., description="Boolean flag for easy polling")
    qdrant_url: str = Field(..., example="http://localhost:6333")
    collection_name: str = Field(..., example="flyio_knowledge_base")
    collection_exists: bool = Field(..., description="Whether configured collection exists")
    vector_size: Optional[int] = Field(default=None, description="Configured embedding dimension")
    request_id: Optional[str] = Field(default=None, example="req_12345")
    timestamp: str = Field(..., example="2026-08-15T04:10:00Z")
    details: Optional[str] = Field(default=None, example="Collection ready for search")
