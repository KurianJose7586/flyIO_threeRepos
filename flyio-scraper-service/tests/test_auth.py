"""Tests for ServiceAuthMiddleware (src/middleware/auth.py).

/health is public; every /scrape/* route requires X-Service-API-Key.
"""

import pytest
from fastapi.testclient import TestClient


def test_missing_api_key_returns_401(client: TestClient):
    response = client.post(
        "/scrape/urls", json={"urls": ["https://example.com"]}, headers={"X-Service-API-Key": ""}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing X-Service-API-Key header."}


def test_wrong_api_key_returns_401(client: TestClient):
    response = client.post(
        "/scrape/urls", json={"urls": ["https://example.com"]}, headers={"X-Service-API-Key": "wrong-key"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid service API key."}


def test_correct_api_key_is_accepted(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """The client fixture already sends the correct key by default — this
    is the control case proving a valid key genuinely passes auth.

    run_crawl_urls is mocked purely so this test's job doesn't attempt a
    real crawl4ai fetch. Found the hard way while writing this suite: the
    client fixture is session-scoped (see conftest.py) and the worker
    processes jobs serially, so one real, unmocked job here would clog
    every later test's job behind it in the queue for the rest of the
    session — this test's own concern is auth, not crawl success, exactly
    like every route test in test_scrape_routes.py.
    """
    async def fake_run_crawl_urls(urls):
        return []

    monkeypatch.setattr("src.queue.worker.run_crawl_urls", fake_run_crawl_urls)

    response = client.post("/scrape/urls", json={"urls": ["https://example.com"]})
    assert response.status_code == 202


def test_health_is_public_with_no_key(client: TestClient):
    response = client.get("/health", headers={"X-Service-API-Key": ""})
    assert response.status_code == 200


def test_job_status_route_requires_auth(client: TestClient):
    response = client.get("/scrape/jobs/00000000-0000-0000-0000-000000000000", headers={"X-Service-API-Key": ""})
    assert response.status_code == 401
