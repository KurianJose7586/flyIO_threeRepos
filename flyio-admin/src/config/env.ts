import dotenv from "dotenv";
import path from "path";

dotenv.config({ path: path.resolve(__dirname, "../../.env") });

export interface EnvConfig {
  PORT: number;
  NODE_ENV: string;
  // PostgreSQL
  DATABASE_URL?: string;
  PGHOST?: string;
  PGPORT?: number;
  PGUSER?: string;
  PGPASSWORD?: string;
  PGDATABASE?: string;
  // Admin auth
  CMS_JWT_SECRET: string;
  INITIAL_ADMIN_USERNAME?: string;
  INITIAL_ADMIN_PASSWORD?: string;
  // Scraper service
  SCRAPER_SERVICE_URL: string;
  SCRAPER_SERVICE_API_KEY: string;
  // Polling config
  SCRAPER_POLL_INTERVAL_MS: number;
  SCRAPER_JOB_TIMEOUT_MS: number;
  LLM_STORE_BATCH_SIZE: number;
  // Blog
  BLOG_UPLOAD_DIR: string;
  CKEDITOR_TOOLBAR: string[];
  // LLM Service
  LLM_SERVICE_URL: string;
  LLM_SERVICE_API_KEY: string;
  DEFAULT_SOURCE_URLS: string[];
}

const getEnv = (): EnvConfig => {
  const CMS_JWT_SECRET = process.env.CMS_JWT_SECRET;
  if (!CMS_JWT_SECRET) {
    throw new Error(
      "CRITICAL CONFIG ERROR: 'CMS_JWT_SECRET' is not set. " +
        "Generate one with: openssl rand -hex 32"
    );
  }

  const SCRAPER_SERVICE_URL = process.env.SCRAPER_SERVICE_URL;
  if (!SCRAPER_SERVICE_URL) {
    throw new Error(
      "CRITICAL CONFIG ERROR: 'SCRAPER_SERVICE_URL' is not set."
    );
  }

  const SCRAPER_SERVICE_API_KEY = process.env.SCRAPER_SERVICE_API_KEY;
  if (!SCRAPER_SERVICE_API_KEY) {
    throw new Error(
      "CRITICAL CONFIG ERROR: 'SCRAPER_SERVICE_API_KEY' is not set."
    );
  }

  // Admin is a pure client of two servers, so it holds two keys and each is
  // named for its target. There are two independent pairs that must match:
  //
  //   admin.SCRAPER_SERVICE_API_KEY  <->  flyio-scraper-service.SERVICE_API_KEY
  //   admin.LLM_SERVICE_API_KEY      <->  flyio-ai-llm.SERVICE_API_KEY
  //
  // Those two pairs are unrelated and, in this deployment, genuinely hold
  // different values — the scraper rejects the LLM service's key. So there is
  // deliberately no generic SERVICE_API_KEY alias here: admin is not a server
  // and has no key of its own, which makes that name ambiguous about which
  // target it means, and guessing wrong sends one service's key to the other.
  //
  // Required, like SCRAPER_SERVICE_API_KEY above. It used to default to ""
  // when unset, so a deployment that omitted it booted cleanly, passed its
  // health check (/v1/health is public on the LLM service, so it proves
  // nothing about the key) and then failed every single ingestion with a 401
  // that read like a rotated key rather than a missing setting. Failing here
  // instead means such a release never gets promoted.
  const LLM_SERVICE_API_KEY = process.env.LLM_SERVICE_API_KEY;
  if (!LLM_SERVICE_API_KEY) {
    throw new Error(
      "CRITICAL CONFIG ERROR: 'LLM_SERVICE_API_KEY' is not set. It must equal SERVICE_API_KEY in the flyio-ai-llm environment (not the scraper's key)."
    );
  }

  // At least DATABASE_URL or PGHOST must be set
  const DATABASE_URL = process.env.DATABASE_URL;
  const PGHOST = process.env.PGHOST;
  if (!DATABASE_URL && !PGHOST) {
    throw new Error(
      "CRITICAL CONFIG ERROR: Either 'DATABASE_URL' or 'PGHOST' (plus PG* vars) must be set."
    );
  }

  const PORT = process.env.PORT ? parseInt(process.env.PORT, 10) : 3000;
  if (isNaN(PORT)) {
    throw new Error("CRITICAL CONFIG ERROR: 'PORT' must be a valid number.");
  }

  const SCRAPER_POLL_INTERVAL_MS = process.env.SCRAPER_POLL_INTERVAL_MS
    ? parseInt(process.env.SCRAPER_POLL_INTERVAL_MS, 10)
    : 5000;

  const SCRAPER_JOB_TIMEOUT_MS = process.env.SCRAPER_JOB_TIMEOUT_MS
    ? parseInt(process.env.SCRAPER_JOB_TIMEOUT_MS, 10)
    : 300000;

  // How many chunks go into one POST /v1/api/store call. The LLM service
  // embeds a whole request before answering, and the reverse proxy in front
  // of it closes the connection after ~90s, so a page sent in one request
  // fails from this side even though the service finishes the work and
  // stores the points — leaving Admin unable to record the point IDs it
  // never received. Batching keeps each call inside that budget. Raise it if
  // the embedding provider gets faster; lower it if the proxy gets stricter.
  const parsedBatchSize = process.env.LLM_STORE_BATCH_SIZE
    ? parseInt(process.env.LLM_STORE_BATCH_SIZE, 10)
    : NaN;
  const LLM_STORE_BATCH_SIZE =
    Number.isFinite(parsedBatchSize) && parsedBatchSize > 0 ? parsedBatchSize : 10;

  return {
    PORT,
    NODE_ENV: process.env.NODE_ENV || "development",
    DATABASE_URL,
    PGHOST,
    PGPORT: process.env.PGPORT ? parseInt(process.env.PGPORT, 10) : 5432,
    PGUSER: process.env.PGUSER,
    PGPASSWORD: process.env.PGPASSWORD,
    PGDATABASE: process.env.PGDATABASE,
    CMS_JWT_SECRET,
    INITIAL_ADMIN_USERNAME: process.env.INITIAL_ADMIN_USERNAME,
    INITIAL_ADMIN_PASSWORD: process.env.INITIAL_ADMIN_PASSWORD,
    SCRAPER_SERVICE_URL,
    SCRAPER_SERVICE_API_KEY,
    SCRAPER_POLL_INTERVAL_MS,
    SCRAPER_JOB_TIMEOUT_MS,
    LLM_STORE_BATCH_SIZE,
    BLOG_UPLOAD_DIR: process.env.BLOG_UPLOAD_DIR || "./uploads/blog",
    CKEDITOR_TOOLBAR: process.env.CKEDITOR_TOOLBAR
      ? process.env.CKEDITOR_TOOLBAR.split(",").map((s) => s.trim())
      : [
          "heading", "|",
          "bold", "italic", "link",
          "bulletedList", "numberedList", "|",
          "blockQuote", "insertTable",
          "undo", "redo",
        ],
    LLM_SERVICE_URL: process.env.LLM_SERVICE_URL || "http://localhost:8000",
    LLM_SERVICE_API_KEY,
    DEFAULT_SOURCE_URLS: process.env.DEFAULT_SOURCE_URLS
      ? process.env.DEFAULT_SOURCE_URLS.split("\n").map((u) => u.trim()).filter(Boolean)
      : [],
  };
};

export const env = getEnv();
