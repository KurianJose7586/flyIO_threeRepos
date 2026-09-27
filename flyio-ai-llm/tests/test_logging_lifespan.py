"""Regression tests for structured logging + application lifespan.

The generate/store test suite normally talks to the app via httpx
`ASGITransport`, which never runs FastAPI's `lifespan` context manager.
`setup_logging()` is only ever invoked from `lifespan` (see app/main.py),
so a bug in the logging configuration that only surfaces once
`setup_logging()` has actually run can pass the full test suite while
the deployed service crashes on startup / on the very first request.

These tests close that gap by (1) calling `setup_logging()` directly and
exercising the exact `logger.<level>(..., extra={...})` call shape used
throughout the codebase, and (2) booting the real app through a
lifespan-aware client so `/health` is only considered healthy if startup
genuinely succeeded.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.logging import logger, setup_logging
from app.main import create_app
from app.services.qdrant.service import QdrantService
from tests.conftest import TEST_SERVICE_API_KEY


def test_setup_logging_does_not_collide_with_extra_event_and_request_id():
    """setup_logging() must not install a LogRecord factory/config that
    raises when call sites pass `extra={"event": ..., "request_id": ...}` —
    this is the exact pattern used by every service in this codebase.
    """
    setup_logging("INFO")

    # Every level used across the codebase, with the standard extra shape.
    logger.info("smoke info", extra={"event": "service_startup", "request_id": "req_test"})
    logger.warning("smoke warning", extra={"event": "db_startup_warning", "request_id": "req_test"})
    logger.error("smoke error", extra={"event": "plan_generation_failed", "request_id": "req_test"})

    try:
        raise ValueError("boom")
    except ValueError:
        # logger.exception() is used by the unhandled-exception handler in main.py.
        logger.exception("smoke exception", extra={"event": "unhandled_exception", "request_id": "req_test"})


def test_setup_logging_is_idempotent_across_repeated_app_startups():
    """Lifespan runs setup_logging() on every app startup (e.g. reload,
    repeated TestClient instantiation). Calling it multiple times must not
    accumulate state that causes a later `extra={...}` call to fail.
    """
    for _ in range(3):
        setup_logging("INFO")
    logger.info("repeat smoke", extra={"event": "service_startup", "request_id": "req_test"})


@pytest.fixture
def lifespan_client(monkeypatch: pytest.MonkeyPatch):
    """TestClient used as a context manager runs the real ASGI lifespan
    (startup + shutdown), unlike the `async_client`/`ASGITransport`
    fixture in conftest.py.

    Startup best-effort connects to Postgres and Qdrant. Neither is
    available here and neither is what these tests are about, so both are
    steered to fail immediately rather than slowly: Postgres is switched
    off outright, and ensure_collection() is replaced with a stub that
    raises at once. Letting it fail naturally costs ~3.5s per startup —
    the Qdrant client retries internally and does not honour
    QDRANT_TIMEOUT for connection setup.

    Note this makes startup take the `except` branch, so the fixture also
    covers the qdrant_startup_warning log call — another real
    `extra={"event": ...}` site that the LogRecord collision used to
    crash on.
    """
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    # Closed loopback port: the request-path Qdrant call (not covered by
    # the ensure_collection stub below) then fails with an immediate
    # connection-refused rather than a DNS lookup on `mock-qdrant`.
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:1")

    async def _fail_fast(*args, **kwargs):
        raise ConnectionError("Qdrant unavailable (stubbed in test)")

    monkeypatch.setattr(QdrantService, "ensure_collection", _fail_fast)

    # get_settings() is process-wide lru_cached; force it to re-read the
    # env var we just set instead of reusing whatever another test cached.
    get_settings.cache_clear()
    app = create_app()
    try:
        # ServiceAuthMiddleware guards /v1/api/generate (hit below by
        # test_app_serves_generate_endpoint_through_real_lifespan) — send the
        # same key conftest.py's os.environ block configures, or it 401s.
        with TestClient(app, headers={"X-Service-API-Key": TEST_SERVICE_API_KEY}) as client:
            yield client
    finally:
        get_settings.cache_clear()


def test_app_boots_and_serves_health_through_real_lifespan(lifespan_client: TestClient):
    """End-to-end guard: if lifespan startup raises (as it did when the
    logging record factory collided with `extra={"event": ...}`), FastAPI
    surfaces 'Application startup failed' and no request is ever served.
    """
    response = lifespan_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_app_serves_generate_endpoint_through_real_lifespan(lifespan_client: TestClient):
    """Confirm a real API route also works once startup has genuinely run
    setup_logging() — not just /health.
    """
    response = lifespan_client.post("/v1/api/generate", json={"prompt": "plan a trip"})
    # Qdrant is unreachable in this test environment; the important
    # assertion is that the service responded at all (no crash on the
    # logging calls inside the request path), not the specific outcome.
    assert response.status_code in (200, 503)
