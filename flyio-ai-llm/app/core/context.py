"""Request context management using Python contextvars."""

from contextvars import ContextVar
from typing import Optional

# Context variable storing the current request ID
_request_id_ctx_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def get_request_id() -> Optional[str]:
    """Retrieve the current request ID from the context."""
    return _request_id_ctx_var.get()


def set_request_id(request_id: str) -> None:
    """Set the request ID in the context."""
    _request_id_ctx_var.set(request_id)
