"""Service-to-service authentication middleware.

Checks the X-Service-API-Key header on every request under the API_V1_STR
prefix (/v1/*). Returns 401 Unauthorized if the key is missing or wrong.
/health (both the bare and /v1-prefixed registrations — see main.py's dual
health.router mount) and the API docs routes are explicitly excluded — no
auth needed for health checks or browsing the OpenAPI docs.

The expected key is read from the SERVICE_API_KEY environment variable.
Never hardcoded.

Mirrors flyio-scraper-service's ServiceAuthMiddleware
(src/middleware/auth.py) so both services share one auth convention —
Admin sends the same X-Service-API-Key header to either. One intentional
deviation from that mirror, not an oversight: constant-time comparison
(hmac.compare_digest) instead of `!=`, so a timing side-channel can't be
used to guess the key one byte at a time.

(An earlier version of this docstring also claimed a second deviation —
that this fails closed on an unset SERVICE_API_KEY while the scraper's
plain `!=` would fail open. That claim didn't survive a self-audit: the
`if not provided_key: return 401` guard below runs *before* the key
comparison, in both this file and the scraper's, so `provided_key` is
already guaranteed non-empty by the time either implementation compares
it against a possibly-empty SERVICE_API_KEY — an empty string can never
equal a non-empty one, so both implementations already fail closed for
an unconfigured key. The explicit `not settings.SERVICE_API_KEY` check
below is kept anyway as defense-in-depth against a future refactor that
reorders these checks, not because it changes today's behavior.)
"""

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import get_settings

# Routes that live outside the versioned API and must stay reachable without
# a service key: load balancer / orchestrator health probes, and anyone
# browsing the API docs.
_PUBLIC_EXACT_PATHS = {"/docs", "/redoc", "/openapi.json"}


def _is_public_path(path: str) -> bool:
    """True for /health, /v1/health* (dual registration — see main.py), and
    the docs routes. Everything else under API_V1_STR requires the key.
    """
    if path in _PUBLIC_EXACT_PATHS:
        return True
    if path == "/health" or path.startswith("/health/"):
        return True
    if path == "/v1/health" or path.startswith("/v1/health/"):
        return True
    return False


class ServiceAuthMiddleware(BaseHTTPMiddleware):
    """Guards API_V1_STR routes with a shared X-Service-API-Key header."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        settings = get_settings()

        if _is_public_path(path) or not path.startswith(settings.API_V1_STR):
            return await call_next(request)

        provided_key = request.headers.get("X-Service-API-Key", "")

        if not provided_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing X-Service-API-Key header."},
            )

        # provided_key is non-empty here (guarded above), so this can only
        # ever reject when SERVICE_API_KEY is unset — the `not
        # settings.SERVICE_API_KEY` half is defense-in-depth, not currently
        # load-bearing (see module docstring).
        if not settings.SERVICE_API_KEY or not hmac.compare_digest(provided_key, settings.SERVICE_API_KEY):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid service API key."},
            )

        return await call_next(request)
