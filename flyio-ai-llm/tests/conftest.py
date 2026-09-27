"""Pytest configuration and common fixtures."""

import os
from typing import AsyncGenerator
import pytest
from httpx import ASGITransport, AsyncClient

# Set testing environment before importing app modules
os.environ["ENVIRONMENT"] = "testing"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["EMBEDDING_PROVIDER"] = "mock"
os.environ["QDRANT_URL"] = "http://mock-qdrant:6333"
os.environ["QDRANT_COLLECTION_NAME"] = "test_flyio_knowledge_base"
# ServiceAuthMiddleware calls get_settings() directly (not via FastAPI's
# Depends), so it is NOT affected by async_client's
# app.dependency_overrides[get_settings] below — it always sees the real,
# process-wide lru_cached Settings() built from this os.environ block. Must
# be set here, not only on the test_settings fixture object, or the
# middleware fails closed (see service_auth.py) on every /v1/* test request.
os.environ["SERVICE_API_KEY"] = "test_service_api_key"

from app.core.config import Settings, get_settings
from app.main import create_app

# Settings.model_config sets env_file=".env", so a bare Settings() inside a test
# reads the *developer's own* .env from the repo root. That makes results depend
# on local machine config: with EMBEDDING_DIMENSION=384 in .env, tests asserting
# the 1536 default fail on that machine and nowhere else. CI has no .env, so it
# stays green and the breakage looks like a local-only mystery.
#
# Tests must describe the code's behaviour, not the machine's configuration, so
# the whole session ignores .env. Anything a test genuinely needs is set
# explicitly — via the os.environ block above, the test_settings fixture, or
# per-test Settings(...) kwargs.
Settings.model_config["env_file"] = None

# Every test that calls a /v1/* route through async_client (below) or the
# lifespan-aware TestClient in test_logging_lifespan.py must send this same
# value in X-Service-API-Key, or ServiceAuthMiddleware returns 401.
TEST_SERVICE_API_KEY = os.environ["SERVICE_API_KEY"]


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Fixture providing test settings."""
    return Settings(
        ENVIRONMENT="testing",
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
        QDRANT_URL="http://mock-qdrant:6333",
        QDRANT_COLLECTION_NAME="test_flyio_knowledge_base",
        DEBUG=True,
        # DATABASE_URL has no production default (see config.py) — set explicitly
        # here so TrackingService's DATABASE_ENABLED-and-DATABASE_URL gate stays
        # open in tests that exercise the log_event -> _persist_event scheduling
        # path. It's never actually connected to by most tests: log_event fires a
        # real fire-and-forget background task per API call, which — unless a
        # test mocks get_pool/_persist_event — genuinely tries to connect. Use a
        # closed loopback port, not a hostname: a hostname needs DNS resolution
        # per attempt, which measurably slows the suite (dozens of these tasks
        # fire across the endpoint tests); a closed local port fails instantly
        # with connection-refused and no lookup.
        DATABASE_URL="postgresql://test:test@127.0.0.1:1/test_flyio_ai",
    )


@pytest.fixture
async def async_client(test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    """Fixture providing an async HTTP client connected to the FastAPI test app."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: test_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Service-API-Key": TEST_SERVICE_API_KEY},
    ) as client:
        yield client
