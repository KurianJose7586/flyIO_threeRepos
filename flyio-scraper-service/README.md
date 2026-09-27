# flyio-scraper-service

## Jenkins development deployment

Set the Jenkins Pipeline-from-SCM **Script Path** to `JenkinsDev`. The pipeline
uses the existing Secret file credential `env-dev-flyio-scraper-service` as
Docker's runtime `--env-file`; it never copies that file into the checkout or
image. Use Docker env-file syntax: one `KEY=value` per line, no `export`, no
shell interpolation, and no surrounding quotes unless the quotes are part of
the value. `.dockerignore` excludes local `.env` files and Git metadata.

One-time setup:

- Provide a Jenkins agent labelled `docker`, with Docker CLI and Python 3,
  connected to the Docker daemon hosting Nginx Proxy Manager. Use a trusted
  agent for this job because it handles deployment credentials.
- Add a Jenkins **Username with password** credential with ID `NPM_CREDENTIAL`:
  username is the NPM login email, password is the NPM password. Its account
  needs permission to read and update the development proxy host. Override
  the ID with the pipeline's `NPM_CREDENTIAL_ID` parameter if needed.
- Set `DOCKER_NETWORK` to an existing user-defined Docker network attached to
  NPM (default `npm`). The candidate joins that network; NPM forwards to its
  unique container name on port `8080`. No host port is published. This setup
  assumes NPM and the scraper use the same Docker host.
- Create an enabled, dedicated NPM proxy host containing only
  `dev-scraper-service.flyio.ai`, with a valid TLS certificate and DNS pointing
  at NPM. The pipeline discovers its ID automatically. Custom location rules
  are rejected because they can forward requests to different containers.
- Confirm `https://npm-domain.flyio.ai/api` reaches NPM's management API from
  Jenkins. `NPM_URL` can override the management URL.

Each build tags a new image with a job hash and Jenkins build number. The old
container stays up while Jenkins builds, starts, and checks the new one.
Checks cover repeated container health and authenticated job API access; they
do not run a real scrape. The pipeline updates only NPM's upstream fields,
checks NPM's saved configuration and public HTTPS health, and attempts to
restore the previous upstream on promotion failure. It does not independently
identify the release behind the public health response.

**Job continuity:** the service stores jobs/results in process memory. Switching
the upstream makes old job IDs unavailable through the domain, even while the
old container remains alive. This pipeline avoids stopping the serving
container during builds; shared job/result storage is still required for
uninterrupted job polling across releases.

