# flyio-ai-llm — Integration Contract for flyio-admin

**Audience:** Abhinav (`flyio-admin`, and `flyio-scraper-service` for context on the async/sync mismatch below).
**Reflects:** `flyio-ai-llm` @ `main` as of Phase 3 of the AI/LLM implementation plan.
**Machine-readable spec:** [`docs/openapi.json`](docs/openapi.json) (static snapshot) or `GET /openapi.json` on a running instance (always current — prefer this for codegen). Interactive docs at `/docs` (Swagger) and `/redoc`.

This is the one document Admin should build against. If it and the live `/openapi.json` ever disagree, the live spec is correct — this file can go stale; re-export it with:

```bash
curl -s http://<host>:8000/openapi.json -o docs/openapi.json
```

---

## 1. The two endpoints Admin calls

| Endpoint | Purpose |
|---|---|
| `POST /v1/api/generate` | Given a prompt, search Qdrant and either return a generated `TravelPlan`, or tell Admin the data doesn't exist yet (`data_required`) |
| `POST /v1/api/store` | Ingest document text (raw or already scraper-chunked) into Qdrant |

Both live under the `/v1` prefix. `/health*` do not (see §4).

## 2. Auth

Every `/v1/*` request needs a service key:

```http
X-Service-API-Key: <shared secret>
```

Mirrors `flyio-scraper-service`'s own `X-Service-API-Key` convention — same header name, same idea, separate secret (`SERVICE_API_KEY` in each service's own `.env`; the two services do **not** need to share one value, they just need to speak the same header). Missing or wrong key → `401 {"detail": "..."}` (a raw body, not the `ErrorResponse` envelope in §6 — that's deliberate, matching the scraper's own auth response shape). `/health*`, `/docs`, `/redoc`, `/openapi.json` never require it.

## 3. Correlation ID — recommended convention

This service accepts an inbound `X-Request-ID` header on every request (also `X-Correlation-ID` or `request-id`, first one wins) and generates one if none is sent. It's echoed back in the response headers and threaded through every log line and every `request_events` row this service writes to Postgres (see §7).

**Recommendation, not yet enforced:** send Admin's `jobs.id` (UUID) as `X-Request-ID` for any call that originated from a job. This service's `request_events.request_id` is a plain `VARCHAR(64)`, so a UUID fits without a schema change on either side, and it makes `request_events` directly joinable to Admin's `job_events.job_id` for a single request_id trace spanning both services — the cross-service tracking goal in the project context doc. If you'd rather use a different value, this service doesn't care what shape `X-Request-ID` is; it just needs to be stable across the calls that belong to one logical operation.

## 4. Health

```
GET /health              GET /v1/health
GET /health/qdrant        GET /v1/health/qdrant
GET /health/postgres      GET /v1/health/postgres
```

Registered twice (bare and `/v1`-prefixed) — use whichever fits your load balancer / orchestrator config, they're identical. No auth required on any of these. `/health/qdrant` and `/health/postgres` do a real backend connectivity check (not just "is the process up") and return `503` if that specific backend is unreachable — `/health` alone only confirms the process is running.

## 5. `POST /v1/api/store`

### 5a. Simple case — raw text

```json
{
  "text": "Paris is the capital of France...",
  "title": "Paris Travel Guide",
  "destination": "Paris",
  "source_url": "https://example.com/paris-guide"
}
```

This service chunks it (default: 500 chars, 50 overlap — configurable via `chunk_size`/`chunk_overlap`), embeds each chunk, and upserts into Qdrant.

### 5b. Recommended case — forwarding scraper chunks (`pre_chunked: true`)

`flyio-scraper-service`'s `GET /scrape/jobs/{job_id}` returns chunks already semantically sectioned (`ChunkResult`: `source_url`, `page_title`, `section_path`, `chunk_index`, `content_text`, `content_html`). Forward them with `pre_chunked: true` and **minimal renaming** (`content_text` → `text`, everything else is a same-named field):

```json
{
  "pre_chunked": true,
  "documents": [
    {
      "text": "Senso-ji is an ancient Buddhist temple located in Asakusa, founded in 645 AD.",
      "content_html": "<p>Senso-ji is an ancient Buddhist temple located in Asakusa, founded in 645 AD.</p>",
      "page_title": "Tokyo - Wikivoyage",
      "section_path": "Tokyo > See > Historic temples",
      "chunk_index": 0,
      "source_url": "https://en.wikivoyage.org/wiki/Tokyo"
    }
  ]
}
```

Two accommodations exist for callers that don't match this shape exactly, both
added because the mismatch previously passed validation and returned `200`
while doing the opposite of what the caller asked:

- **`"mode": "pre_chunked"`** is accepted as an alias for `pre_chunked: true`
  (and `"auto"` for `false`). An explicit `pre_chunked` in the same request
  wins. An unrecognised `mode` is now a validation error rather than ignored.
- **The chunk fields may be nested inside `metadata`** — `section_path`,
  `chunk_index`, `source_url`, `content_html`, and `title`/`page_title` are
  read from there when absent at the top level. Top level always wins.

Prefer the shape above in new integrations; the aliases exist so an already
deployed caller keeps working, not as a second way to spell this.

