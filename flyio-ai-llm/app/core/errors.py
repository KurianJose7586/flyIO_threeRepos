"""Custom application exceptions and error codes."""

from typing import Any, Optional


class AppException(Exception):
    """Base application exception."""

    status_code: int = 500
    code: str = "INTERNAL_SERVER_ERROR"

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class InvalidRequestError(AppException):
    """Raised when an incoming client request is malformed or invalid."""

    status_code = 400
    code = "INVALID_REQUEST"


class ValidationError(AppException):
    """Raised when request data fails semantic validation."""

    status_code = 422
    code = "VALIDATION_ERROR"


class AuthenticationError(AppException):
    """Raised when authentication credentials are missing or invalid."""

    status_code = 401
    code = "AUTHENTICATION_ERROR"


class NotFoundError(AppException):
    """Raised when a requested resource is not found."""

    status_code = 404
    code = "NOT_FOUND"


class QdrantUnavailableError(AppException):
    """Raised when Qdrant vector database is unreachable or fails."""

    status_code = 503
    code = "QDRANT_UNAVAILABLE"


class LLMProviderError(AppException):
    """Raised when external LLM provider fails or is unreachable."""

    status_code = 503
    code = "LLM_PROVIDER_ERROR"
