"""
Service-to-service authentication middleware.

Checks the X-Service-API-Key header on every request to /scrape/*.
Returns 401 Unauthorized if the key is missing or wrong.
/health is explicitly excluded — no auth needed for health checks.

The expected key is read from the SERVICE_API_KEY environment variable.
Never hardcoded.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.config.settings import get_settings


class ServiceAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only guard /scrape/* routes — /health is public
        if request.url.path.startswith("/scrape"):
            settings = get_settings()
            provided_key = request.headers.get("X-Service-API-Key", "")

            if not provided_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing X-Service-API-Key header."},
                )

            if provided_key != settings.SERVICE_API_KEY:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid service API key."},
                )

        return await call_next(request)