**Use `pre_chunked: true` whenever the content came from the scraper.** Without it, this service re-splits already-sectioned text on raw character boundaries, cutting across the scraper's own semantic sections — it works, but throws away real structure and hurts retrieval quality. `pre_chunked` also changes how the point ID is derived: without it, the ID is seeded from the chunk's own text (a re-scrape with different wording mints a new point); with it, the ID is seeded from `(source_url, section_path, chunk_index)`, so **re-scraping the same page section updates that point in place** instead of accumulating near-duplicates on every crawl. This matters directly for your job re-run / re-scrape story — plan on always sending `pre_chunked: true` for scraper-sourced content, not as an occasional flag.

### Response (both cases)

```json
{
  "success": true,
  "request_id": "req_...",
  "status": "stored",
  "stored_count": 2,
  "document_ids": ["<qdrant point uuid>", "..."],
  "collection_name": "flyio_knowledge_base",
  "message": "Successfully chunked and stored 2 vector point(s)..."
}
```

## 6. `POST /v1/api/generate`

```json
{
  "prompt": "Plan a 3-day trip to Paris",
  "metadata": {"source": "admin_panel"}
}
```

Two possible outcomes — **this is the workflow Admin orchestrates around**:

**Data found — a real plan comes back:**
```json
{
  "success": true,
  "status": "data_found",
  "data_found": true,
  "data_required": false,
  "results": [
    {"id": "doc-001", "score": 0.56, "payload": {"title": "Paris Travel Guide"}, "text": "Paris is the capital of France..."}
  ],
  "plan": {
    "title": "3-Day Paris Highlights Itinerary",
    "summary": "A concise Paris trip covering the major landmarks.",
    "destinations": [{"name": "Paris, France", "description": "...", "recommended_duration_days": 3}],
    "attractions": [{"name": "Eiffel Tower", "destination": "Paris, France", "category": "Landmark", "description": "..."}],
    "hotels": [],
    "daily_schedule": [{"day": 1, "title": "Historic Center", "morning": "...", "afternoon": "...", "evening": "..."}],
    "budget": {"currency": "USD", "accommodation_est": "$600", "activities_est": "$200", "food_dining_est": "$300", "total_estimated": "$1,100"},
    "travel_tips": ["Book the Louvre in advance."]
  },
  "message": "Relevant data found (1 matches). Travel plan generated successfully."
}
```
Full `TravelPlan` field reference (all sub-object shapes: `Destination`, `Attraction`, `Hotel`, `DaySchedule`, `BudgetBreakdown`) is in [`docs/openapi.json`](docs/openapi.json) under `components.schemas.TravelPlan`, or `app/schemas/generate.py` in this repo.

**Data missing — Admin's cue to trigger the scrape → store → retry loop:**
```json
{
  "success": true,
  "status": "data_required",
  "data_found": false,
  "data_required": true,
  "results": [],
  "plan": null,
  "message": "Data missing in vector database. Source data extraction / scraping required."
}
```

```
Admin: POST /v1/api/generate
           │
           ▼
   status == "data_required"?
     │                  │
     no                yes
     │                  │
  return plan     Admin -> Scraper -> extraction -> POST /v1/api/store (pre_chunked: true)
                            │
                            ▼
                  Admin retries the original POST /v1/api/generate
```

This service never scrapes anything itself and doesn't know the scraper exists — that whole retry loop is Admin's responsibility, not something to expect from this API.

A third outcome exists: `status: "generation_failed"` (`data_found: true`, `plan: null`) — data existed and was retrieved, but the LLM failed to produce valid structured output even after one internal retry. Treat this as a hard failure for that request, not something to retry against `/v1/api/store` (retrying `/v1/api/store` won't fix an LLM output problem).

## 7. Errors

Every error from a route handler (not the auth middleware — see §2) uses this envelope:

```json
{
  "success": false,
  "request_id": "req_...",
  "error": {"code": "QDRANT_UNAVAILABLE", "message": "...", "details": null}
}
```

Codes worth branching on: `QDRANT_UNAVAILABLE` (503, retry later), `VALIDATION_ERROR` (422, bad payload — won't succeed on retry without fixing the request), `LLM_PROVIDER_ERROR` (503).

## 8. Architectural note: this service is synchronous; the scraper is async

`flyio-scraper-service` is job-based: `POST /scrape/urls` returns `202 {job_id}` immediately, and you poll `GET /scrape/jobs/{job_id}` until it's done. **This service is not** — both `/v1/api/generate` and `/v1/api/store` block until the work is finished and return a normal `200`/`503`, no job/polling model at all. A real LLM completion (Groq or OpenAI) can take several seconds; plan Admin's HTTP client timeout accordingly (10s+ recommended) rather than assuming a fast response.

Bridging these two different execution models — "wait for this job, then call that synchronous endpoint" — is entirely Admin's job. Neither this service nor the scraper is aware the other exists.

## 9. Retrieval quality note

`QDRANT_SEARCH_SCORE_THRESHOLD` (what counts as "found" in `/v1/api/generate`) is tuned per embedding provider — the default (`0.45`) assumes the free local embedding model this service runs by default. If this deployment is ever switched to `EMBEDDING_PROVIDER=openai`, that threshold should move back up toward `0.70` (documented in `.env.example`) — OpenAI's embeddings report meaningfully higher absolute cosine similarity for the same relevant pairs, so the same threshold that's well-tuned for one provider is wrong for the other. Not something Admin needs to act on, but worth knowing if `data_required` starts showing up for content you know was stored.
