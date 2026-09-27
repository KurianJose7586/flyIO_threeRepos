"""Qdrant search schemas and result models."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SearchResultItem(BaseModel):
    """Individual matched vector document item."""

    id: Any = Field(..., description="Document / point ID in Qdrant")
    score: float = Field(..., description="Similarity score (e.g. cosine similarity)", example=0.88)
    payload: Dict[str, Any] = Field(default_factory=dict, description="Metadata payload stored in vector point")
    text: Optional[str] = Field(default=None, description="Extracted text snippet or content if present in payload")


class SearchResult(BaseModel):
    """Structured Qdrant search result distinguishing found, not found, and metadata."""

    found: bool = Field(..., description="True if at least one matching vector was found above threshold")
    data_required: bool = Field(..., description="True if data was missing and needs scraping/ingestion")
    total_results: int = Field(default=0, description="Number of results returned")
    results: List[SearchResultItem] = Field(default_factory=list, description="List of matched items")
    request_id: str = Field(..., description="Job / request correlation ID", example="req_12345")
    message: str = Field(..., description="Human-readable search outcome summary")
