"""Compatibility tests for the exact request body flyio-admin sends to
POST /v1/api/store.

Admin builds this body in two places:
  - src/services/llmClient.ts  storeDocuments()        -> {request_id, documents, mode}
  - src/services/kbToLlmStore.ts prepareDocumentsFromKB() -> documents[].metadata
    carrying {source_url, title, section_path, chunk_index}

Both diverge from CONTRACT.md section 5b, and both diverged *silently*: the
request validated, returned 200, and reported a plausible stored_count while
doing the opposite of what Admin asked for. `mode` was dropped as an unknown
key so pre_chunked stayed False and scraper chunks were re-split at 500 chars;
the nested chunk fields were never read, so point IDs fell back to being seeded
from chunk text and every re-scrape accumulated near-duplicates instead of
updating in place.

These tests pin the accommodation so a future schema change can't quietly
re-break a deployed caller. The payloads below are copied from Admin's source,
not paraphrased — that is the point of the file.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.store import StoreDocumentItem, StoreRequest


# Verbatim shape of llmClient.storeDocuments() + prepareDocumentsFromKB().
def _admin_store_body() -> dict:
    return {
        "request_id": "req_admin_1",
        "documents": [
            {
                "text": "Kiyomizu-dera is a Buddhist temple in Kyoto, founded in 778.",
                "metadata": {
                    "source_url": "https://en.wikivoyage.org/wiki/Kyoto",
                    "title": "Kyoto - Wikivoyage",
                    "section_path": "Kyoto > See > Temples",
                    "chunk_index": 3,
                },
                "source_url": "https://en.wikivoyage.org/wiki/Kyoto",
            }
        ],
        "mode": "pre_chunked",
    }


# --- 1. `mode` is honoured as an alias for `pre_chunked` ---

def test_admin_mode_string_enables_prechunked():
    """The regression that mattered: mode='pre_chunked' must actually turn on
    pre_chunked. Previously this parsed fine and left it False.
    """
    req = StoreRequest.model_validate(_admin_store_body())
    assert req.pre_chunked is True


def test_mode_auto_maps_to_false():
    req = StoreRequest.model_validate({"text": "hello", "mode": "auto"})
    assert req.pre_chunked is False


def test_mode_is_case_and_whitespace_tolerant():
    req = StoreRequest.model_validate({"text": "hello", "mode": "  Pre_Chunked "})
    assert req.pre_chunked is True


def test_explicit_boolean_wins_over_mode():
    """A caller sending both means the boolean. `mode` must never override an
    explicitly-set pre_chunked, or the alias becomes a second source of truth.
    """
    req = StoreRequest.model_validate(
        {"text": "hello", "mode": "pre_chunked", "pre_chunked": False}
    )
    assert req.pre_chunked is False


def test_unknown_mode_is_rejected_not_ignored():
    """Silently ignoring an unrecognised mode is the exact failure this whole
    validator exists to eliminate — a typo must fail loudly, not degrade.
    """
    with pytest.raises(ValidationError) as exc:
        StoreRequest.model_validate({"text": "hello", "mode": "prechunked"})
    assert "Unsupported mode" in str(exc.value)


def test_omitting_mode_leaves_prechunked_default():
    req = StoreRequest.model_validate({"text": "hello"})
    assert req.mode is None
    assert req.pre_chunked is False


# --- 2. chunk fields nested in `metadata` are hoisted ---

def test_chunk_fields_are_read_from_nested_metadata():
    doc = StoreRequest.model_validate(_admin_store_body()).documents[0]
    assert doc.section_path == "Kyoto > See > Temples"
    assert doc.chunk_index == 3
    assert doc.effective_title == "Kyoto - Wikivoyage"
    assert doc.source_url == "https://en.wikivoyage.org/wiki/Kyoto"


def test_top_level_fields_win_over_metadata():
    """Hoisting only fills gaps. A caller that sets both means the top-level
    value — otherwise metadata could silently rewrite an explicit field.
    """
    doc = StoreDocumentItem.model_validate(
        {
            "text": "t",
            "section_path": "Explicit > Path",
            "chunk_index": 1,
            "metadata": {"section_path": "Nested > Path", "chunk_index": 99},
        }
    )
    assert doc.section_path == "Explicit > Path"
    assert doc.chunk_index == 1


def test_stringified_chunk_index_in_metadata_is_coerced():
    """Assignment during hoisting bypasses field validation, so a JSON caller
    that stringified the number must not leave a str where an int is expected.
    """
    doc = StoreDocumentItem.model_validate(
        {"text": "t", "metadata": {"chunk_index": "7"}}
    )
    assert doc.chunk_index == 7


@pytest.mark.parametrize("bad", ["not-a-number", -1, None, {}])
def test_unusable_metadata_chunk_index_falls_back_to_none(bad):
    """An unusable value must degrade to the normal positional index, which is
    what would have happened had it never been sent — not raise on a field the
    caller was not required to provide in the first place.
    """
    doc = StoreDocumentItem.model_validate({"text": "t", "metadata": {"chunk_index": bad}})
    assert doc.chunk_index is None


def test_hoisting_does_not_disturb_documents_without_metadata():
    doc = StoreDocumentItem.model_validate({"text": "t"})
    assert doc.section_path is None
    assert doc.chunk_index is None
    assert doc.metadata == {}


# --- 3. end-to-end: the payoff is a stable point ID across re-scrapes ---

@pytest.mark.asyncio
async def test_admin_payload_updates_in_place_across_rescrapes():
    """The whole reason pre_chunked matters to Admin's pipeline.

    Admin re-pushes a source_url's chunks after every crawl (pushToLlmStore is
    called on each scrape completion). With the old behaviour the point ID was
    seeded from chunk text, so re-crawling a page whose wording changed at all
    left the old vector behind and added a new one. This asserts the corrected
    path: same (source_url, section_path, chunk_index) -> same point, updated.
    """
    from qdrant_client import AsyncQdrantClient

    from app.services.qdrant.service import QdrantService
    from app.services.store_service import StoreService, generate_prechunked_point_id

    settings = Settings(QDRANT_COLLECTION_NAME="admin_compat_test")
    client = AsyncQdrantClient(":memory:")
    qdrant_svc = QdrantService(client=client, settings=settings)
    await qdrant_svc.ensure_collection("admin_compat_test")
    service = StoreService(qdrant_service=qdrant_svc, settings=settings)

    body = _admin_store_body()
    resp1 = await service.process_store_request(
        StoreRequest.model_validate(body), request_id="req_admin_1"
    )
    assert resp1.stored_count == 1

    # The ID must be the pre_chunked scheme, not the text-seeded fallback.
    assert resp1.document_ids[0] == generate_prechunked_point_id(
        "https://en.wikivoyage.org/wiki/Kyoto", "Kyoto > See > Temples", 3
    )

    # Re-scrape: same section, reworded content, same Admin-shaped body.
    body2 = _admin_store_body()
    body2["documents"][0]["text"] = "Kiyomizu-dera, founded in 778, overlooks eastern Kyoto."
    resp2 = await service.process_store_request(
        StoreRequest.model_validate(body2), request_id="req_admin_2"
    )

    assert resp2.document_ids[0] == resp1.document_ids[0]
    info = await client.get_collection("admin_compat_test")
    assert info.points_count == 1, "re-scrape created a duplicate instead of updating"

    retrieved = await client.retrieve("admin_compat_test", ids=[resp1.document_ids[0]])
    assert "overlooks eastern Kyoto" in retrieved[0].payload["text"]


@pytest.mark.asyncio
async def test_admin_payload_is_not_resplit():
    """pre_chunked's other guarantee: one document in, one point out. A long
    scraper section must survive as a single chunk rather than being cut at
    chunk_size into fragments that straddle the scraper's own boundaries.
    """
    from qdrant_client import AsyncQdrantClient

    from app.services.qdrant.service import QdrantService
    from app.services.store_service import StoreService

    settings = Settings(QDRANT_COLLECTION_NAME="admin_nosplit_test")
    client = AsyncQdrantClient(":memory:")
    qdrant_svc = QdrantService(client=client, settings=settings)
    await qdrant_svc.ensure_collection("admin_nosplit_test")
    service = StoreService(qdrant_service=qdrant_svc, settings=settings)

    body = _admin_store_body()
    # Comfortably longer than the 500-char default chunk_size.
    body["documents"][0]["text"] = "Kyoto has many temples. " * 80

    resp = await service.process_store_request(
        StoreRequest.model_validate(body), request_id="req_admin_nosplit"
    )
    assert resp.stored_count == 1, "pre_chunked document was re-split"
