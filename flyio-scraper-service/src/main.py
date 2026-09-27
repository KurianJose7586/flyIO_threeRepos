"""
FastAPI application entry point.

Registers:
  - ServiceAuthMiddleware (X-Service-API-Key on /scrape/*)
  - /health router (no auth)
  - /scrape router (auth enforced by middleware)

On startup, starts a single background asyncio worker that processes
the job queue for the lifetime of the service process.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.middleware.auth import ServiceAuthMiddleware
from src.queue.worker import worker
from src.routes.health import router as health_router
from src.routes.scrape import router as scrape_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background queue worker on startup; nothing to clean up on shutdown."""
    asyncio.create_task(worker())
    yield


openapi_tags = [
    {
        "name": "Health",
        "description": "Public health check and queue monitoring endpoints. No authentication required.",
    },
    {
        "name": "Scraping",
        "description": "Async endpoints to trigger web crawling jobs. Requires `X-Service-API-Key`.",
    },
    {
        "name": "Jobs",
        "description": "Async job status and result retrieval endpoints. Requires `X-Service-API-Key`.",
    },
]

app = FastAPI(
    title="flyio-scraper-service",
    description=(
        "Stateless web scraping microservice. "
        "Wraps crawl4ai + Wikivoyage API and exposes a stable HTTP API "
        "for flyio-admin to trigger scrape jobs and retrieve parsed content chunks."
    ),
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=openapi_tags,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_extra={
        "components": {
            "securitySchemes": {
                "APIKeyHeader": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Service-API-Key",
                    "description": (
                        "Service-to-service API key. "
                        "Value comes from the SERVICE_API_KEY environment variable. "
                        "Required on all /scrape/* endpoints."
                    ),
                }
            }
        }
    },
)

# ── Middleware (applied in reverse order — auth runs first) ───────────────────
app.add_middleware(ServiceAuthMiddleware)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(scrape_router)

