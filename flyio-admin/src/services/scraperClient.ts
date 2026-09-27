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
