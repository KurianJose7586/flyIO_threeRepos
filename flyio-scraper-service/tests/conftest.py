"""Pytest configuration and shared fixtures."""

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

# Set before any app import — Settings.SERVICE_API_KEY is required (no
# default), and get_settings() is process-wide lru_cached, so this must
# happen before the first import of src.config.settings anywhere.
os.environ["SERVICE_API_KEY"] = "test_service_api_key"

TEST_SERVICE_API_KEY = os.environ["SERVICE_API_KEY"]


@pytest.fixture(scope="session")
def client():
    """TestClient used as a context manager runs the real ASGI lifespan —
    this service's background job worker (src/queue/worker.py) is started
    in lifespan, and jobs never advance past "pending" without it. Unlike
    an ASGITransport-based client (which skips lifespan entirely), this
    fixture exercises the real startup path, matching how flyio-ai-llm's
    own test suite learned this the hard way (see that repo's Phase 0).

    Session-scoped deliberately, not one-per-test: src/queue/worker.py's
    _queue is a module-level asyncio.Queue(), which binds to whichever
    event loop is running when it's first touched. TestClient spins up a
    fresh thread + event loop per instantiation, so a fresh TestClient per
    test would bind that same queue object to a new loop each time,
    breaking every test after the first with "Queue is bound to a
    different event loop" (reproduced while writing these tests). One
    client for the whole session avoids that — and matches how this
    worker was actually designed to run in production: one queue, one
    loop, for the lifetime of the process (see worker.py's own docstring).

    monkeypatch stays function-scoped regardless (a pytest fixture, not
    tied to this one's scope) — mocking src.queue.worker.run_crawl_urls
    etc. per test still isolates correctly across tests sharing this client.

    Sends the correct X-Service-API-Key by default so most tests don't
    need to think about auth — tests that specifically exercise auth
    override the header per-request.
    """
    from src.main import app

    with TestClient(app, headers={"X-Service-API-Key": TEST_SERVICE_API_KEY}) as c:
        yield c


async def wait_for_job(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    """Poll GET /scrape/jobs/{job_id} until it leaves "pending", or raise
    on timeout. Jobs are processed by a background asyncio worker, not
    synchronously within the request — tests need to wait for the result
    rather than assume it's ready immediately after enqueueing.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = client.get(f"/scrape/jobs/{job_id}")
        data = resp.json()
        if data["status"] != "pending":
            return data
        await asyncio.sleep(0.02)
    raise TimeoutError(f"Job {job_id} still pending after {timeout}s")
