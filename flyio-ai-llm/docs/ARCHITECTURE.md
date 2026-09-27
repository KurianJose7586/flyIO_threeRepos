# Architecture

## Where this service sits

```text
Frontend
   ↓
Admin Panel (flyio-admin)
   ↓
LLM API (flyio-ai-llm)  ← this service
   ↓
Qdrant Vector Database
```

## End-to-end workflow

```text
Admin
  ↓
LLM API (POST /v1/api/generate)
  ↓
Qdrant Search
  ├── Data exists  ──→ Generate Plan ──→ Return to Admin
  │
  └── Data missing ──→ Return "data_required" ──→ Admin triggers Scraper
                                                         ↓
                                                 Scraper fetches HTML
                                                         ↓
                                                 Admin extraction
                                                         ↓
                                                 LLM Store API (POST /v1/api/store)
                                                         ↓
                                                 Qdrant ingestion
                                                         ↓
                                                 Admin retries the original generate call
```

See [CONTRACT.md](../CONTRACT.md) for the exact request/response shapes Admin builds against.

## Microservice boundaries

| Microservice | Core Responsibility |
|---|---|
| `flyio-admin` | Frontend-facing APIs, workflow orchestration, scraper triggers, HTML extraction, PostgreSQL tracking. |
| `flyio-scraper-service` | URL fetching, HTTP retries/timeouts, raw HTML extraction. Async job-based (`202 {job_id}` → poll). |
| `flyio-ai-llm` (this service) | LLM APIs, embedding generation, Qdrant vector search/retrieval, storage, AI plan generation. Fully synchronous — no job/polling model. |

## Technology stack

- **FastAPI (Python 3.12+)** — async/await for non-blocking vector DB and LLM calls; Pydantic v2 for validation; auto-generated OpenAPI docs at `/docs`.
- **Qdrant** — vector similarity search with payload filtering.
- **PostgreSQL** (`asyncpg`) — durable, fire-and-forget event tracking shared across all three FlyIO services.
- **LLM / embedding providers** — pluggable: `mock` (deterministic, no network, used in tests), `openai` (real OpenAI API), `groq` (real Groq API via the same OpenAI-compatible client), `local` (fastembed/ONNX, offline, no API key — embeddings only).
- **Pytest** + `pytest-asyncio` + `pytest-mock` — the default suite needs no live infra or API keys; two tests that hit the real Groq API self-skip without a key.

## Project structure

```text
flyio-ai-llm/
├── app/
│   ├── api/v1/
│   │   ├── endpoints/
│   │   │   ├── health.py        # GET /health, /health/qdrant, /health/postgres
│   │   │   ├── generate.py      # POST /v1/api/generate
│   │   │   └── store.py         # POST /v1/api/store
│   │   └── api.py               # v1 router aggregator
│   ├── core/
│   │   ├── config.py            # Environment configuration (Pydantic Settings)
│   │   ├── context.py           # Request contextvars for request_id
│   │   ├── errors.py            # Domain exceptions & error codes
│   │   └── logging.py           # JSON / text structured logging
│   ├── db/session.py            # asyncpg pool + DDL init + health check
│   ├── middlewares/
│   │   ├── request_id.py        # Correlation request_id extractor/generator
│   │   └── service_auth.py      # X-Service-API-Key guard on /v1/*
│   ├── schemas/                 # Pydantic request/response models
│   ├── services/
│   │   ├── embeddings/          # mock / openai / local (fastembed) providers
│   │   ├── llm/                 # mock / openai / groq providers
│   │   ├── qdrant/              # client manager & QdrantService
│   │   ├── store_service.py     # chunking, batch embedding, Qdrant ingestion
│   │   └── tracking_service.py  # PostgreSQL event tracking
│   └── main.py                  # FastAPI app entry point & exception handlers
├── tests/                        # 20 test files, 100+ tests
├── docs/                         # this folder — detailed reference docs
├── CONTRACT.md                   # integration contract for flyio-admin
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── README.md                     # quick overview — start there
```
