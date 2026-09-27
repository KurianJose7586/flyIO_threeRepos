"""Store API schemas for document ingestion and vector database storage."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator

# Chunk fields that StoreDocumentItem will also accept nested inside `metadata`.
# See StoreDocumentItem.hoist_chunk_fields_from_metadata for why.
_METADATA_FALLBACK_KEYS = ("section_path", "chunk_index", "source_url", "content_html", "total_chunks")


class StoreDocumentItem(BaseModel):
    """Individual document or chunk payload to be vectorized and stored."""

    id: Optional[str] = Field(
        default=None,
        description="Optional unique identifier for document/chunk. If omitted, a deterministic UUID will be generated.",
        example="doc_98765",
    )
    text: Optional[str] = Field(
        default=None,
        description="Document text or chunk content",
        example="Fly.io provides global application deployment platform using microVMs.",
    )
    content: Optional[str] = Field(
        default=None,
        description="Alias for text content",
    )
    title: Optional[str] = Field(
        default=None,
        description="Optional document title",
        example="Fly.io Architecture Overview",
    )
    destination: Optional[str] = Field(
        default=None,
        description="Optional city/region destination for travel document",
        example="Paris, France",
    )
    category: Optional[str] = Field(
        default=None,
        description="Optional category (e.g. attraction, hotel, guide)",
        example="attraction",
    )
    source_url: Optional[str] = Field(
        default=None,
        description="Optional URL or source location of document",
        example="https://fly.io/docs/architecture",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Custom key-value metadata payload to preserve with vector point",
    )

    # Mirror flyio-scraper-service's ChunkResult shape (GET /scrape/jobs/{job_id}
    # response items) so Admin can forward a scraped chunk with minimal
    # transformation when StoreRequest.pre_chunked=True. Only meaningful in
    # that mode — see StoreRequest.pre_chunked and process_store_request().
    section_path: Optional[str] = Field(
        default=None,
        description=(
            "Hierarchical section path / breadcrumbs from the source page "
            "(e.g. 'Tokyo > See > Historic temples'), as produced by the "
            "scraper's semantic parser. Only used when the parent "
            "StoreRequest.pre_chunked=True: embedded alongside the chunk text "
            "for retrieval, and part of the deterministic point ID so "
            "re-scraping the same section updates it in place."
        ),
        example="Tokyo > See > Historic temples",
    )
    page_title: Optional[str] = Field(
        default=None,
        description=(
            "Title of the source page, matching the scraper's ChunkResult.page_title. "
            "Falls back to `title` when set and this is omitted, and vice versa "
            "— set whichever is more convenient for the caller."
        ),
        example="Tokyo - Wikivoyage",
    )
    chunk_index: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "0-based index of this chunk within its source page, matching the "
            "scraper's ChunkResult.chunk_index. Only used when the parent "
            "StoreRequest.pre_chunked=True — ignored otherwise, since this "
            "service computes its own chunk_index when it does the splitting."
        ),
        example=0,
    )
    total_chunks: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Total number of chunks in this document's source page. Only used "
            "when the parent StoreRequest.pre_chunked=True, and only needed "
            "when a caller splits one page across several store requests to "
            "keep each one inside its own timeout budget: this service "
            "otherwise infers the total from how many sibling items share a "
            "source_url *in the current request*, which undercounts once a "
            "page is sent in batches. Omit it and that inference applies as "
            "before."
        ),
        example=27,
    )
    content_html: Optional[str] = Field(
        default=None,
        description="Cleaned semantic HTML for this chunk, matching the scraper's ChunkResult.content_html. Stored in the point payload if provided; never embedded.",
    )

    @property
    def effective_title(self) -> Optional[str]:
        """`title` takes precedence; falls back to `page_title` — see that field's docstring."""
        return self.title or self.page_title

    # Callers that carry the scraper's chunk fields inside `metadata` rather
    # than at the top level are accommodated rather than silently degraded.
    # flyio-admin does exactly this (kbToLlmStore.prepareDocumentsFromKB builds
    # `metadata: {source_url, title, section_path, chunk_index}`), and because
    # unknown/misplaced keys are simply not read, pre_chunked mode lost
    # section_path and chunk_index with no error anywhere — which silently
    # changed how point IDs are derived (see generate_prechunked_point_id) and
    # dropped section context from the embedded text. Both are quality
    # regressions that produce a perfectly successful-looking 200.
    #
    # Top level always wins; this only fills what the caller left unset.

    @model_validator(mode="after")
    def hoist_chunk_fields_from_metadata(self) -> "StoreDocumentItem":
        """Fill unset chunk fields from `metadata` when the caller nested them there."""
        if not self.metadata:
            return self

        for key in _METADATA_FALLBACK_KEYS:
            if getattr(self, key, None) is None and self.metadata.get(key) is not None:
                setattr(self, key, self.metadata[key])

        # Assignment above bypasses field validation, so chunk_index could land
        # here as a string ("3") from a JSON caller that stringified it. Coerce
        # rather than reject: an unusable value falls back to None and the
        # normal positional index applies, which is what would have happened
        # had it never been sent.
        if self.chunk_index is not None and not isinstance(self.chunk_index, int):
            try:
                self.chunk_index = int(self.chunk_index)
            except (TypeError, ValueError):
                self.chunk_index = None
        if isinstance(self.chunk_index, int) and self.chunk_index < 0:
            self.chunk_index = None

        # Same treatment for total_chunks — hoisted values bypass validation,
        # and an unusable one falls back to the inferred group size.
        if self.total_chunks is not None and not isinstance(self.total_chunks, int):
            try:
                self.total_chunks = int(self.total_chunks)
            except (TypeError, ValueError):
                self.total_chunks = None
        if isinstance(self.total_chunks, int) and self.total_chunks < 1:
            self.total_chunks = None

        # `title` and `page_title` are interchangeable here (see effective_title),
        # so a nested `title` may satisfy either — only fill if both are unset.
        if self.title is None and self.page_title is None:
            nested_title = self.metadata.get("title") or self.metadata.get("page_title")
            if nested_title:
                self.page_title = nested_title

        return self

    @model_validator(mode="after")
    def validate_content_presence(self) -> "StoreDocumentItem":
        txt = (self.text or self.content or "").strip()
        if not txt:
            raise ValueError("StoreDocumentItem must contain non-empty 'text' or 'content'")
        if not self.text:
            self.text = txt
        return self


