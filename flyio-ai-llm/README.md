# FlyIO AI/LLM Microservice

`flyio-ai-llm` is the AI/LLM microservice for the FlyIO travel planning platform. It exposes two APIs — **generate a travel plan** and **store new knowledge** — backed by Qdrant vector search and a pluggable LLM/embedding provider layer.

## What's done

- **`POST /v1/api/generate`** — takes a prompt, searches Qdrant, and returns either a structured AI-generated travel plan or a signal that more source data is needed.
- **`POST /v1/api/store`** — ingests document text (including already-chunked scraper content) into Qdrant for future retrieval.
- Real AI providers wired in and verified — Groq (LLM) and a free local embedding model — not just mocks.
- Service-to-service authentication (`X-Service-API-Key`) on every `/v1/*` route.
- Cross-service event tracking in a shared PostgreSQL database.
- Health checks (`/health`, `/health/qdrant`, `/health/postgres`), structured JSON logging, automated tests, and CI.
- Live-verified against real infrastructure (real Qdrant, the shared Postgres, real LLM/embedding APIs), not just mocked tests.

## Quick start

```bash
cp .env.example .env
docker-compose up --build
curl http://localhost:8000/health
```

See [docs/SETUP.md](docs/SETUP.md) for local (non-Docker) setup.

## Documentation

| Doc | For |
|---|---|
| **[CONTRACT.md](CONTRACT.md)** | The integration contract — how `flyio-admin` calls this service |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram, tech stack, project layout |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable |
| [docs/SETUP.md](docs/SETUP.md) | Running locally |
| [docs/LOGGING_AND_TRACKING.md](docs/LOGGING_AND_TRACKING.md) | Correlation IDs, structured logs, Postgres event tracking |
| [docs/TESTING.md](docs/TESTING.md) | Running tests, CI |

Interactive API docs (once running): `http://localhost:8000/docs`

## Testing

```bash
pytest -v
```

No live infrastructure or API keys required — see [docs/TESTING.md](docs/TESTING.md).

## Status

All planned work for this service is complete and merged to `main`. Not yet done: a real end-to-end run with `flyio-admin` and `flyio-scraper-service` together — see [CONTRACT.md](CONTRACT.md) for the contract that integration builds against.
