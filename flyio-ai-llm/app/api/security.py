"""OpenAPI security scheme declaration for the X-Service-API-Key header.

This is documentation/UI wiring only — it does NOT enforce anything by
itself (APIKeyHeader(auto_error=False) just extracts the header value for
FastAPI's dependency system and OpenAPI schema; it never rejects a
request). The actual enforcement is ServiceAuthMiddleware
(app/middlewares/service_auth.py), which runs for every /v1/* request
regardless of whether a route declares this dependency.

What adding `dependencies=[Depends(api_key_header)]` to a router DOES do:
it makes FastAPI list X-Service-API-Key as a required security requirement
in the generated OpenAPI schema, which is what makes Swagger UI (/docs)
show an "Authorize" button — clicking it once applies the header to every
"Try it out" call on that router, the same UX flyio-scraper-service's
Swagger docs already have (src/routes/scrape.py). Without this, there was
no way to supply the header through the Swagger UI form at all, since
ServiceAuthMiddleware reads request.headers directly rather than declaring
a FastAPI Header()/security dependency anywhere.

Shared here (rather than declared separately in each router file, as the
scraper's single-router repo does) since flyio-ai-llm has two routers
(generate.py, store.py) that both need the same scheme.
"""

from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(
    name="X-Service-API-Key",
    description="Service-to-service API key passed in the X-Service-API-Key header. Enforced by ServiceAuthMiddleware.",
    auto_error=False,
)
