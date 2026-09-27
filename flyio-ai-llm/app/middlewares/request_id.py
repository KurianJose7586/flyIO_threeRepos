"""Middleware to extract, generate, and propagate correlation request_id."""

import uuid
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import set_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Ensures every HTTP request has an associated request_id."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Check standard headers for incoming request ID
        header_request_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Correlation-ID")
            or request.headers.get("request-id")
        )

        if header_request_id and header_request_id.strip():
            req_id = header_request_id.strip()
        else:
            # Generate deterministic prefixed ID
            req_id = f"req_{uuid.uuid4().hex[:12]}"

        # Store in contextvars for downstream services and logging
        set_request_id(req_id)
        request.state.request_id = req_id

        response = await call_next(request)

        # Propagate back to caller in response headers
        response.headers["X-Request-ID"] = req_id
        return response
