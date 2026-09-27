"""
Scrape routes — all require X-Service-API-Key authentication.

POST /scrape/urls
    Body: JSON {"urls": ["https://...", ...]}.
    Creates a job, enqueues a background crawl, returns {job_id} immediately.

POST /scrape/discover
    Body: JSON {"destination": "Jabalpur", "max_urls": 12}.
    Searches the web, filters and ranks the hits, returns candidate URLs.
    Does NOT crawl - the caller decides what to submit to /scrape/urls.

POST /scrape/sources
    Optional query params: max_pages, source_names.
    Crawls all tourism sources from settings (env or legacy config).
    Creates a job, enqueues it, returns {job_id} immediately.

GET /scrape/jobs/{job_id}
    Returns the current job status + results from the in-memory store.
    Results shape when status == "success":
      list of chunk dicts:
        {source_url, page_title, section_path, chunk_index,
         content_text, content_html}
"""
from typing import Annotated, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.security import APIKeyHeader

from src.config.settings import get_settings
from src.discovery import DiscoveryError, discover
from src.queue.worker import enqueue
from src.schemas.models import (
    DiscoverRequest,
    DiscoverResponse,
    ErrorResponse,
    JobCreatedResponse,
    JobStatusResponse,
    ScrapeUrlsRequest,
)
from src.store.jobs import JobIdConflictError, create_job, get_job

# OpenAPI security scheme — registers the global Authorize 🔒 button in Swagger UI
api_key_header = APIKeyHeader(
    name="X-Service-API-Key",
    description="Service-to-service API key. Value comes from SERVICE_API_KEY env var.",
    auto_error=False,
)

router = APIRouter()


# ── Reusable header annotation ────────────────────────────────────────────────
# Using Annotated + Header so Swagger renders an editable input box for the
# X-Service-API-Key header on every protected endpoint individually.

ApiKeyHeader = Annotated[
    str,
    Header(
        alias="X-Service-API-Key",
        description=(
            "Service-to-service API key. "
            "Must match the `SERVICE_API_KEY` configured in the server environment."
        ),
    ),
]


# ── POST /scrape/urls ─────────────────────────────────────────────────────────

@router.post(
    "/scrape/urls",
    response_model=JobCreatedResponse,
    status_code=202,
    tags=["Scraping"],
    summary="Scrape Custom URLs (Async)",
    description=(
        "Accepts a JSON body containing a list of URLs to crawl. "
        "Enqueues a background web crawl and returns a unique `job_id` immediately. "
        "Requires `X-Service-API-Key` header."
    ),
    responses={
        202: {
            "description": "Scrape job successfully queued.",
            "model": JobCreatedResponse,
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job_9f8e7d6c-5b4a-3210-fedc-ba9876543210"
                    }
                }
            },
        },
        400: {
            "description": "Empty or missing URLs in request body.",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Request body must contain at least one non-empty URL."
                    }
                }
            },
        },
        401: {
            "description": "Missing or invalid X-Service-API-Key header.",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Missing X-Service-API-Key header."
                    }
                }
            },
        },
    },
)
async def scrape_urls(
    body: ScrapeUrlsRequest,
    x_service_api_key: ApiKeyHeader,
):
    """
    Accept a JSON body with a list of URLs to scrape.
    Returns {job_id} immediately — crawl runs in the background.
    """
    urls = [u.strip() for u in body.urls if u.strip()]

    if not urls:
        raise HTTPException(
            status_code=400,
            detail="Request body must contain at least one non-empty URL.",
        )

    # Reject anything that isn't an absolute http(s) URL up front — otherwise
    # it only fails deep inside the crawl (crawl4ai and requests both refuse a
    # scheme-less string like "gorakhpur"), taking the whole batch with it.
    invalid = [
        u for u in urls
        if urlparse(u).scheme not in ("http", "https") or not urlparse(u).netloc
    ]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=(
                "Not a valid http(s) URL: " + ", ".join(invalid)
                + ". Include the scheme, e.g. https://en.wikivoyage.org/wiki/Gorakhpur"
            ),
        )

    try:
        job = create_job("urls", job_id=body.job_id)
    except JobIdConflictError:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{body.job_id}' already exists. Supply a unique job_id or omit it.",
        )
    await enqueue(job.job_id, "urls", {"urls": urls})
    return {"job_id": job.job_id}


# ── POST /scrape/discover ─────────────────────────────────────────────────────

