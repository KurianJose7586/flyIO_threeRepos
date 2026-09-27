# End-to-end integration tests

Covers the destination-driven ingestion path across all three services:

```
destination -> /scrape/discover -> filter/rank/dedup -> /scrape/urls
            -> crawl4ai -> semantic_parser -> chunker
            -> knowledge_base (Postgres) -> /v1/api/store
```

Only the two **outbound third parties** are stubbed — the search API and the
embedding/vector service. Everything between them is the real code, including
a real headless-Chromium crawl.

Pages are served locally and reached through hostnames mapped in `/etc/hosts`,
so the trusted-domain ranking and the auto-selection rule are genuinely
exercised rather than sidestepped by pointing the crawler at `localhost`
(which would score as an unknown domain and never be auto-selected).

## What is covered

| File | Checks |
|---|---|
| `test_destination_ingestion.py` | 35 — discovery filtering and ranking, auto-crawl selection, chunks reaching Postgres and the vector store, re-run deduplication, the explicit-selection fence, auth and error mapping |
| `test_llm_data_required.py` | 5 — `data_required` → discover → ingest → retry, and that only trusted domains are used on that unattended path |

## Running

Five processes. Ports are hardcoded; adjust in the scripts if they clash.

```bash
# 0. Hostnames for the fixture pages (needs root)
echo "127.0.0.1 en.wikivoyage.org" >> /etc/hosts
echo "127.0.0.1 www.holidify.com"  >> /etc/hosts

# 1. Postgres, and a database for the admin service
#    Point flyio-admin/.env at it (PGPORT etc.) plus:
#      SCRAPER_SERVICE_URL=http://127.0.0.1:8099
#      LLM_SERVICE_URL=http://127.0.0.1:8101

# 2. Fixture pages on :80  (root: it binds a privileged port)
python3 tests/integration/harness/fixture_server.py &

# 3. Vector-store stub on :8101
python3 tests/integration/harness/stub_llm.py &

# 4. Scraper service on :8099, with the search boundary stubbed
cd flyio-scraper-service
SERVICE_API_KEY=live_test_key SEARCH_PROVIDER=mock \
NO_PROXY=localhost,127.0.0.1,en.wikivoyage.org,www.holidify.com \
  .venv/bin/python ../tests/integration/harness/run_scraper_fixture.py &

# 5. Admin on :3100
cd flyio-admin && npx ts-node-dev --transpile-only src/app.ts &

# Run
python3 tests/integration/test_destination_ingestion.py
python3 tests/integration/test_llm_data_required.py
```

Each test truncates nothing on its own: reset between runs with

```sql
TRUNCATE knowledge_base, history, job_events, jobs, prompt_history, request_events
  RESTART IDENTITY CASCADE;
```

and restart `stub_llm.py` (it accumulates calls in memory, and both suites
assert on the call count).

## Note on Playwright

`crawl4ai` drives headless Chromium through Playwright. If Playwright's pinned
browser build is not the one installed on the machine, the crawl fails at
launch with `Executable doesn't exist at .../chrome-headless-shell`. Either
install the matching build, or point `PLAYWRIGHT_BROWSERS_PATH` at a directory
laid out for the expected revision. Do not skip the crawl to work around it —
the crawl is the part these tests exist to prove.
