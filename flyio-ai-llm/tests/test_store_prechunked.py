"""Tests for StoreRequest.pre_chunked — the Phase 3 contract alignment with
flyio-scraper-service's chunk output shape (GET /scrape/jobs/{job_id} ->
ChunkResult: source_url, page_title, section_path, chunk_index, content_text,
content_html). See app/schemas/store.py and app/services/store_service.py.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.schemas.store import StoreDocumentItem, StoreRequest
from app.services.store_service import StoreService, generate_prechunked_point_id


# --- 1. generate_prechunked_point_id ---

def test_prechunked_point_id_is_deterministic():
    id1 = generate_prechunked_point_id("https://en.wikivoyage.org/wiki/Tokyo", "Tokyo > See > Historic temples", 0)
    id2 = generate_prechunked_point_id("https://en.wikivoyage.org/wiki/Tokyo", "Tokyo > See > Historic temples", 0)
    assert id1 == id2


def test_prechunked_point_id_is_insensitive_to_chunk_text():
    """The whole point of this ID scheme: re-scraping the same page section
    with slightly different wording must update the same point, not create a
    near-duplicate under a new ID. generate_deterministic_point_id (the
    original scheme) does NOT have this property — it's seeded from the text
    itself — which is exactly why pre_chunked mode uses a different function.
    """
    id1 = generate_prechunked_point_id("https://example.com/paris", "Paris > See", 0)
    id2 = generate_prechunked_point_id("https://example.com/paris", "Paris > See", 0)
    assert id1 == id2  # same key, would hold even if text differed


def test_prechunked_point_id_changes_with_any_key_component():
    base = generate_prechunked_point_id("https://example.com/a", "Section A", 0)
    diff_url = generate_prechunked_point_id("https://example.com/b", "Section A", 0)
    diff_section = generate_prechunked_point_id("https://example.com/a", "Section B", 0)
    diff_index = generate_prechunked_point_id("https://example.com/a", "Section A", 1)
    assert len({base, diff_url, diff_section, diff_index}) == 4


# --- 2. StoreService.process_store_request(pre_chunked=True) ---

def _scraper_style_items() -> list[StoreDocumentItem]:
    """Mirrors flyio-scraper-service's actual ChunkResult example values
    (src/schemas/models.py) as closely as possible — this is what Admin
    would forward with minimal transformation.
    """
    return [
        StoreDocumentItem(
            text="Senso-ji is an ancient Buddhist temple located in Asakusa, founded in 645 AD.",
            content_html="<p>Senso-ji is an ancient Buddhist temple located in Asakusa, founded in 645 AD.</p>",
            page_title="Tokyo - Wikivoyage",
            section_path="Tokyo > See > Historic temples",
            chunk_index=0,
            source_url="https://en.wikivoyage.org/wiki/Tokyo",
        ),
        StoreDocumentItem(
            text="The Meiji Shrine is dedicated to Emperor Meiji and Empress Shoken.",
            content_html="<p>The Meiji Shrine is dedicated to Emperor Meiji and Empress Shoken.</p>",
            page_title="Tokyo - Wikivoyage",
            section_path="Tokyo > See > Shrines",
            chunk_index=1,
            source_url="https://en.wikivoyage.org/wiki/Tokyo",
        ),
    ]


@pytest.mark.asyncio
async def test_prechunked_mode_does_not_resplit_long_text():
    """A single item's text longer than chunk_size must still become exactly
    one point in pre_chunked mode — re-splitting it would cut across the
    scraper's own semantic boundary.
    """
    mock_qdrant_svc = AsyncMock()
    mock_qdrant_svc.upsert_points.return_value = True
    service = StoreService(qdrant_service=mock_qdrant_svc)

    long_text = "Historic temple details. " * 40  # well over chunk_size=500
    assert len(long_text) > 500

    req = StoreRequest(
        documents=[
            StoreDocumentItem(
                text=long_text,
                section_path="Tokyo > See > Historic temples",
                chunk_index=0,
                source_url="https://en.wikivoyage.org/wiki/Tokyo",
            )
        ],
        pre_chunked=True,
        chunk_size=500,  # would force multiple chunks if this were honored
    )

    resp = await service.process_store_request(req, request_id="req_prechunk_1")
    assert resp.stored_count == 1
    assert resp.points[0].total_chunks == 1
    assert resp.points[0].text_snippet.startswith("Historic temple details.")


@pytest.mark.asyncio
async def test_prechunked_mode_preserves_scraper_chunk_index_and_total_chunks():
    """Two items sharing a source_url must both land as points, with
    chunk_index taken verbatim from the scraper's own field and total_chunks
    reflecting the sibling group size (2), not a per-item re-split count.
    """
    mock_qdrant_svc = AsyncMock()
    mock_qdrant_svc.upsert_points.return_value = True
    service = StoreService(qdrant_service=mock_qdrant_svc)

    req = StoreRequest(documents=_scraper_style_items(), pre_chunked=True)
    resp = await service.process_store_request(req, request_id="req_prechunk_2")

    assert resp.stored_count == 2
    assert {p.chunk_index for p in resp.points} == {0, 1}
    assert all(p.total_chunks == 2 for p in resp.points)


@pytest.mark.asyncio
async def test_prechunked_mode_payload_carries_scraper_fields():
    """section_path, content_html, and page_title (via effective_title) must
    reach the stored Qdrant payload — this is the actual contract-alignment
    fix, not just the ID scheme.
    """
    mock_qdrant_svc = AsyncMock()
    captured_points = {}

    async def _capture_upsert(points, collection_name):
        captured_points["points"] = points
        return True

    mock_qdrant_svc.upsert_points.side_effect = _capture_upsert
    service = StoreService(qdrant_service=mock_qdrant_svc)

    req = StoreRequest(documents=[_scraper_style_items()[0]], pre_chunked=True)
    await service.process_store_request(req, request_id="req_prechunk_3")

    payload = captured_points["points"][0]["payload"]
    assert payload["section_path"] == "Tokyo > See > Historic temples"
    assert payload["content_html"] == "<p>Senso-ji is an ancient Buddhist temple located in Asakusa, founded in 645 AD.</p>"
    assert payload["title"] == "Tokyo - Wikivoyage"  # via effective_title (page_title fallback)
    assert payload["chunk_index"] == 0
    # Stored text stays clean — no section_path prefix baked in (see next test
    # for where that prefix actually goes: the embedding input, not storage).
    assert payload["text"] == "Senso-ji is an ancient Buddhist temple located in Asakusa, founded in 645 AD."


@pytest.mark.asyncio
async def test_prechunked_mode_embeds_section_path_but_stores_clean_text():
    """section_path must be prepended to what's embedded (real retrieval
    signal) but NOT to what's stored as payload text (so prompt context
    built from it doesn't carry the breadcrumb as visible noise).
    """
    mock_qdrant_svc = AsyncMock()
    mock_qdrant_svc.upsert_points.return_value = True

    mock_embedding_svc = AsyncMock()
    mock_embedding_svc.embed_batch.return_value = [[0.1] * 1536]

    service = StoreService(qdrant_service=mock_qdrant_svc, embedding_service=mock_embedding_svc)

    req = StoreRequest(documents=[_scraper_style_items()[0]], pre_chunked=True)
    await service.process_store_request(req, request_id="req_prechunk_4")

    embedded_texts = mock_embedding_svc.embed_batch.call_args[0][0]
    assert len(embedded_texts) == 1
    assert embedded_texts[0].startswith("Tokyo > See > Historic temples\n\n")
    assert "Senso-ji is an ancient Buddhist temple" in embedded_texts[0]


@pytest.mark.asyncio
async def test_prechunked_mode_updates_same_point_when_text_changes():
    """The actual point of the (source_url, section_path, chunk_index) ID
    scheme: re-scraping the same section with different wording must
    overwrite the same point, not create a second one — verified against a
    real in-memory Qdrant, not just by comparing generated ID strings.
    """
    from qdrant_client import AsyncQdrantClient

    from app.services.qdrant.service import QdrantService

    settings = Settings(QDRANT_COLLECTION_NAME="prechunk_update_test")
    client = AsyncQdrantClient(":memory:")
    qdrant_svc = QdrantService(client=client, settings=settings)
    await qdrant_svc.ensure_collection("prechunk_update_test")

    service = StoreService(qdrant_service=qdrant_svc, settings=settings)

    item = StoreDocumentItem(
        text="Senso-ji is an ancient temple in Asakusa.",
        section_path="Tokyo > See > Historic temples",
        chunk_index=0,
        source_url="https://en.wikivoyage.org/wiki/Tokyo",
    )
    resp1 = await service.process_store_request(
        StoreRequest(documents=[item], pre_chunked=True), request_id="req_update_1"
    )
    assert resp1.stored_count == 1
    point_id = resp1.document_ids[0]

    col_info1 = await client.get_collection("prechunk_update_test")
    assert col_info1.points_count == 1

    # Re-scrape: same section, different wording.
    updated_item = StoreDocumentItem(
        text="Senso-ji, founded in 645 AD, is Tokyo's oldest Buddhist temple.",
        section_path="Tokyo > See > Historic temples",
        chunk_index=0,
        source_url="https://en.wikivoyage.org/wiki/Tokyo",
    )
    resp2 = await service.process_store_request(
        StoreRequest(documents=[updated_item], pre_chunked=True), request_id="req_update_2"
    )

    assert resp2.document_ids[0] == point_id  # same point, not a new one
    col_info2 = await client.get_collection("prechunk_update_test")
    assert col_info2.points_count == 1  # still one point, not two

    retrieved = await client.retrieve("prechunk_update_test", ids=[point_id])
    assert "founded in 645 AD" in retrieved[0].payload["text"]


@pytest.mark.asyncio
async def test_prechunked_mode_falls_back_to_text_hash_id_without_source_url_or_section_path():
    """A pre_chunked item missing source_url or section_path can't form the
    (source_url, section_path, chunk_index) key — must fall back to the
    original text-hash ID scheme rather than risk a collision (e.g. every
    item with chunk_index=0 and no section_path would otherwise seed the
    same ID).
    """
    mock_qdrant_svc = AsyncMock()
    mock_qdrant_svc.upsert_points.return_value = True
    service = StoreService(qdrant_service=mock_qdrant_svc)

    req = StoreRequest(
        documents=[StoreDocumentItem(text="No section path or source url here.", chunk_index=0)],
        pre_chunked=True,
    )
    resp = await service.process_store_request(req, request_id="req_prechunk_fallback")
    assert resp.stored_count == 1
    # The specific ID value isn't the contract — only that it didn't error
    # out, and that it's stable/deterministic for identical input (checked
    # next), proving the fallback path is real and not accidentally random
    # (e.g. from an unseeded UUID).


@pytest.mark.asyncio
async def test_prechunked_fallback_id_is_stable_for_identical_input():
    """The fallback path (previous test) must be deterministic run-to-run for
    identical input, without hardcoding the exact hash (which depends on
    internal base_doc_id derivation details that aren't part of the public
    contract).
    """
    mock_qdrant_svc = AsyncMock()
    mock_qdrant_svc.upsert_points.return_value = True

    ids = []
    for _ in range(2):
        service = StoreService(qdrant_service=mock_qdrant_svc)
        req = StoreRequest(
            documents=[StoreDocumentItem(text="No section path or source url here.", chunk_index=0)],
            pre_chunked=True,
        )
        resp = await service.process_store_request(req, request_id="req_stable")
        ids.append(resp.document_ids[0])

    assert ids[0] == ids[1]


def test_effective_title_prefers_title_over_page_title():
    both = StoreDocumentItem(text="x", title="Explicit Title", page_title="Scraped Page Title")
    assert both.effective_title == "Explicit Title"

    only_page_title = StoreDocumentItem(text="x", page_title="Scraped Page Title")
    assert only_page_title.effective_title == "Scraped Page Title"

    neither = StoreDocumentItem(text="x")
    assert neither.effective_title is None


# --- explicit total_chunks (batched ingestion) ---

@pytest.mark.asyncio
async def test_prechunked_explicit_total_chunks_survives_batching():
    """A page split across several store requests must not have its
    total_chunks collapse to the size of whichever batch it arrived in.
    Admin batches large pages to stay inside the proxy's read timeout, so
    without an explicit total a 27-chunk page sent as 3 batches of 9 would
    store total_chunks=9 on every point.
    """
    mock_qdrant_svc = AsyncMock()
    mock_qdrant_svc.upsert_points.return_value = True
    service = StoreService(qdrant_service=mock_qdrant_svc)

    # Second batch of a 27-chunk page: only 2 items present in this request.
    batch = [
        StoreDocumentItem(
            text="chunk nine",
            source_url="https://en.wikipedia.org/wiki/Dwarka",
            section_path="Etymology > History",
            chunk_index=9,
            total_chunks=27,
        ),
        StoreDocumentItem(
            text="chunk ten",
            source_url="https://en.wikipedia.org/wiki/Dwarka",
            section_path="Etymology > History",
            chunk_index=10,
            total_chunks=27,
        ),
    ]

    req = StoreRequest(documents=batch, pre_chunked=True)
    resp = await service.process_store_request(req, request_id="req_batch_2_of_3")

    assert resp.stored_count == 2
    assert all(p.total_chunks == 27 for p in resp.points)

    points = mock_qdrant_svc.upsert_points.call_args.kwargs["points"]
    assert all(p["payload"]["total_chunks"] == 27 for p in points)


@pytest.mark.asyncio
async def test_prechunked_total_chunks_falls_back_to_group_size_when_absent():
    """Omitting total_chunks keeps the pre-existing inference, so callers that
    send a whole page in one request are unaffected.
    """
    mock_qdrant_svc = AsyncMock()
    mock_qdrant_svc.upsert_points.return_value = True
    service = StoreService(qdrant_service=mock_qdrant_svc)

    req = StoreRequest(documents=_scraper_style_items(), pre_chunked=True)
    resp = await service.process_store_request(req, request_id="req_no_total")

    assert all(p.total_chunks == 2 for p in resp.points)


def test_total_chunks_hoists_from_metadata_and_coerces():
    """Same nested-metadata accommodation as the other chunk fields, including
    a stringified value from a JSON caller.
    """
    item = StoreDocumentItem(text="x", metadata={"total_chunks": "27"})
    assert item.total_chunks == 27

    # An unusable value falls back to None rather than rejecting the document.
    assert StoreDocumentItem(text="x", metadata={"total_chunks": "many"}).total_chunks is None
    assert StoreDocumentItem(text="x", metadata={"total_chunks": 0}).total_chunks is None

    # Top level wins over metadata.
    item = StoreDocumentItem(text="x", total_chunks=27, metadata={"total_chunks": 9})
    assert item.total_chunks == 27