@router.post(
    "/scrape/discover",
    response_model=DiscoverResponse,
    tags=["Scraping"],
    summary="Discover Candidate URLs for a Destination",
    description=(
        "Expands a destination name into several topic queries, searches the "
        "web, then filters, scores and caps the hits into a candidate URL list."
        "\n\n"
        "**This endpoint does not crawl anything.** It automates the step a "
        "human currently does by hand — deciding which URLs are worth "
        "pasting. The caller reviews (or auto-accepts) the candidates and "
        "submits them to `POST /scrape/urls`, so every page still goes "
        "through the same crawl, parse and chunk pipeline as before. "
        "Requires `X-Service-API-Key`."
    ),
    responses={
        200: {
            "description": "Candidate URLs, best first.",
            "model": DiscoverResponse,
            "content": {
                "application/json": {
                    "example": {
                        "destination": "Jabalpur",
                        "provider": "tavily",
                        "queries": [
                            "Jabalpur travel guide",
                            "things to do in Jabalpur",
                        ],
                        "considered": 34,
                        "candidates": [
                            {
                                "url": "https://en.wikivoyage.org/wiki/Jabalpur",
                                "title": "Jabalpur - Travel guide at Wikivoyage",
                                "domain": "wikivoyage.org",
                                "score": 100,
                                "trusted": True,
                                "query": "Jabalpur travel guide",
                            }
                        ],
                        "errors": [],
                    }
                }
            },
        },
        400: {
            "description": "Unusable destination, or no search provider configured.",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "SEARCH_API_KEY is empty but SEARCH_PROVIDER is "
                            "'tavily'. Get a key at https://app.tavily.com or "
                            "set SEARCH_PROVIDER=mock."
                        )
                    }
                }
            },
        },
        401: {
            "description": "Missing or invalid X-Service-API-Key header.",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"detail": "Missing X-Service-API-Key header."}
                }
            },
        },
        502: {
            "description": "The search provider was reached but every query failed.",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": "All 5 search queries failed. First error - 'Jabalpur travel guide': HTTPStatusError: 429"
                    }
                }
            },
        },
    },
)
async def discover_urls(
    body: DiscoverRequest,
    x_service_api_key: ApiKeyHeader,
):
    """
    Search for pages worth crawling for a destination.

    Returns candidates only — nothing is crawled and nothing is stored.

    Deduplication against an already-populated knowledge base is deliberately
    the caller's job: this service is stateless and has no view of what has
    been ingested. flyio-admin owns that in its `knowledge_base` table and
    marks the candidates it already holds.
    """
    settings = get_settings()

    try:
        result = await discover(body.destination, body.max_urls)
    except DiscoveryError as exc:
        # A bad destination or an unconfigured provider is the caller's to fix
        # (400); an upstream that took the request and then failed is not
        # (502). Either way the message carries the remedy.
        status = 502 if "search queries failed" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc))

    return {
        "destination": result.destination,
        "provider": settings.SEARCH_PROVIDER,
        "queries": result.queries,
        "considered": result.considered,
        "candidates": [
            {
                "url": c.url,
                "title": c.title,
                "domain": c.domain,
                "score": c.score,
                "trusted": c.trusted,
                "query": c.query,
            }
            for c in result.candidates
        ],
        "errors": result.errors,
    }


# ── POST /scrape/sources ──────────────────────────────────────────────────────

