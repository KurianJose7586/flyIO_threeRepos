# Flyio Admin & Orchestration Microservice

`flyio-admin` is the central **Application and Orchestration layer** for the **Flyio.ai** platform. It provides Headless CMS capabilities, dynamic Blog and Trip engines, web scraper pipeline coordination, and complete end-to-end AI/LLM workflow orchestration.

---

## 1. Architectural Role & Context

Flyio is architected as decoupled microservices communicating strictly via well-defined HTTP APIs:

```
┌────────────────────────────────────────────────────────┐
│                        Frontend                        │
└───────────────────────────┬────────────────────────────┘
                            │ HTTP
                            ▼
┌────────────────────────────────────────────────────────┐
│              flyio-admin (This Service)                │
│  - Frontend-facing API gateway & Admin Dashboard       │
│  - Headless CMS, Blog (CKEditor 5), Trip Packages      │
│  - Workflow orchestration & retry pipeline             │
│  - PostgreSQL persistent storage & process tracking    │
└───────────────┬───────────────────────────┬────────────┘
                │                           │
                │ HTTP                      │ HTTP (X-Service-API-Key)
                ▼                           ▼
┌───────────────────────────────┐   ┌───────────────────────────────┐
│     flyio-scraper-service     │   │         flyio-ai-llm          │
│  - URL fetching / scraping    │   │  - AI / LLM Plan Generation   │
│  - Raw HTML extraction        │   │  - Vector search & retrieval  │
│  - Async job queues & retries │   │  - Qdrant Vector Storage      │
└───────────────────────────────┘   └───────────────────────────────┘
```

### Core Responsibilities
- **Frontend-Facing APIs**: Serves all public and admin endpoints for CMS, Blog, Trips, and AI Itinerary generation.
- **Workflow Orchestration**: Orchestrates the multi-step pipeline connecting the user's prompt ➔ LLM Generate API ➔ Scraper Service ➔ HTML extraction ➔ JSON preparation ➔ LLM Store API (Qdrant) ➔ final AI Plan generation.
- **Durable Process Tracking**: Logs every operation into PostgreSQL (`prompt_history`, `request_events`, `jobs`, `job_events`, `history`).
- **Zero Hardcoding**: All endpoints, secrets, URLs, and paths are read dynamically from environment variables at runtime.

---

## 2. Interactive Swagger / OpenAPI Documentation

Interactive Swagger UI documentation is built into the application:

