"""Pins the chunk shape that flyio-admin's orchestration actually reads.

flyio-admin decides which source URLs to forward to the LLM Store API with
this filter (flyio-admin/src/routes/llm.ts):

    const successfulUrls = scrapeOutcome.results
      .filter((r) => r.status === "success" && r.url)
      .map((r) => r.url);

    const urlsToStore = successfulUrls.length > 0 ? successfulUrls : targetUrls;

Chunks originally carried neither `status` nor `url`, so that predicate matched
nothing. On the /scrape/urls path Admin silently fell through to `targetUrls`
and still worked. On the /scrape/sources path there are no targetUrls, so
`urlsToStore` was empty and Admin stored nothing at all — a crawl that reported
success while ingesting zero documents, raising no error at any layer.

These tests assert against the predicate itself rather than the field list, so
they fail if the shape Admin depends on regresses.
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import wait_for_job

CHUNK_FROM_CRAWLER = {
    "source_url": "https://en.wikivoyage.org/wiki/Kyoto",
    "page_title": "Kyoto - Wikivoyage",
    "section_path": "Kyoto > See > Temples",
    "chunk_index": 0,
    "content_text": "Kiyomizu-dera is a Buddhist temple founded in 778.",
    "content_html": "<p>Kiyomizu-dera is a Buddhist temple founded in 778.</p>",
}


def _admin_successful_urls(results: list[dict]) -> list[str]:
    """Python transcription of Admin's filter, kept deliberately literal."""
    return [r["url"] for r in results if r.get("status") == "success" and r.get("url")]


@pytest.mark.asyncio
async def test_admin_filter_selects_urls_from_job_results(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """The regression that mattered: Admin's predicate must select the URL."""

    async def fake_run_crawl_urls(urls):
        return [CHUNK_FROM_CRAWLER]

    monkeypatch.setattr("src.queue.worker.run_crawl_urls", fake_run_crawl_urls)

    response = client.post(
        "/scrape/urls", json={"urls": ["https://en.wikivoyage.org/wiki/Kyoto"]}
    )
    job = await wait_for_job(client, response.json()["job_id"])

    assert job["status"] == "success"
    assert _admin_successful_urls(job["results"]) == [
        "https://en.wikivoyage.org/wiki/Kyoto"
    ]


@pytest.mark.asyncio
async def test_sources_job_results_are_selectable_by_admin(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """The path where the old shape actually broke ingestion.

    /scrape/sources is triggered with no caller-supplied URLs, so Admin has no
    `targetUrls` fallback — if the filter yields nothing here, nothing is ever
    pushed to the vector store.
    """

    async def fake_run_crawl_source():
        return [
            CHUNK_FROM_CRAWLER,
            {**CHUNK_FROM_CRAWLER, "chunk_index": 1, "content_text": "Another section."},
        ]

    async def fake_run_all_sources(*args, **kwargs):
        return await fake_run_crawl_source()

    monkeypatch.setattr("src.queue.worker.run_crawl_source", fake_run_all_sources)

    response = client.post("/scrape/sources")
    assert response.status_code == 202
    job = await wait_for_job(client, response.json()["job_id"])

    assert job["status"] == "success"
    selected = _admin_successful_urls(job["results"])
    assert selected, "Admin's filter matched nothing — ingestion would silently store zero documents"
    assert set(selected) == {"https://en.wikivoyage.org/wiki/Kyoto"}


@pytest.mark.asyncio
async def test_url_mirrors_source_url_and_does_not_replace_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """`url` is additive. Consumers keyed on source_url (flyio-ai-llm's Store
    API among them) must be unaffected by its presence.
    """

    async def fake_run_crawl_urls(urls):
        return [CHUNK_FROM_CRAWLER]

    monkeypatch.setattr("src.queue.worker.run_crawl_urls", fake_run_crawl_urls)

    response = client.post(
        "/scrape/urls", json={"urls": ["https://en.wikivoyage.org/wiki/Kyoto"]}
    )
    job = await wait_for_job(client, response.json()["job_id"])

    chunk = job["results"][0]
    assert chunk["source_url"] == CHUNK_FROM_CRAWLER["source_url"]
    assert chunk["url"] == chunk["source_url"]
    # Every original field survives unchanged.
    for key, value in CHUNK_FROM_CRAWLER.items():
        assert chunk[key] == value
