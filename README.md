# FlyIO — three services

| Service | What it does | Local port |
|---|---|---|
| `flyio-admin` | Admin panel (Express API + React UI) — orchestrates the other two | 3000 (API), 5173 (UI) |
| `flyio-scraper-service` | Finds, crawls and chunks travel pages | 8080 |
| `flyio-ai-llm` | Embeddings, vector store and trip-plan generation | 8000 |

## Getting started (Windows)

Needs **Python 3.11+** (tick "Add python.exe to PATH" when installing) and
**Node.js LTS**.

**1. One-time setup.** From this folder in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -CopyEnvFrom "C:\path\to\your\old\Three repos"
```

`-CopyEnvFrom` reuses the `.env` files from an existing checkout of the three
services; leave it out to start from each service's `.env.example`. The
script:

- installs everything (a Python virtualenv per service, the scraper's
  headless browser, npm packages);
- sets destination search to **Wikimedia** — free, no API key: it searches
  Wikivoyage and Wikipedia;
- points the admin at the local scraper and makes their API keys match;
- gives the admin a database: if `flyio-admin/.env` names none, it is set to
  a local PostgreSQL 16 that `run_all.ps1` starts — bundled through npm, so
  nothing to install;
- flags any setting that still needs a real value;
- finishes with a live search for "Jabalpur" to prove search works.

It is safe to re-run. Any `.env` it changes is backed up as
`.env.bak-<timestamp>`. Add `-SkipInstall` to only re-check configuration.

**2. Start everything:**

```powershell
powershell -ExecutionPolicy Bypass -File .\run_all.ps1
```

Five windows open, a couple of seconds apart — the admin's database first
(when `flyio-admin/.env` points at a local one), then the four services; the
admin waits until the database is ready. Its data is kept in
`flyio-admin/.local-db`, so it survives restarts. Then go to
**http://localhost:5173 → Knowledge Base → By destination**, type a
destination and click **Find sources**.

If a window shows `[error 2147942632 (0x800700e8) when launching …]`, Windows
Terminal failed to open it. Close the windows and run everything in one
window instead — output is prefixed with each service's name, and Ctrl+C
stops them all:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_all.ps1 -OneWindow
```

**Check search on its own**, without starting anything:

```powershell
cd flyio-scraper-service
.\.venv\Scripts\python scripts\try_discovery.py Jabalpur
```

**Check crawling on its own** — fetches, parses and chunks a page exactly as a
scraper job does, and says why if it gets nothing:

```powershell
cd flyio-scraper-service
.\.venv\Scripts\python scripts\try_crawl.py https://en.wikivoyage.org/wiki/Delhi
```

## Destination discovery

Type a destination instead of pasting URLs. The scraper searches Wikivoyage
and Wikipedia, filters and ranks the results, and the admin marks anything
already in the knowledge base. Trusted sources come pre-selected; review and
crawl. See `flyio-scraper-service/README.md` (`POST /scrape/discover`) for how
filtering works and the other search providers available.

## Tests

- Scraper unit tests: `cd flyio-scraper-service; .\.venv\Scripts\python -m pytest`
- End-to-end suites across all three services: `tests/integration/README.md`