- **Swagger UI**: [http://localhost:3000/docs](http://localhost:3000/docs)
- **OpenAPI 3.0.3 Spec**: [http://localhost:3000/openapi.json](http://localhost:3000/openapi.json)

---

## 3. End-to-End Orchestration Workflow

When a request arrives at `POST /api/admin/llm/generate`:

```
1. Request received from frontend
   ↓
2. Generates shared request_id (e.g. req_8f7b2c1d4e0a)
   ↓
3. Saves prompt to prompt_history (status: 'pending')
   ↓
4. Calls flyio-ai-llm (POST /v1/api/generate)
   ↓
5. LLM checks Qdrant vector database:
   ├── [status: "data_found"]
   │     → Updates prompt_history (status: 'completed')
   │     → Returns synthesized travel plan to frontend ✅
   │
   └── [status: "data_required"]
         → Admin initiates automated source ingestion:
              a. Resolves source URLs, in order: request body → URLs in the
                 prompt text → web search for `destination` if one was given
                 (POST /scrape/discover, trusted domains only) →
                 DEFAULT_SOURCE_URLS → all configured tourism sources
              b. Calls Scraper Service (POST /scrape/urls)
              c. Waits for scraper job completion → stores clean chunks in knowledge_base
              d. Converts KB chunks into structured JSON documents
              e. Calls LLM Store API (POST /v1/api/store with mode: 'pre_chunked')
              f. Retries LLM Generate API (POST /v1/api/generate)
              g. Saves final plan to prompt_history → returns plan to frontend ✅
```

---

## 4. Tech Stack

- **Backend**: Node.js, Express, TypeScript, `pg` (PostgreSQL client pool), `jsonwebtoken`, `bcryptjs`, `multer`, `axios`, `uuid`.
- **Database**: PostgreSQL with `JSONB`, `pgcrypto` (UUID generation), and GIN indexing.
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, Lucide React icons, CKEditor 5 (CDN).
- **API Standards**: OpenAPI 3.0.3, Swagger UI, RESTful JSON.

---

## 5. Database Architecture

| Table | Description |
|---|---|
| **`admin_users`** | Admin accounts with bcrypt-hashed passwords. |
| **`pages`** | CMS dynamic landing pages (slug, title, body). |
| **`site_content`** | Key-value store for global marketing copy. |
| **`categories`** | Dynamic blog categories with slug. |
| **`tags`** | Dynamic blog tags with slug. |
| **`blog_posts`** | Articles with summary, author, banner URL, category FK, and CKEditor HTML body. |
| **`blog_post_tags`** | M:N join table connecting blog posts and tags. |
| **`trip_packages`** | Travel packages with JSON itineraries, price tiers, and media. |
| **`jobs`** | Scrape job tracker with UUID correlation. |
| **`job_events`** | Event timeline and audit logs per job. |
| **`knowledge_base`** | Extracted chunks, metadata, and HTML from successful scrapes. |
| **`history`** | Permanent audit record of every URL crawl attempt. |
| **`prompt_history`** | User prompts, status, and synthesized AI plans. |
| **`request_events`** | Cross-service lifecycle event tracking sharing `request_id`. |

---

## 6. Getting Started

### 1. Prerequisites
- **Node.js**: `v18+` or `v20+` / `v22+`
- **PostgreSQL Database**

### 2. Environment Configuration

Copy the example environment file and configure your credentials:

```bash
cp .env.example .env
```

```env
# ─── PostgreSQL ───────────────────────────────────────────────
PGHOST=localhost
PGPORT=5432
PGUSER=postgres
PGPASSWORD=your_password
PGDATABASE=flyio_admin
# OR use connection string:
# DATABASE_URL=postgresql://user:password@localhost:5432/flyio_admin

# ─── Admin Auth ───────────────────────────────────────────────
CMS_JWT_SECRET=your_super_secret_jwt_key_here
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=your_secure_password

# ─── Scraper Service ──────────────────────────────────────────
SCRAPER_SERVICE_URL=https://your-scraper-service.fly.dev
SCRAPER_SERVICE_API_KEY=your_scraper_api_key

# ─── LLM Service (flyio-ai-llm) ──────────────────────────────
LLM_SERVICE_URL=http://localhost:8000
LLM_SERVICE_API_KEY=your_llm_service_api_key
# DEFAULT_SOURCE_URLS=https://en.wikipedia.org/wiki/Tourism_in_France

# ─── Blog Configuration (optional) ───────────────────────────
BLOG_UPLOAD_DIR=./uploads/blog
CKEDITOR_TOOLBAR=heading,|,bold,italic,link,bulletedList,numberedList,|,blockQuote,insertTable,undo,redo

# ─── Server ───────────────────────────────────────────────────
PORT=3000
NODE_ENV=development
```

---

### 3. Installation

```bash
# Backend dependencies
npm install

# Frontend dependencies
npm install --prefix frontend
```

---

### 4. Running Locally

#### Run Backend & Frontend Concurrently (Dev Mode)
```bash
npm run dev:all
```
- Admin Panel: **`http://localhost:5173/admin`**
- Public Site: **`http://localhost:5173`**
- Swagger Docs: **`http://localhost:3000/docs`**

#### Run Separately
```bash
# Terminal 1: Backend API (Port 3000)
npm run dev

# Terminal 2: Frontend Vite (Port 5173)
npm run dev:frontend
```

#### Production Build & Run
```bash
npm run build:frontend
npm run build
npm start
```

---

## 7. Complete API Reference

### System & Documentation
- `GET /health` — Health check endpoint.
- `GET /docs` — Interactive Swagger UI documentation.
- `GET /openapi.json` — Raw OpenAPI 3.0.3 specification.

### Authentication
- `POST /api/admin/login` — Login with username & password, returns JWT token.
- `GET /api/admin/me` — Verify token and get current admin details.

### LLM Orchestration & Prompt History
- `POST /api/admin/llm/generate` — Orchestrated AI plan generation with automated scraper fallback & vector ingestion.
- `POST /api/admin/llm/store` — Push knowledge base content to LLM Store API (Qdrant).
- `GET /api/admin/llm/health` — Check LLM Service and Qdrant connectivity.
- `GET /api/admin/prompts` — Paginated prompt history list.
- `GET /api/admin/prompts/:request_id` — Single prompt detail with cross-service `request_events` timeline trace.
- `DELETE /api/admin/prompts/:request_id` — Delete prompt record and associated event traces.

### Knowledge Base & Web Scraper
- `POST /api/admin/discover` — Destination in, ranked candidate URLs out. Crawls nothing; each candidate is marked with whether it is already indexed, stale, or needs review.
- `POST /api/admin/crawl/auto` — Discover **and** crawl in one call. Pass `urls` to crawl a reviewed selection; omit it to crawl everything discovery recommends. Records the destination on the job.
- `POST /api/admin/crawl` (or `POST /api/admin/scrape/urls`) — Submit URLs to Scraper Service.
- `POST /api/admin/scrape/sources` — Scrape default configured tourism sources.
- `GET /api/admin/jobs/:job_id/status` — Check job status.
- `GET /api/admin/jobs` — Paginated list of recent scrape jobs.
- `GET /api/admin/knowledge-base` — Paginated list of indexed URLs in knowledge base.
- `GET /api/admin/knowledge-base/chunks?source_url=...` — View all extracted chunks for a URL.
- `DELETE /api/admin/knowledge-base?source_url=...` (or `?id=...`) — Delete URL/chunk from knowledge base (audit history preserved).
- `GET /api/admin/crawl-history` — Permanent audit log of all crawl attempts.

### Blog & Taxonomy
- `GET /api/blog/posts` — Public blog posts list with sorting (`?sort=created_at|author`, `?order=asc|desc`).
- `GET /api/blog/posts/:slug` — Public single blog post.
- `GET/POST /api/admin/blog/posts` — Manage admin blog posts.
- `GET/POST/PUT/DELETE /api/admin/blog/categories` — Manage blog categories.
- `GET/POST/PUT/DELETE /api/admin/blog/tags` — Manage blog tags.
- `POST /api/admin/blog/upload-banner` — Upload banner image (saved to `BLOG_UPLOAD_DIR`).
- `GET /api/admin/config/ckeditor` — Dynamic CKEditor toolbar config.

### Headless CMS & Trip Packages
- `GET/POST/PUT/DELETE /api/cms/pages` — Manage custom pages.
- `GET/PUT /api/cms/content` — Manage site copy key-value pairs.
- `GET/POST/PUT/DELETE /api/admin/trips/packages` — Manage travel packages.

---

## 8. Anti-Hardcoding Guarantee

Every configuration value is dynamically loaded:
- **Zero hardcoded credentials**: Auth credentials and JWT secret read from `.env`.
- **Zero hardcoded service URLs**: Scraper and LLM microservice endpoints read from `SCRAPER_SERVICE_URL` and `LLM_SERVICE_URL`.
- **Zero hardcoded upload paths**: Upload destination read from `BLOG_UPLOAD_DIR`.
- **Zero hardcoded editor config**: CKEditor toolbar configuration read from `CKEDITOR_TOOLBAR`.
- **Zero hardcoded taxonomy**: Categories and tags managed dynamically in PostgreSQL.

---

## 9. License

Private & Proprietary — Flyio.ai.
