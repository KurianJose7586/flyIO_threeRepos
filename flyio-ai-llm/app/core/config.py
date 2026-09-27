"""Application settings and environment configuration."""

from functools import lru_cache
from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration loaded from environment variables."""

    # Project metadata
    PROJECT_NAME: str = "flyio-ai-llm"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/v1"
    ENVIRONMENT: Literal["development", "staging", "production", "testing"] = "development"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    # "json": one JSON object per line — what log aggregators (CloudWatch,
    # Datadog, ELK) expect, and what makes cross-service request_id tracing
    # (FlyIO_Project_Context.md section 4) actually queryable instead of
    # grep-only. "text": the original single-line key=value format, kept for
    # a more readable local terminal during development.
    LOG_FORMAT: Literal["json", "text"] = "json"

    # Service-to-service auth — shared secret Admin sends in the
    # X-Service-API-Key header (see app/middlewares/service_auth.py).
    # Mirrors flyio-scraper-service's SERVICE_API_KEY convention. Empty by
    # default, which means the auth middleware rejects every /v1/* request
    # (fails closed) until an operator explicitly sets a real key.
    SERVICE_API_KEY: str = ""

    # LLM Provider Configuration
    # "groq" reuses the OpenAI-compatible client (app/services/llm/openai_provider.py)
    # pointed at Groq's API — set LLM_API_KEY to a Groq key and LLM_MODEL to a
    # Groq model (e.g. "openai/gpt-oss-120b") when using it.
    LLM_PROVIDER: str = "mock"  # "mock" | "openai" | "groq"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"

    # Embedding Provider Configuration
    # "local" runs a model on-box via fastembed (ONNX runtime) — no API key,
    # no network call, no cost. Set EMBEDDING_MODEL to a fastembed-supported
    # model id (default: "sentence-transformers/all-MiniLM-L6-v2") and
    # EMBEDDING_DIMENSION to match its output size (384 for that model — NOT
    # the OpenAI-sized default below) when using it.
    EMBEDDING_PROVIDER: str = "mock"  # "mock" | "openai" | "local"
    EMBEDDING_API_KEY: str = ""
    # Defaults target the local provider, which is what this service actually
    # runs on: BAAI/bge-base-en-v1.5 is 768-dim, free, offline, and needs no
    # torch (ONNX via fastembed). If you switch EMBEDDING_PROVIDER=openai,
    # set EMBEDDING_MODEL="text-embedding-3-small" and EMBEDDING_DIMENSION=1536.
    # EMBEDDING_DIMENSION must always match the model's real output size AND
    # the Qdrant collection's configured vector size — a mismatch is rejected
    # by Qdrant at write time ("expected dim: X, got Y").
    EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"
    EMBEDDING_DIMENSION: int = 768

    # How many texts the local (fastembed/ONNX) provider encodes per forward
    # pass. fastembed's own default is 256, which puts a whole store request in
    # a single ONNX batch padded to the longest document in it — peak memory
    # scales with batch_size * longest_sequence, not with the average. Storing
    # one scraped page (28 chunks, longest ~4k chars) that way measured 155s
    # and then failed outright with an onnxruntime "bad allocation", so the
    # cost is not just latency: it is an OOM on a small VM.
    #
    # A small batch bounds that working set and keeps padding local to a few
    # similar documents. Only used by EMBEDDING_PROVIDER=local.
    EMBEDDING_BATCH_SIZE: int = 8

    # Batch limits for POST /v1/api/store — a single request with no cap on
    # document count or combined text size could exhaust memory building the
    # embedding batch, or blow an API-metered embedding provider's per-call
    # cost/payload limits in one shot. See StoreService.process_store_request.
    STORE_MAX_DOCUMENTS: int = 100
    STORE_MAX_TOTAL_CHARS: int = 500_000

    # Qdrant Vector DB Configuration
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_COLLECTION_NAME: str = "flyio_knowledge_base"
    # 0.70 was tuned around OpenAI embeddings, which tend to report higher
    # absolute cosine similarity for related query/passage pairs. Measured
    # directly against the default local (fastembed all-MiniLM-L6-v2)
    # provider: a genuinely relevant query/passage pair scores ~0.54 — 0.70
    # would silently return data_required for almost every real query.
    # Raise back toward 0.70 for tighter precision if EMBEDDING_PROVIDER=openai.
    QDRANT_SEARCH_SCORE_THRESHOLD: float = 0.45
    QDRANT_SEARCH_LIMIT: int = 5
    QDRANT_TIMEOUT: float = 5.0

    # Prompt Builder Configuration
    PROMPT_CONTEXT_MAX_RESULTS: int = 2
    # Hard character budget for the retrieved context block, on top of the
    # result-count cap above. Count alone is not a bound on size: real scraped
    # chunks run up to ~1800 chars each (flyio-scraper-service's
    # MAX_CHUNK_CHARS), so 5 results plus the schema-heavy system prompt
    # measured ~14k tokens against real Wikivoyage content and was rejected
    # outright by the provider ("Request too large ... Limit 8000, Requested
    # 14231"). Every provider has a context/rate limit; bounding by count only
    # meant the real ceiling was whatever the retrieved documents happened to
    # be. ~12000 chars is roughly 3-4k tokens, leaving comfortable room for the
    # system prompt, the user prompt, and the model's own response.
    PROMPT_CONTEXT_MAX_CHARS: int = 12000

    # PostgreSQL Database Event Tracking Configuration
    #
    # No credential default on purpose: this service is expected to point at a
    # real, sometimes shared, database (see FlyIO_Project_Context.md section 4).
    # A previous default of postgresql://postgres:postgres@localhost:5432/flyio_ai
    # meant an environment that simply forgot to set DATABASE_URL would silently
    # try to connect to *something* on localhost instead of cleanly no-opping —
    # DatabaseManager/TrackingService already treat an empty DATABASE_URL as
    # "tracking disabled" (fail-safe), so None is the correct default, not a
    # placeholder credential.
    DATABASE_ENABLED: bool = True
    DATABASE_URL: Optional[str] = None


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
