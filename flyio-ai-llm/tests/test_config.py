"""Tests for application settings and configuration loading."""

import os
from app.core.config import Settings


def test_settings_default_values():
    """Verify default configuration attributes.

    _env_file=None disables .env loading for this test specifically. Settings
    reads .env by default (model_config env_file=".env"), so without this a
    developer's local .env silently decides what "the defaults" are and this
    test asserts their machine's config rather than the code's — which is
    exactly what happened: a local .env with EMBEDDING_DIMENSION=384 made this
    test fail against a code default of 768.
    """
    settings = Settings(_env_file=None)
    assert settings.PROJECT_NAME == "flyio-ai-llm"
    assert settings.VERSION == "0.1.0"
    assert settings.API_V1_STR == "/v1"
    # Defaults target the local (fastembed) provider — BAAI/bge-base-en-v1.5.
    assert settings.EMBEDDING_MODEL == "BAAI/bge-base-en-v1.5"
    assert settings.EMBEDDING_DIMENSION == 768
    assert settings.QDRANT_SEARCH_LIMIT == 5
    assert settings.PROMPT_CONTEXT_MAX_RESULTS == 2
    assert settings.PROMPT_CONTEXT_MAX_CHARS == 12000


def test_settings_env_override(monkeypatch):
    """Verify settings pick up environment variable overrides."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-key-12345")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "custom_collection")
    monkeypatch.setenv("QDRANT_SEARCH_SCORE_THRESHOLD", "0.85")
    monkeypatch.setenv("PROMPT_CONTEXT_MAX_RESULTS", "10")

    settings = Settings()
    assert settings.LLM_PROVIDER == "openai"
    assert settings.LLM_API_KEY == "sk-test-key-12345"
    assert settings.QDRANT_COLLECTION_NAME == "custom_collection"
    assert settings.QDRANT_SEARCH_SCORE_THRESHOLD == 0.85
    assert settings.PROMPT_CONTEXT_MAX_RESULTS == 10
