# Configuration

Copy `.env.example` to `.env` and fill in real values:

```bash
cp .env.example .env
```

`.env.example` has inline comments for every non-obvious variable (provider-specific setup for Groq/local embeddings, why some defaults are intentionally blank, etc.) — this table is a quick-reference summary, not a replacement for reading it.

| Variable | Default | Notes |
|---|---|---|
| `PROJECT_NAME` | `flyio-ai-llm` | |
| `ENVIRONMENT` | `development` | `development` \| `staging` \| `production` \| `testing` |
| `DEBUG` | `true` | |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | |
| `LOG_LEVEL` | `INFO` | |
| `LOG_FORMAT` | `json` | `json` (log aggregators, cross-service tracing) or `text` (readable local terminal) |
| `SERVICE_API_KEY` | *(empty)* | Shared secret Admin sends as `X-Service-API-Key`. Empty = every `/v1/*` request is rejected (fails closed, not open) |
| `LLM_PROVIDER` | `mock` | `mock` \| `openai` \| `groq` |
| `LLM_API_KEY` | *(empty)* | Your OpenAI or Groq key, depending on provider |
| `LLM_MODEL` | `gpt-4o-mini` | e.g. `openai/gpt-oss-120b` for Groq |
| `EMBEDDING_PROVIDER` | `mock` | `mock` \| `openai` \| `local` |
| `EMBEDDING_API_KEY` | *(empty)* | Only used for `openai` |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | `sentence-transformers/all-MiniLM-L6-v2` for `local` |
| `EMBEDDING_DIMENSION` | `1536` | **Must be `384` for `local`** — mismatched dimension breaks Qdrant collection creation |
| `STORE_MAX_DOCUMENTS` | `100` | Max documents per `/v1/api/store` call |
| `STORE_MAX_TOTAL_CHARS` | `500000` | Max combined text size per `/v1/api/store` call |
| `QDRANT_URL` | `http://localhost:6333` | |
| `QDRANT_API_KEY` | *(empty)* | Only needed for Qdrant Cloud |
| `QDRANT_COLLECTION_NAME` | `flyio_knowledge_base` | |
| `QDRANT_SEARCH_SCORE_THRESHOLD` | `0.45` | Tuned for `local` embeddings — raise toward `0.70` if using `openai` embeddings (see `.env.example`) |
| `DATABASE_ENABLED` | `true` | |
| `DATABASE_URL` | *(empty)* | Postgres DSN. Empty = event tracking cleanly disables itself, no crash |

## Real free providers (no OpenAI key needed)

```ini
LLM_PROVIDER="groq"
LLM_API_KEY="gsk_..."          # free at console.groq.com
LLM_MODEL="openai/gpt-oss-120b"

EMBEDDING_PROVIDER="local"
EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION=384
```
