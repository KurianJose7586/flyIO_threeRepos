"""
Pydantic schemas for request and response validation, serialization, and Swagger / OpenAPI documentation.
"""
from typing import Annotated, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


# ── Request Body Schemas ─────────────────────────────────────────────────────

"""Correlation ID a caller may supply so one identifier spans both services.

Constrained rather than free-form because it becomes a key in the job store and
is echoed back in URLs: a bounded, URL-safe token keeps
GET /scrape/jobs/{job_id} unambiguous. A UUID (what flyio-admin sends) fits
comfortably.
"""
CallerJobId = Annotated[
    str,
    Field(
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "Optional caller-supplied job identifier. When provided, the job is "
            "stored under this ID and GET /scrape/jobs/{job_id} accepts it "
            "directly, so the caller's own correlation ID spans both services. "
            "Omit to have one generated. Must be unique — reusing an in-flight "
            "ID returns 409."
        ),
        examples=["8c5373b8-69a4-430a-85ba-2075764a1fac"],
    ),
]


class ScrapeUrlsRequest(BaseModel):
    urls: List[str] = Field(
        ...,
        description="List of URLs to scrape, one per entry.",
        examples=[
            [
                "https://en.wikivoyage.org/wiki/Tokyo",
                "https://en.wikivoyage.org/wiki/Kyoto"
            ]
        ],
    )
    job_id: Optional[CallerJobId] = None


# ── Health Schemas ────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = Field(..., example="ok", description="Service operational status.")
    timestamp: str = Field(..., example="2026-09-04T14:30:00.000000+00:00", description="Current UTC timestamp (ISO 8601).")
    queue_size: int = Field(..., example=0, description="Current number of jobs queued in the background worker.")


# ── Job Schemas ───────────────────────────────────────────────────────────────

class ChunkResult(BaseModel):
    source_url: str = Field(..., example="https://en.wikivoyage.org/wiki/Tokyo", description="Source URL of the scraped page.")
    page_title: str = Field(..., example="Tokyo - Wikivoyage", description="Title of the page.")
    section_path: str = Field(..., example="Tokyo > See > Historic Temples", description="Hierarchical section path / breadcrumbs.")
    chunk_index: int = Field(..., example=0, description="Sequential index of the chunk within the page.")
    content_text: str = Field(..., example="Sensō-ji is Tokyo's oldest temple, dedicated to the bodhisattva Kannon...", description="Plain text content extracted from this section.")
    content_html: str = Field(..., example="<p>Sensō-ji is Tokyo's oldest temple, dedicated to the bodhisattva Kannon...</p>", description="Cleaned semantic HTML content.")

    # ── Consumer-compatibility fields ────────────────────────────────────────
    # Derived, not new information: `url` mirrors source_url, and `status` is
    # always "success" because a chunk only exists for a page that was crawled
    # and parsed successfully. A failed page yields no chunks, and job-level
    # outcome is already reported by JobStatusResponse.status/error.
    #
    # They exist because flyio-admin filters this array with
    # `r.status === "success" && r.url` (src/routes/llm.ts) to decide which
    # source URLs to forward to the LLM Store API. Against the shape above that
    # predicate matched nothing, so the list came back empty and Admin fell
    # through to its `targetUrls` fallback. On the /scrape/sources path there
    # are no targetUrls, so the fallback was empty too — Admin then stored
    # nothing at all: a successful crawl that ingested zero documents, with no
    # error raised anywhere.
    #
    # Emitting what that consumer already reads is cheaper and lower-risk than
    # changing the orchestration in a deployed service, and both fields are
    # additive — consumers keyed on source_url are unaffected.
    url: Optional[str] = Field(
        None,
        example="https://en.wikivoyage.org/wiki/Tokyo",
        description="Alias of `source_url`, populated automatically. Prefer `source_url` in new consumers.",
    )
    status: Literal["success"] = Field(
        "success",
        description=(
            "Always 'success' — a chunk is only produced for a page that was "
            "crawled and parsed successfully. Job-level outcome lives on "
            "JobStatusResponse.status."
        ),
    )

    @model_validator(mode="after")
    def mirror_source_url(self) -> "ChunkResult":
        """Keep `url` in lockstep with `source_url` so the two cannot drift."""
        if self.url is None:
            self.url = self.source_url
        return self


class JobCreatedResponse(BaseModel):
    job_id: str = Field(..., example="job_9f8e7d6c-5b4a-3210-fedc-ba9876543210", description="Identifier of the newly created scrape job.")


class JobStatusResponse(BaseModel):
    job_id: str = Field(..., example="job_9f8e7d6c-5b4a-3210-fedc-ba9876543210", description="Identifier of the scrape job.")
    type: Literal["urls", "sources"] = Field(..., example="urls", description="Job type ('urls' for custom URLs or 'sources' for preconfigured sources).")
    status: Literal["pending", "success", "failed"] = Field(..., example="success", description="Current job status.")
    submitted_at: str = Field(..., example="2026-09-04T14:30:00.000000+00:00", description="ISO 8601 timestamp when the job was enqueued.")
    completed_at: Optional[str] = Field(None, example="2026-09-04T14:30:15.123456+00:00", description="ISO 8601 timestamp when the job completed, or null if pending.")
    results: Optional[List[ChunkResult]] = Field(None, description="Extracted content chunks (populated when status is 'success').")
    error: Optional[str] = Field(None, example=None, description="Error message if the crawl failed (populated when status is 'failed').")


# ── Error Schemas ─────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str = Field(..., example="Error message describing the issue.", description="Error message explanation.")
