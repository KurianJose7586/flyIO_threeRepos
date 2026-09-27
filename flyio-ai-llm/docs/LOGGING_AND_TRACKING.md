# Logging & Cross-Service Event Tracking

## Correlation ID

Every request accepts or generates a `request_id` (e.g. `req_abc123456789`), propagated via Python `contextvars`, echoed in the `X-Request-ID` response header, and attached to every log line and every `request_events` row this service writes.

**Convention for Admin:** send Admin's `jobs.id` UUID as `X-Request-ID` for any call tied to a job — see [CONTRACT.md §3](../CONTRACT.md) for why.

## Structured logging

Default format is one JSON object per line (`LOG_FORMAT=json`):

```json
{"timestamp": "2026-08-15T04:14:00.123Z", "level": "INFO", "service": "flyio-ai-llm", "request_id": "req_12345", "event": "qdrant_search_started", "message": "Executing vector search"}
```

Set `LOG_FORMAT=text` for a more readable single-line format during local development:

```text
2026-08-15T04:14:00.123456+00:00 [INFO] [flyio-ai-llm] request_id=req_12345 event=qdrant_search_started message=Executing vector search
```

Exceptions (`logger.exception(...)`) include the full traceback in both formats.

## PostgreSQL event tracking

Durable, non-blocking lifecycle events, powered by `asyncpg` and the `request_events` table (auto-created on startup — see `app/db/init.sql`):

```sql
CREATE TABLE IF NOT EXISTS request_events (
    id BIGSERIAL PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    service VARCHAR(32) NOT NULL DEFAULT 'flyio-ai-llm',
    event_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'info',
    message TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- **`service` column** — identifies which of the three FlyIO microservices wrote the row, so a single `request_id`'s rows are traceable across all three even though they share one physical database.
- **Fire-and-forget** — events are scheduled as background tasks via `TrackingService`; a database outage never blocks or fails an API response (checked separately at `GET /health/postgres`).
