"""Error response schemas."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detailed error object."""

    code: str = Field(..., description="Machine-readable error code", example="QDRANT_UNAVAILABLE")
    message: str = Field(..., description="Human-readable error description", example="Vector database is currently unavailable")
    details: Optional[Any] = Field(default=None, description="Optional extra error details or validation violations")


class ErrorResponse(BaseModel):
    """Standardized API error response format across all endpoints."""

    success: bool = Field(default=False, description="Always false for error responses")
    request_id: str = Field(..., description="Common request/job ID", example="req_12345")
    error: ErrorDetail = Field(..., description="Error specifics")
