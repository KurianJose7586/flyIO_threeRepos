"""Tests for POST /scrape/urls, POST /scrape/sources, GET /scrape/jobs/{id}.

The actual crawl (src/crawler/wrapper.run_crawl_urls / run_crawl_source) is
mocked throughout — these tests are about the API/job-lifecycle contract,
not about crawling for real. worker.py does
`from src.crawler.wrapper import run_crawl_source, run_crawl_urls`, so the
names to patch are src.queue.worker.run_crawl_urls /
src.queue.worker.run_crawl_source — patching src.crawler.wrapper's own
names would not affect worker.py's already-bound references.
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import wait_for_job

SAMPLE_CHUNK = {
    "source_url": "https://example.com/page",
    "page_title": "Example Page",
    "section_path": "Example Page > See",
    "chunk_index": 0,
    "content_text": "Some example content.",
    "content_html": "<p>Some example content.</p>",
}

# What the crawler produces (SAMPLE_CHUNK) is not quite what the API emits:
# ChunkResult derives `url` from source_url and pins `status` to "success" for
# downstream consumers. Keeping the two separate means a test that mocks the
# crawler still asserts against the real serialized response shape.
SAMPLE_CHUNK_SERIALIZED = {
    **SAMPLE_CHUNK,
    "url": SAMPLE_CHUNK["source_url"],
    "status": "success",
}


# ── POST /scrape/urls ─────────────────────────────────────────────────────────

def test_scrape_urls_empty_body_returns_400(client: TestClient):
    """A syntactically valid body carrying no usable URL is a 400 from the
    route's own check, not a 422 from schema validation — `{"urls": []}`
    satisfies ScrapeUrlsRequest, so this exercises the route's guard.
    """
    response = client.post("/scrape/urls", json={"urls": []})
    assert response.status_code == 400


def test_scrape_urls_blank_only_urls_returns_400(client: TestClient):
    """Whitespace-only entries are stripped before the guard runs, so a body
    of nothing but blanks must also be rejected rather than enqueueing a
    job that would crawl an empty list.
    """
    response = client.post("/scrape/urls", json={"urls": ["", "   ", "\n"]})
    assert response.status_code == 400


@pytest.mark.parametrize("bad", ["gorakhpur", "en.wikivoyage.org/wiki/Gorakhpur", "ftp://example.com/x", "https://"])
def test_scrape_urls_non_http_url_returns_400(client: TestClient, bad: str):
    """A bare word or scheme-less URL must be rejected before a job is
    created — the crawler cannot fetch it and used to fail the whole batch.
    """
    response = client.post("/scrape/urls", json={"urls": ["https://example.com/a", bad]})
    assert response.status_code == 400
    assert bad in response.json()["detail"]


@pytest.mark.asyncio
async def test_scrape_urls_success_path_populates_results(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Also covers blank-entry handling in the request body: the route must
    filter blank/whitespace-only entries before they ever reach the crawler.
    """
    async def fake_run_crawl_urls(urls):
        assert urls == ["https://example.com/a", "https://example.com/b"]
        return [SAMPLE_CHUNK]

    monkeypatch.setattr("src.queue.worker.run_crawl_urls", fake_run_crawl_urls)

    response = client.post(
        "/scrape/urls",
        json={"urls": ["https://example.com/a", "", "  ", "https://example.com/b"]},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    job = await wait_for_job(client, job_id)
    assert job["status"] == "success"
    assert job["type"] == "urls"
    assert job["results"] == [SAMPLE_CHUNK_SERIALIZED]
    assert job["error"] is None


@pytest.mark.asyncio
async def test_scrape_urls_failure_path_records_error(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_run_crawl_urls(urls):
        raise RuntimeError("simulated crawl failure")

    monkeypatch.setattr("src.queue.worker.run_crawl_urls", fake_run_crawl_urls)

    response = client.post("/scrape/urls", json={"urls": ["https://example.com/a"]})
    job_id = response.json()["job_id"]

    job = await wait_for_job(client, job_id)
    assert job["status"] == "failed"
    assert job["results"] is None
    assert "simulated crawl failure" in job["error"]


# ── POST /scrape/sources ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scrape_sources_success_path(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_run_crawl_source(source_cfg):
        return [SAMPLE_CHUNK]

    monkeypatch.setattr("src.queue.worker.run_crawl_source", fake_run_crawl_source)

    response = client.post("/scrape/sources")
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    job = await wait_for_job(client, job_id)
    assert job["status"] == "success"
    assert job["type"] == "sources"
    # One chunk per configured default source (6 in legacy_crawler/config.py).
    assert len(job["results"]) == 6


def test_scrape_sources_no_sources_configured_returns_500(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from src.config.settings import Settings

    monkeypatch.setattr(Settings, "get_sources", lambda self: [])
    response = client.post("/scrape/sources")
    assert response.status_code == 500


# ── GET /scrape/jobs/{job_id} ──────────────────────────────────────────────────

def test_get_unknown_job_returns_404(client: TestClient):
    response = client.get("/scrape/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_get_pending_job_before_worker_finishes(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """The job must be immediately visible as 'pending' right after
    enqueueing — before the background worker has had a chance to run.

    Note: TestClient's sync calls run the ASGI app (and therefore the
    worker's asyncio task) on a separate thread with its own event loop —
    an asyncio.Event or similar created in this test's context would not
    be safely signalable across that boundary. A fixed delay avoids the
    cross-loop synchronization problem entirely; it only needs to be long
    enough that the immediate GET below reliably wins the race, which a
    fake (no real I/O) coroutine makes trivial.
    """
    import asyncio as _asyncio

    async def fake_run_crawl_urls(urls):
        await _asyncio.sleep(0.3)
        return [SAMPLE_CHUNK]

    monkeypatch.setattr("src.queue.worker.run_crawl_urls", fake_run_crawl_urls)

    response = client.post("/scrape/urls", json={"urls": ["https://example.com/a"]})
    job_id = response.json()["job_id"]

    status_response = client.get(f"/scrape/jobs/{job_id}")
    assert status_response.json()["status"] == "pending"
