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
| `test_llm_data_required.py` | 10 — `data_required` → discover → ingest → retry, only trusted domains on that unattended path, and provenance in the event log |
| `test_review_regressions.py` | 13 — the four code-review findings: stored-vs-canonical URL dedup, explicit selection not depending on a re-search, `data_required` skipping indexed pages, and input validation |
| `test_ui_skipped.py` | 2 — in a real browser, a "skipped" reply shows the backend's reason and leaves no progress card stuck (run with the scraper venv's Python, which has Playwright) |
| `test_limits.py` | 12 — 40 concurrent discoveries, real crawl throughput, two destinations crawling at once, a dead link (404) not becoming knowledge, dedup against 20,000 knowledge-base rows, and a scraper crash mid-job. Prints its measurements, so a run doubles as a capacity report |

## Running

`harness/up.sh` brings the whole stack up idempotently — hostnames, Postgres,
fixture server, vector-store stub, scraper (search stubbed), admin — and
leaves anything already healthy alone, so it is safe to re-run after a
container restart. `reset` also clears DB rows and stub state.

```bash
# once: flyio-scraper-service/.venv installed, flyio-admin npm-installed,
# and flyio-admin/.env pointing at this stack:
#   PGHOST=127.0.0.1 PGPORT=5433 PGUSER=flyio PGDATABASE=flyio_admin_test
#   SCRAPER_SERVICE_URL=http://127.0.0.1:8099  SCRAPER_SERVICE_API_KEY=live_test_key
#   LLM_SERVICE_URL=http://127.0.0.1:8101      PORT=3100
#   INITIAL_ADMIN_PASSWORD=integration-test-admin-pw
#   DEFAULT_SOURCE_URLS=http://en.wikivoyage.org/wiki/Gorakhpur

sudo tests/integration/harness/up.sh reset && python3 tests/integration/test_destination_ingestion.py
sudo tests/integration/harness/up.sh reset && python3 tests/integration/test_llm_data_required.py
python3 tests/integration/test_review_regressions.py      # resets itself
python3 tests/integration/test_limits.py                  # resets itself; restarts the scraper
```

Needs root: it binds :80 and edits `/etc/hosts`. Logs go to
`/tmp/flyio-integration/`.

## Demo recording

`harness/record_demo.py OUT_DIR` drives the admin UI through the whole flow —
type a destination, review candidates, crawl, re-run to show dedup — and
records it with on-screen captions and a banner stating what is stubbed.
Run it on a reset database; see its docstring for converting to MP4.

## Note on Playwright

`crawl4ai` drives headless Chromium through Playwright. If Playwright's pinned
browser build is not the one installed on the machine, the crawl fails at
launch with `Executable doesn't exist at .../chrome-headless-shell`. Either
install the matching build, or point `PLAYWRIGHT_BROWSERS_PATH` at a directory
laid out for the expected revision. Do not skip the crawl to work around it —
the crawl is the part these tests exist to prove.