Helper verification: `python3 -B -m unittest discover -s scripts -p 'test_*.py'`.
Live Jenkins, Docker, and installed-NPM compatibility must be verified on the
deployment host. NPM API references:
[authentication and discovery](https://nginxproxymanager.com/third-party/npm-auth-gateway.html#npm-api-endpoints-used),
[proxy-host update route](https://github.com/NginxProxyManager/nginx-proxy-manager/blob/develop/backend/routes/nginx/proxy_hosts.js).

A stateless, asynchronous web-scraping microservice built with **FastAPI**, **Crawl4AI**, and **Playwright**. It wraps web scraping and semantic content parsing into a stable HTTP API for client services (such as `flyio-admin`) to trigger background scrape jobs and retrieve chunked results.

---

## Features

- **Asynchronous Job Processing:** Jobs are queued in an in-memory FIFO queue and processed in the background without blocking API requests.
- **Dual Scraping Strategies:**
  - **Custom URLs:** Scrape any list of arbitrary URLs using Crawl4AI and headless Chromium.
  - **Tourism Sources:** Crawl configured tourism portals and MediaWiki/Wikivoyage API sources.
- **Semantic Parsing & Chunking:** Parses HTML content, cleans markup, and splits text into structured chunks with breadcrumb paths and semantic HTML.
- **Service-to-Service Authentication:** Secured with `X-Service-API-Key` header authentication.
- **Interactive Swagger Documentation:** Built-in OpenAPI 3.1.0 documentation with interactive Swagger UI (`/docs`), ReDoc (`/redoc`), and authorization support.
- **Deployable to Fly.io & Docker:** Production-ready `Dockerfile` and `fly.toml` with auto-stop/auto-start support.

---

## Project Structure

```
flyio-scraper-service/
├── .env.example              # Template for environment variables
├── Dockerfile                # Production Docker build (Chromium + Playwright)
├── fly.toml                  # Fly.io deployment and VM configuration
├── requirements.txt          # Python dependencies
├── legacy_crawler/           # Underlying crawler, parser, and chunking pipeline
│   ├── config.py             # Default tourism sources and crawler configs
│   ├── crawler/              # Crawl4AI & Wikivoyage API crawlers
│   └── parser/               # Semantic parser and text chunker
└── src/
    ├── main.py               # FastAPI application factory & lifespan worker
    ├── config/               # Settings loaded via pydantic-settings
    ├── crawler/              # Async thread-pool wrapper around legacy_crawler
    ├── middleware/           # Service-to-service auth middleware
    ├── queue/                # Async worker and job queue
    ├── routes/               # API routes (/health, /scrape/*)
    ├── schemas/              # Pydantic models for OpenAPI / Swagger docs
    └── store/                # In-memory job state store
```

---

## Quick Start (Local Setup)

### 1. Prerequisites
- Python 3.11+
- Virtual environment tool (`venv`)

### 2. Installation

Clone the repository and create a virtual environment:

```bash
python -m venv .venv

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# On Linux / macOS:
source .venv/bin/activate
```

Install dependencies and Playwright Chromium:

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

### 3. Configure Environment

Copy `.env.example` to `.env` and set your service key:

```bash
cp .env.example .env
```

Edit `.env`:
```env
SERVICE_API_KEY=my-super-secret-service-key
```

### 4. Run the Service

```bash
uvicorn src.main:app --reload --port 8000
```

The service will start at `http://localhost:8000`.

---

## API Documentation & Swagger UI

Once the service is running, explore the interactive documentation:

- **Swagger UI (Interactive):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc (Reference):** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON Spec:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

### Using Swagger UI Authentication
1. Navigate to `http://localhost:8000/docs`.
2. Click the green **Authorize 🔓** button in the upper-right corner.
3. Paste the value of `SERVICE_API_KEY` into the input field and click **Authorize**.
4. Test endpoints directly from the browser!

---

## API Endpoints

### 1. Health Check
`GET /health` (No authentication required)

Returns service status and current queue depth.

**Response (`200 OK`):**
```json
{
  "status": "ok",
  "timestamp": "2026-08-21T16:00:00.000000+00:00",
  "queue_size": 0
}
```

---

### 2. Scrape Custom URLs
`POST /scrape/urls` (Requires `X-Service-API-Key`)

Submits a batch of URLs to scrape in the background.

**Headers:**
```http
X-Service-API-Key: my-super-secret-service-key
Content-Type: application/json
```

**Request Body (JSON):**
```json
{
  "urls": [
    "https://en.wikivoyage.org/wiki/Tokyo",
    "https://en.wikivoyage.org/wiki/Kyoto"
  ]
}
```

Blank and whitespace-only entries are stripped. A body whose `urls` list is
empty after stripping returns `400`, not `202`.

**Response (`202 Accepted`):**
```json
{
  "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

---

### 3. Scrape Preconfigured Sources
`POST /scrape/sources` (Requires `X-Service-API-Key`)

Triggers crawling for all configured tourism portals (Wikivoyage, TourMyIndia, Holidify, etc.).

**Headers:**
```http
X-Service-API-Key: my-super-secret-service-key
```

**Response (`202 Accepted`):**
```json
{
  "job_id": "8f3b2075-f35b-4cbe-a178-9e5c6a512df8"
}
```

---

### 4. Get Job Status & Results
`GET /scrape/jobs/{job_id}` (Requires `X-Service-API-Key`)

Polls the state and results of a scrape job.

**Headers:**
```http
X-Service-API-Key: my-super-secret-service-key
```

**Response (`200 OK` — When completed successfully):**
```json
{
  "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "type": "urls",
  "status": "success",
  "submitted_at": "2026-08-21T16:00:00.000000+00:00",
  "completed_at": "2026-08-21T16:00:05.123456+00:00",
  "results": [
    {
      "source_url": "https://en.wikivoyage.org/wiki/Tokyo",
      "page_title": "Tokyo - Wikivoyage",
      "section_path": "Tokyo > See > Historic temples",
      "chunk_index": 0,
      "content_text": "Senso-ji is an ancient Buddhist temple located in Asakusa...",
      "content_html": "<p>Senso-ji is an ancient Buddhist temple located in Asakusa...</p>",
      "url": "https://en.wikivoyage.org/wiki/Tokyo",
      "status": "success"
    }
  ],
  "error": null
}
```

**Possible job `status` values:**
- `pending`: Job is queued or actively being processed.
- `success`: Job finished; `results` contains the array of extracted chunks.
- `failed`: Job encountered an error; `error` contains the exception details.

**Per-chunk `url` and `status`** are derived convenience fields, not extra
information. `url` mirrors `source_url`, and `status` is always `"success"` —
a chunk is only produced for a page that was crawled and parsed successfully, so
a failed page contributes no chunks at all. Whether the *job* succeeded is the
top-level `status` above. They exist so consumers that filter results on
`status`/`url` (flyio-admin does) select correctly; new consumers should prefer
`source_url`.

---

## Configuration & Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SERVICE_API_KEY` | *(Required in prod)* | Shared secret key for service-to-service authentication. |
| `TOURISM_SOURCES_JSON` | `""` | Optional JSON array overriding default tourism sources. |
| `CRAWL4AI_HEADLESS` | `true` | Runs Chromium in headless mode. |
| `CRAWL4AI_PAGE_TIMEOUT_MS` | `45000` | Timeout per page load in milliseconds. |
| `CRAWL4AI_WAIT_UNTIL` | `domcontentloaded` | Page load readiness state. |
| `CRAWL4AI_MAX_CONCURRENT` | `3` | Maximum concurrent page crawls. |
| `REQUEST_TIMEOUT` | `20` | HTTP request timeout in seconds for API crawlers. |
| `MAX_RETRIES` | `4` | Maximum retries on network failures. |
| `REQUEST_DELAY_SECONDS` | `2.0` | Base delay between successive requests to polite sources. |
| `REQUEST_DELAY_JITTER` | `1.0` | Random jitter added to delays. |
| `RESPECT_ROBOTS_TXT` | `true` | Whether to parse and respect `robots.txt`. |

---

## Docker Deployment

Build and run using Docker:

```bash
docker build -t flyio-scraper-service .

docker run -d \
  -p 8080:8080 \
  -e SERVICE_API_KEY="your-secret-key" \
  --name scraper-service \
  flyio-scraper-service
```

Test the container:
```bash
curl http://localhost:8080/health
```

---

## Deployment on Fly.io

1. **Set secrets on Fly.io:**
   ```bash
   fly secrets set SERVICE_API_KEY="your-production-secret-key"
   ```

2. **Deploy the application:**
   ```bash
   fly deploy
   ```

3. **Check logs:**
   ```bash
   fly logs
   ```


## Successful-deployment cleanup

After promotion passes, Jenkins rechecks the NPM upstream and public health,
then stops/removes older containers labelled for this development service.
The current candidate and newer containers are excluded. Old unused images
are removed when Docker permits it; no forced deletion or global pruning runs.
Failed promotion skips cleanup so rollback candidates remain. Cleanup errors
mark the build unstable without rolling back the healthy deployment.

No volumes are deleted. In admin, `flyio-admin-dev-uploads` remains mounted
across releases. Other projects' data volumes are not touched. Removing old
containers discards their process memory and writable container filesystem;
scraper jobs still running there are lost. After cleanup, immediate rollback
to those containers is no longer available. Docker gives running containers
30 seconds to stop before terminating them. Use one pipeline job per domain.