@router.post(
    "/scrape/sources",
    response_model=JobCreatedResponse,
    status_code=202,
    tags=["Scraping"],
    summary="Scrape Preconfigured Tourism Sources (Async)",
    description=(
        "Triggers a background crawl of all configured tourism sources "
        "(from `TOURISM_SOURCES_JSON` environment variable or legacy defaults: "
        "Wikivoyage, TourMyIndia, Holidify, Thrillophilia, TravelTriangle, IncredibleIndia). "
        "Returns a unique `job_id` immediately. Requires `X-Service-API-Key` header."
    ),
    responses={
        202: {
            "description": "Scrape job successfully queued.",
            "model": JobCreatedResponse,
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job_1a2b3c4d-5e6f-7890-abcd-ef1234567890"
                    }
                }
            },
        },
        401: {
            "description": "Missing or invalid X-Service-API-Key header.",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Invalid service API key."
                    }
                }
            },
        },
        500: {
            "description": "No tourism sources are configured.",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": "No tourism sources configured (or none matched source_names filter)."
                    }
                }
            },
        },
    },
)
async def scrape_sources(
    x_service_api_key: ApiKeyHeader,
    max_pages: Optional[int] = Query(
        default=None,
        description=(
            "Override the maximum number of pages to crawl per source. "
            "If omitted, uses the value from env/config."
        ),
        ge=1,
        le=500,
        examples=[10],
    ),
    source_names: Optional[str] = Query(
        default=None,
        description=(
            "Comma-separated list of source names to crawl. "
            "e.g. `Wikivoyage,Holidify`. "
            "If omitted, all configured sources are crawled."
        ),
        examples=["Wikivoyage,Holidify"],
    ),
    job_id: Optional[str] = Query(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "Optional caller-supplied job identifier — the query-string "
            "counterpart of ScrapeUrlsRequest.job_id, since this endpoint takes "
            "no request body. When provided, the job is stored under this ID so "
            "GET /scrape/jobs/{job_id} accepts the caller's own correlation ID. "
            "Omit to have one generated. Reusing an in-flight ID returns 409."
        ),
        examples=["8c5373b8-69a4-430a-85ba-2075764a1fac"],
    ),
):
    """
    Trigger a crawl of configured tourism sources.
    Optionally filter by source_names and override max_pages per source.
    Returns {job_id} immediately — crawl runs in the background.
    """
    settings = get_settings()
    sources = settings.get_sources()

    # Filter by source_names if provided
    if source_names:
        names = {n.strip() for n in source_names.split(",")}
        sources = [s for s in sources if s.get("name") in names]

    # Override max_pages if provided
    if max_pages is not None:
        sources = [{**s, "max_pages": max_pages} for s in sources]

    if not sources:
        raise HTTPException(
            status_code=500,
            detail=(
                "No tourism sources configured (or none matched source_names filter). "
                "Set TOURISM_SOURCES_JSON or check legacy_crawler/config.py."
            ),
        )

    try:
        job = create_job("sources", job_id=job_id)
    except JobIdConflictError:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' already exists. Supply a unique job_id or omit it.",
        )
    await enqueue(job.job_id, "sources", {"sources": sources})
    return {"job_id": job.job_id}


# ── GET /scrape/jobs/{job_id} ─────────────────────────────────────────────────

@router.get(
    "/scrape/jobs/{job_id}",
    response_model=JobStatusResponse,
    tags=["Jobs"],
    summary="Get Scrape Job Status & Results",
    description=(
        "Returns the current state and results of a scraping job. "
        "Status will be `pending`, `success`, or `failed`. "
        "When `success`, the `results` list contains parsed content chunks. "
        "Requires `X-Service-API-Key` header."
    ),
    responses={
        200: {
            "description": "Current status and results of the job.",
            "model": JobStatusResponse,
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job_9f8e7d6c-5b4a-3210-fedc-ba9876543210",
                        "type": "urls",
                        "status": "success",
                        "submitted_at": "2026-09-04T14:30:00.000000+00:00",
                        "completed_at": "2026-09-04T14:30:15.123456+00:00",
                        "results": [
                            {
                                "source_url": "https://en.wikivoyage.org/wiki/Tokyo",
                                "page_title": "Tokyo - Wikivoyage",
                                "section_path": "Tokyo > See > Historic Temples",
                                "chunk_index": 0,
                                "content_text": "Sensō-ji is Tokyo's oldest temple, dedicated to the bodhisattva Kannon...",
                                "content_html": "<p>Sensō-ji is Tokyo's oldest temple, dedicated to the bodhisattva Kannon...</p>"
                            }
                        ],
                        "error": None,
                    }
                }
            },
        },
        401: {
            "description": "Missing or invalid X-Service-API-Key header.",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Missing X-Service-API-Key header."
                    }
                }
            },
        },
        404: {
            "description": "Job ID not found (process may have restarted).",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Job 'job_9f8e7d6c-5b4a-3210-fedc-ba9876543210' not found. The service may have restarted."
                    }
                }
            },
        },
    },
)
async def get_job_status(
    job_id: str,
    x_service_api_key: ApiKeyHeader,
):
    """
    Return the current state of a job from the in-memory store.

    Status values:
      pending  — job is queued or actively running
      success  — crawl completed; results contains chunk list
      failed   — crawl failed; error contains the exception message

    Returns 404 if the job_id is unknown (service may have restarted).
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found. The service may have restarted since this job was created.",
        )
    return job.to_dict()
