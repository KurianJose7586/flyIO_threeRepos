"""Store service for document chunking, batched embedding generation, and Qdrant ingestion."""

import hashlib
import uuid
from typing import Any, Dict, List, Optional

from app.core.config import Settings, get_settings
from app.core.errors import InvalidRequestError
from app.core.logging import logger
from app.schemas.store import (
    StoreDocumentItem,
    StorePointDetail,
    StoreRequest,
    StoreResponse,
)
from app.services.embeddings.service import EmbeddingService
from app.services.qdrant.service import QdrantService
from app.services.tracking_service import TrackingService


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:

    """Split input text into overlapping chunks.

    Tries word boundary splitting before hard character splitting.
    Ensures chunk_overlap characters repeat between consecutive chunks.
    """
    cleaned_text = text.strip()
    if not cleaned_text:
        return []
    if len(cleaned_text) <= chunk_size:
        return [cleaned_text]

    chunks: List[str] = []
    start = 0
    text_len = len(cleaned_text)

    while start < text_len:
        end = start + chunk_size
        if end >= text_len:
            chunks.append(cleaned_text[start:].strip())
            break

        # Find word boundary near chunk_size limit
        space_idx = cleaned_text.rfind(" ", start, end)
        if space_idx > start + (chunk_size // 2):
            end = space_idx

        chunk = cleaned_text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Advance start index with overlap
        start = max(start + 1, end - chunk_overlap)

    return chunks


def generate_deterministic_point_id(doc_identifier: str, chunk_index: int, chunk_text_content: str) -> str:
    """Generate a deterministic UUID point ID string for Qdrant idempotency.

    Includes the chunk's own text in the seed, so this service's own
    character-boundary re-chunking of the *same* source document produces
    stable IDs run to run (same text in -> same chunks out -> same IDs),
    while a source text edit naturally produces new IDs rather than
    silently overwriting semantically different content under an old ID.
    """
    seed_str = f"{doc_identifier}::chunk_{chunk_index}::{chunk_text_content}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, seed_str))


def generate_prechunked_point_id(source_url: str, section_path: str, chunk_index: int) -> str:
    """Generate a deterministic point ID for an already-chunked (pre_chunked=True)
    document item, seeded from (source_url, section_path, chunk_index) rather
    than the chunk text itself.

    Unlike generate_deterministic_point_id, this is deliberately insensitive
    to the chunk's own text: pre-chunked items come from the scraper's own
    semantic sectioning, and re-scraping the same page section should update
    that section's point in place even if the scraped wording shifts
    slightly, rather than accumulate near-duplicate points under new IDs
    every time the source page is re-crawled.
    """
    seed_str = f"prechunked::{source_url}::{section_path}::chunk_{chunk_index}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, seed_str))


class StoreService:
    """Service managing document chunking, batched embeddings, and Qdrant storage."""

    def __init__(
        self,
        qdrant_service: Optional[QdrantService] = None,
        embedding_service: Optional[EmbeddingService] = None,
        tracking_service: Optional[TrackingService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.qdrant_service = qdrant_service or QdrantService(settings=self.settings)
        self.embedding_service = embedding_service or EmbeddingService(settings=self.settings)
        self.tracking_service = tracking_service or TrackingService(settings=self.settings)

    def _enforce_batch_limits(self, request: StoreRequest) -> None:
        """Reject an oversized request before any I/O — no cap here and a
        single POST /v1/api/store call could exhaust memory building the
        embedding batch, or blow an API-metered embedding provider's
        per-call cost/payload limit in one shot. See
        Settings.STORE_MAX_DOCUMENTS / STORE_MAX_TOTAL_CHARS.

        Counts documents and characters the same way process_store_request
        itself will build raw_items below — including the top-level
        text/content convenience field as one implicit document — so this
        check reflects what's actually about to be processed, not just
        len(request.documents).
        """
        doc_count = len(request.documents) if request.documents else 0
        total_chars = sum(len(d.text or d.content or "") for d in (request.documents or []))

        top_text = (request.text or request.content or "").strip()
        if top_text:
            doc_count += 1
            total_chars += len(top_text)

        if doc_count > self.settings.STORE_MAX_DOCUMENTS:
            raise InvalidRequestError(
                message=(
                    f"Request contains {doc_count} document(s), exceeding the "
                    f"configured limit of {self.settings.STORE_MAX_DOCUMENTS} per "
                    "request. Split into multiple POST /v1/api/store calls."
                ),
                details={"document_count": doc_count, "limit": self.settings.STORE_MAX_DOCUMENTS},
            )

        if total_chars > self.settings.STORE_MAX_TOTAL_CHARS:
            raise InvalidRequestError(
                message=(
                    f"Request contains {total_chars} total characters, exceeding "
                    f"the configured limit of {self.settings.STORE_MAX_TOTAL_CHARS} "
                    "per request. Split into multiple POST /v1/api/store calls."
                ),
                details={"total_chars": total_chars, "limit": self.settings.STORE_MAX_TOTAL_CHARS},
            )

    async def process_store_request(
        self,
        request: StoreRequest,
        request_id: str,
    ) -> StoreResponse:
        """Process incoming store request:

        1. Extract document items (from request.documents or top-level text/content)
        2. Chunk each document into segments of max `chunk_size`
        3. Batch embed all chunks in a single embedding call (`embed_batch`)
        4. Ingest vectors and payloads atomically into Qdrant collection
        5. Return structured StoreResponse
        """
        self._enforce_batch_limits(request)

        col_name = request.collection_name or self.settings.QDRANT_COLLECTION_NAME

        self.tracking_service.log_event(
            "store_started",
            status="started",
            message=f"Starting store workflow in collection '{col_name}'",
            metadata=request.metadata,
            request_id=request_id,
        )

        # Validate collection existence and vector dimension BEFORE embedding generation to avoid wasted API costs
        if col_name == self.settings.QDRANT_COLLECTION_NAME:
            await self.qdrant_service.ensure_collection(col_name)
        await self.qdrant_service.validate_collection(col_name)


        # Collect raw input documents
        raw_items: List[StoreDocumentItem] = []
        if request.documents:
            raw_items.extend(request.documents)

        top_text = (request.text or request.content or "").strip()
        if top_text:
            raw_items.append(
                StoreDocumentItem(
                    text=top_text,
                    title=request.title,
                    destination=request.destination,
                    category=request.category,
                    source_url=request.source_url,
                    metadata=request.metadata or {},
                )
            )

        def _base_doc_id(doc: StoreDocumentItem, doc_index: int) -> str:
            return doc.id or f"doc_{hashlib.md5((doc.source_url or doc.effective_title or f'idx_{doc_index}').encode('utf-8')).hexdigest()[:12]}"

        # pre_chunked mode: each item IS already one final chunk from the
        # scraper (one page-section per item), so total_chunks per document
        # is the count of sibling items sharing the same base_doc_id
        # (source_url) in this request — not something derived from local
        # re-splitting, since none happens in this mode. Precompute those
        # group sizes before the main loop below.
        group_sizes: Dict[str, int] = {}
        if request.pre_chunked:
            for doc_index, doc in enumerate(raw_items):
                bid = _base_doc_id(doc, doc_index)
                group_sizes[bid] = group_sizes.get(bid, 0) + 1

        # Pre-process all documents into chunk payloads
        chunk_metadata_list: List[Dict[str, Any]] = []
        all_chunk_texts: List[str] = []
        next_index_in_group: Dict[str, int] = {}

        for doc_index, doc in enumerate(raw_items):
            doc_text = doc.text or doc.content or ""
            base_doc_id = _base_doc_id(doc, doc_index)

            if request.pre_chunked:
                # No local re-splitting — splitting an already-scraped section
                # would cut across the semantic boundaries the scraper's
                # parser already established.
                chunks = [doc_text] if doc_text.strip() else []
                # An explicit per-item total wins over the inferred group size:
                # a caller that splits one page across several store requests
                # knows the real total, while group_sizes only ever sees the
                # items present in *this* request. See
                # StoreDocumentItem.total_chunks.
                total_chunks = doc.total_chunks or group_sizes.get(base_doc_id, 1)
            else:
                chunks = chunk_text(
                    text=doc_text,
                    chunk_size=request.chunk_size,
                    chunk_overlap=request.chunk_overlap,
                )
                total_chunks = len(chunks)

            for chunk_idx, chunk in enumerate(chunks):
                combined_metadata = {
                    **(request.metadata or {}),
                    **(doc.metadata or {}),
                }

                if request.pre_chunked:
                    # Prefer the scraper's own 0-based index; fall back to a
                    # per-document running counter (also 0-based, to match)
                    # only when the caller omitted it.
                    effective_chunk_index = (
                        doc.chunk_index if doc.chunk_index is not None
                        else next_index_in_group.get(base_doc_id, 0)
                    )
                    next_index_in_group[base_doc_id] = effective_chunk_index + 1

                    if doc.source_url:
                        point_id = generate_prechunked_point_id(doc.source_url, doc.section_path or "", effective_chunk_index)
                    else:
                        # Can't form the (source_url, section_path, chunk_index)
                        # key this mode is meant to use — fall back to the
                        # text-hash scheme rather than risk colliding IDs
                        # across unrelated documents.
                        point_id = generate_deterministic_point_id(base_doc_id, effective_chunk_index, chunk)

                    # Embed the section path alongside the text — real
                    # retrieval signal ("Tokyo > See > Historic temples"
                    # narrows what the chunk is about) at no extra cost. The
                    # *stored* payload text stays the clean chunk below, not
                    # this augmented string, so prompt context built from it
                    # doesn't carry the breadcrumb as visible noise.
                    embed_text = f"{doc.section_path}\n\n{chunk}" if doc.section_path else chunk
                else:
                    effective_chunk_index = chunk_idx + 1
                    point_id = generate_deterministic_point_id(base_doc_id, effective_chunk_index, chunk)
                    embed_text = chunk

                payload = {
                    "text": chunk,
                    "title": doc.effective_title or f"Document {doc_index+1}",
                    "destination": doc.destination,
                    "category": doc.category,
                    "source_url": doc.source_url,
                    "section_path": doc.section_path,
                    "content_html": doc.content_html,
                    "chunk_index": effective_chunk_index,
                    "total_chunks": total_chunks,
                    "parent_doc_id": base_doc_id,
                    "metadata": combined_metadata,
                }

                chunk_metadata_list.append({
                    "id": point_id,
                    "chunk_index": effective_chunk_index,
                    "total_chunks": total_chunks,
                    "chunk": chunk,
                    "payload": payload,
                })
                all_chunk_texts.append(embed_text)

        # Batched embedding call across all chunks from the single request
        vectors: List[List[float]] = []
        if all_chunk_texts:
            vectors = await self.embedding_service.embed_batch(all_chunk_texts)
            self.tracking_service.log_event(
                "embedding_generated",
                status="completed",
                message=f"Batch embedding generated successfully for {len(vectors)} chunk(s)",
                metadata={"chunk_count": len(vectors)},
                request_id=request_id,
            )

        # Assemble Qdrant point objects
        qdrant_points: List[Dict[str, Any]] = []
        point_details: List[StorePointDetail] = []
        document_ids: List[str] = []

        for meta, vector in zip(chunk_metadata_list, vectors):
            qdrant_points.append({
                "id": meta["id"],
                "vector": vector,
                "payload": meta["payload"],
            })

            point_details.append(
                StorePointDetail(
                    id=meta["id"],
                    chunk_index=meta["chunk_index"],
                    total_chunks=meta["total_chunks"],
                    text_snippet=meta["chunk"][:80] + "..." if len(meta["chunk"]) > 80 else meta["chunk"],
                )
            )
            document_ids.append(meta["id"])

        # Atomic batch upsert into Qdrant (all-or-nothing failure handling)
        self.tracking_service.log_event(
            "qdrant_insert_started",
            status="started",
            message=f"Executing Qdrant batch upsert of {len(qdrant_points)} vector point(s)",
            request_id=request_id,
        )
        await self.qdrant_service.upsert_points(
            points=qdrant_points,
            collection_name=col_name,
        )
        self.tracking_service.log_event(
            "qdrant_insert_completed",
            status="completed",
            message=f"Successfully stored {len(qdrant_points)} point(s) in Qdrant collection '{col_name}'",
            metadata={"stored_count": len(qdrant_points)},
            request_id=request_id,
        )

        return StoreResponse(
            success=True,
            request_id=request_id,
            status="stored",
            stored_count=len(qdrant_points),
            document_ids=document_ids,
            points=point_details,
            collection_name=col_name,
            message=f"Successfully chunked and stored {len(qdrant_points)} vector point(s) in Qdrant collection '{col_name}'.",
            metadata=request.metadata or {},
        )