class StoreRequest(BaseModel):
    """Incoming request for storing/ingesting documents into Qdrant vector database."""

    request_id: Optional[str] = Field(
        default=None,
        description="Optional correlation request ID. If omitted, one will be generated.",
        example="req_store_123",
    )
    documents: Optional[List[StoreDocumentItem]] = Field(
        default=None,
        description="List of document items to be vectorized and stored.",
    )
    text: Optional[str] = Field(
        default=None,
        description="Raw document text string to store (single document convenience)",
        example="Fly.io is a platform for running application code globally.",
    )
    content: Optional[str] = Field(
        default=None,
        description="Alias for text string",
    )
    title: Optional[str] = Field(
        default=None,
        description="Optional document title when using top-level text",
    )
    destination: Optional[str] = Field(
        default=None,
        description="Optional destination when using top-level text",
    )
    category: Optional[str] = Field(
        default=None,
        description="Optional category when using top-level text",
    )
    source_url: Optional[str] = Field(
        default=None,
        description="Optional source URL when using top-level text",
    )
    collection_name: Optional[str] = Field(
        default=None,
        description="Target Qdrant collection name (defaults to QDRANT_COLLECTION_NAME setting)",
    )
    chunk_size: int = Field(
        default=500,
        gt=0,
        description="Maximum character length per text chunk if chunking is performed",
    )
    chunk_overlap: int = Field(
        default=50,
        ge=0,
        description="Character overlap between consecutive chunks",
    )
    pre_chunked: bool = Field(
        default=False,
        description=(
            "When True, every item in `documents` is treated as one final "
            "chunk — chunk_size/chunk_overlap are ignored and no re-splitting "
            "happens. Use this when documents already carry the scraper's own "
            "semantic sections (StoreDocumentItem.section_path/chunk_index), "
            "so this service doesn't cut across boundaries the scraper "
            "already established. See StoreDocumentItem for the per-item "
            "fields this mode reads."
        ),
    )
    mode: Optional[str] = Field(
        default=None,
        description=(
            "Alias for `pre_chunked`, accepted for callers that express the "
            "choice as a mode string: 'pre_chunked' is equivalent to "
            "pre_chunked=true, 'auto' to pre_chunked=false. Prefer the boolean "
            "— this exists so an existing caller keeps working, not as a second "
            "way to spell new integrations."
        ),
        example="pre_chunked",
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context metadata to attach to all stored points",
    )

    @model_validator(mode="after")
    def apply_mode_alias(self) -> "StoreRequest":
        """Map the `mode` string onto `pre_chunked`.

        flyio-admin's llmClient.storeDocuments() sends `mode: "pre_chunked"`
        (and documents its intent as such), but the field this service reads is
        the boolean `pre_chunked`. Pydantic ignores unknown keys by default, so
        that request parsed cleanly, `pre_chunked` stayed False, and every
        scraper chunk Admin forwarded was silently re-split at 500 characters —
        a 200 OK that quietly did the opposite of what the caller asked for.

        Accepting the alias here fixes the integration from this side, so the
        contract owner absorbs the mismatch rather than requiring a coordinated
        change in a service that is already deployed and working.

        An explicit `pre_chunked` in the same request wins: a caller that sends
        both means the boolean, and `mode` should never silently override it.
        An unrecognised `mode` is rejected rather than ignored — that is the
        failure mode this whole validator exists to eliminate.
        """
        if self.mode is None:
            return self

        normalized = self.mode.strip().lower()
        if normalized not in {"pre_chunked", "auto"}:
            raise ValueError(
                f"Unsupported mode '{self.mode}'. Expected 'pre_chunked' or 'auto' "
                "(or omit `mode` and set the `pre_chunked` boolean directly)."
            )

        if "pre_chunked" not in self.model_fields_set:
            self.pre_chunked = normalized == "pre_chunked"

        return self

    @model_validator(mode="after")
    def validate_payload_presence(self) -> "StoreRequest":
        has_docs = bool(self.documents and len(self.documents) > 0)
        has_text = bool((self.text or self.content or "").strip())
        if not has_docs and not has_text:
            raise ValueError("StoreRequest must contain either 'documents' list or 'text'/'content' string")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be strictly less than chunk_size")
        return self


class StorePointDetail(BaseModel):
    """Details of an individual stored point."""

    id: str = Field(..., description="Qdrant point ID")
    chunk_index: int = Field(..., description="Index of chunk within parent document")
    total_chunks: int = Field(..., description="Total chunks in parent document")
    text_snippet: str = Field(..., description="Prefix snippet of chunk text")


class StoreResponse(BaseModel):
    """Response returned after successful document chunking and vector storage."""

    success: bool = Field(default=True, description="Execution success flag")
    request_id: str = Field(..., description="Correlation request ID")
    status: str = Field(default="stored", description="Status indicator (e.g. 'stored')")
    stored_count: int = Field(..., description="Total number of vector points inserted into Qdrant")
    document_ids: List[str] = Field(..., description="List of IDs of stored Qdrant vector points")
    points: List[StorePointDetail] = Field(default_factory=list, description="Details of stored chunks")
    collection_name: str = Field(..., description="Target Qdrant collection name")
    message: str = Field(..., description="Summary message of the store operation")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Echoed metadata")
