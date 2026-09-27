import axios from "axios";
import { env } from "../config/env";

/**
 * HTTP client for flyio-scraper-service.
 *
 * All config (base URL, API key) read from env vars — nothing hardcoded.
 * Attaches X-API-Key header on every request.
 */

const scraperHttp = axios.create({
  baseURL: env.SCRAPER_SERVICE_URL,
  headers: {
    "Content-Type": "application/json",
    "X-Service-API-Key": env.SCRAPER_SERVICE_API_KEY,
  },
  timeout: 30_000,
});

export interface ScraperJobResponse {
  job_id: string;
  status?: string;
}

export interface ScraperResult {
  url?: string;
  source_url?: string;
  status: "success" | "failed";
  content?: string;
  content_text?: string;
  content_html?: string;
  title?: string;
  page_title?: string;
  section_path?: string;
  chunk_index?: number;
  error?: string;
  [key: string]: unknown;
}

export interface ScraperStatusResponse {
  status: "pending" | "running" | "success" | "failed";
  results?: ScraperResult[];
  error?: string;
}

/**
 * Submit a batch of URLs for scraping.
 * POST /scrape/urls
 */
export async function submitUrlScrape(
  urls: string,
  jobId?: string
): Promise<ScraperJobResponse> {
  const urlList = urls
    .split("\n")
    .map((u) => u.trim())
    .filter(Boolean);

  // jobId is forwarded so the scraper stores the job under *our* correlation
  // ID (see migration 004: "a UUID job_id that flows through both this service
  // and flyio-scraper-service"). It used to be accepted and dropped, so the
  // scraper minted its own ID while waitForJobCompletion kept polling ours —
  // every poll 404'd until the 300s timeout and ingestion failed with a
  // successful crawl sitting unread on the other side.
  const response = await scraperHttp.post<ScraperJobResponse>("/scrape/urls", {
    urls: urlList,
    ...(jobId ? { job_id: jobId } : {}),
  });
  return response.data;
}

/**
 * Trigger the fixed tourism sources scrape.
 * POST /scrape/sources
 */
export async function submitSourceScrape(
  jobId?: string
): Promise<ScraperJobResponse> {
  // Same correlation-ID forwarding as submitUrlScrape, via query string —
  // /scrape/sources takes no request body.
  const response = await scraperHttp.post<ScraperJobResponse>(
    "/scrape/sources",
    undefined,
    jobId ? { params: { job_id: jobId } } : undefined
  );
  return response.data;
}

/**
 * Poll job status from the scraper service.
 * GET /scrape/jobs/:job_id
 */
export async function getJobStatus(
  jobId: string
): Promise<ScraperStatusResponse> {
  const response = await scraperHttp.get<ScraperStatusResponse>(
    `/scrape/jobs/${jobId}`
  );
  return response.data;
}

export interface DiscoveredUrl {
  url: string;
  title: string;
  domain: string;
  /** Trust score 0-100. Higher ranks first; unknown domains score 30. */
  score: number;
  /** True when the domain is curated-trusted or a government tourism board. */
  trusted: boolean;
  /** The expansion query that surfaced this URL. */
  query: string;
}

export interface DiscoverResponse {
  destination: string;
  provider: string;
  queries: string[];
  /** Raw search hits seen before filtering — the denominator for "kept N of M". */
  considered: number;
  candidates: DiscoveredUrl[];
  /** Per-query failures. Non-empty means fewer topics are represented. */
  errors: string[];
}

/**
 * Ask the scraper service which URLs are worth crawling for a destination.
 * POST /scrape/discover
 *
 * Returns candidates only — nothing is crawled by this call. The scraper is
 * stateless and has no view of what is already ingested, so deduplication
 * against `knowledge_base` happens on this side (see routes/scrape.ts).
 *
 * Uses a longer timeout than the shared client default: this fans out into
 * several concurrent search-API calls, and the default 30s is the budget for
 * a single fast request.
 */
export async function discoverUrls(
  destination: string,
  maxUrls?: number
): Promise<DiscoverResponse> {
  const response = await scraperHttp.post<DiscoverResponse>(
    "/scrape/discover",
    { destination, ...(maxUrls ? { max_urls: maxUrls } : {}) },
    { timeout: 60_000 }
  );
  return response.data;
}
