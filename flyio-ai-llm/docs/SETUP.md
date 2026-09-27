# Local Setup & Execution

## Prerequisites

- Python 3.12+
- Docker & Docker Compose (for local Qdrant / Postgres)

## Option A — Docker Compose (recommended, runs everything)

```bash
docker-compose up --build
```

Starts the API, Qdrant, and PostgreSQL together. Service available at `http://localhost:8000`.

## Option B — Run locally with Python

```bash
pip install -r requirements.txt

# Start Qdrant in a container
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest

# Start the API
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Verify it's up

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/qdrant
curl http://localhost:8000/health/postgres
```

Interactive API docs: `http://localhost:8000/docs` (Swagger) or `/redoc`.

See [CONFIGURATION.md](CONFIGURATION.md) for environment variables, and [../CONTRACT.md](../CONTRACT.md) for the actual API contract.
