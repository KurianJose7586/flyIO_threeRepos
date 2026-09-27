import { Router, Request, Response } from "express";
import axios from "axios";
import { v4 as uuidv4 } from "uuid";
import { query } from "../db/pgPool";
import { requireAdminAuth } from "../middleware/requireAdminAuth";
import {
  submitUrlScrape,
  submitSourceScrape,
  getJobStatus,
  discoverUrls,
  type DiscoveredUrl,
} from "../services/scraperClient";
import {
  logEvent,
  processJobOutcome,
  waitForJobCompletion,
} from "../services/jobScheduler";

const router = Router();

function isHttpUrl(u: string): boolean {
  try {
    const parsed = new URL(u);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && !!parsed.hostname;
  } catch {
    return false;
  }
}

/**
 * How long a crawled URL is considered current. Past this, an already-indexed
 * URL is offered for re-crawling instead of being skipped — destination pages
 * change (prices, timings, transport), and the store has no other mechanism
 * for noticing.
 */
const KB_FRESHNESS_DAYS = 90;

export interface AnnotatedCandidate extends DiscoveredUrl {
  /** Already present in knowledge_base. */
  already_indexed: boolean;
  /** Last ingest time for this URL, ISO 8601, or null if never indexed. */
  last_indexed_at: string | null;
  /** Chunks currently held for this URL. */
  indexed_chunks: number;
  /** Indexed, but older than KB_FRESHNESS_DAYS. */
  stale: boolean;
  /**
   * What the automated path would do with this candidate, and why. Surfaced
   * so an operator can see the filter's reasoning rather than a bare list.
   */
  recommended: boolean;
  reason: string;
}

/**
 * Marks discovery candidates with what the knowledge base already holds.
 *
 * The scraper service is stateless by design and cannot answer this — the
 * `knowledge_base` table lives here. Doing the check before crawling is what
 * stops the same page being fetched, chunked and embedded twice: the existing
 * Jaipur document is stored twice already (57 structured chunks from the
 * crawler, 192 unstructured ones from an ad-hoc script), and those duplicates
 * compete against each other at retrieval time.
 */
async function annotateWithIndexState(
  candidates: DiscoveredUrl[]
): Promise<AnnotatedCandidate[]> {
  if (candidates.length === 0) return [];

  const urls = candidates.map((c) => c.url);
  const indexed = await query(
    `SELECT source_url,
            MAX(created_at) AS last_indexed_at,
            COUNT(*)        AS chunks
     FROM knowledge_base
     WHERE source_url = ANY($1::text[])
     GROUP BY source_url`,
    [urls]
  );

  const state = new Map<string, { lastIndexedAt: Date; chunks: number }>();
  for (const row of indexed.rows) {
    state.set(row.source_url, {
      lastIndexedAt: new Date(row.last_indexed_at),
      chunks: parseInt(row.chunks, 10),
    });
  }

  const staleBefore = Date.now() - KB_FRESHNESS_DAYS * 24 * 60 * 60 * 1000;

  return candidates.map((c) => {
    const existing = state.get(c.url);
    const stale = existing ? existing.lastIndexedAt.getTime() < staleBefore : false;

    let recommended: boolean;
    let reason: string;
    if (existing && !stale) {
      recommended = false;
      reason = `Already indexed (${existing.chunks} chunks)`;
    } else if (existing && stale) {
      recommended = true;
      reason = `Indexed over ${KB_FRESHNESS_DAYS} days ago — re-crawl`;
    } else if (c.trusted) {
      recommended = true;
      reason = `Trusted source (${c.domain})`;
    } else {
      // Deliberately surfaced rather than dropped: an unknown domain may be
      // exactly the right source for a small destination, and that judgement
      // is the operator's. Listed, but never auto-crawled.
      recommended = false;
      reason = "Unrecognised domain — review before crawling";
    }

    return {
      ...c,
      already_indexed: Boolean(existing),
      last_indexed_at: existing ? existing.lastIndexedAt.toISOString() : null,
      indexed_chunks: existing ? existing.chunks : 0,
      stale,
      recommended,
      reason,
    };
  });
}

/**
 * Submits URLs to the scraper service and opens the matching job row here.
 *
 * Extracted from the /api/admin/crawl handler so the destination-driven path
 * goes through byte-for-byte the same submission, job record and event log —
 * an automated crawl must not become a second, subtly different pipeline.
 */
async function startUrlCrawlJob(
  submittedUrls: string[],
  operation: "url_scrape" | "auto_scrape" = "url_scrape"
): Promise<string> {
  const scraperRes = await submitUrlScrape(submittedUrls.join("\n"));
  const jobId = scraperRes?.job_id || uuidv4();

  await query("INSERT INTO jobs (id, operation, status) VALUES ($1, $2, 'sent')", [
    jobId,
    operation,
  ]);
  // The submitted list is recorded on the job itself so its outcome can be
  // reconciled against what was actually asked for. An async submission
  // returns immediately and the background scheduler finalizes the job, and
  // that scheduler is not told what was submitted — so a URL the scraper
  // silently dropped left no trace anywhere while the job still reported
  // success. See processJobOutcome.
  await logEvent(jobId, "created", {
    url_count: submittedUrls.length,
    urls: submittedUrls,
  });
  await logEvent(jobId, "sent_to_scraper");

  return jobId;
}

/**
 * Translates a failure from the discovery call into a response.
 *
 * The scraper service answers a misconfigured search provider with a 400 and
 * a message naming the fix ("SEARCH_API_KEY is empty but SEARCH_PROVIDER is
 * 'tavily'"), and a dead provider with a 502. Collapsing both into a generic
 * 500 here would throw that away and leave an operator staring at "Internal
 * Server Error" for a missing environment variable, so the upstream status
 * and detail are forwarded as-is.
 */
function handleDiscoveryError(err: unknown, res: Response): void {
  if (axios.isAxiosError(err) && err.response) {
    const status = err.response.status;
    const detail =
      (err.response.data as { detail?: string } | undefined)?.detail ||
      err.message;

    // 401 means *this service's* key for the scraper is wrong. Forwarding it
    // would read as "your admin login expired" and send someone to the wrong
    // place entirely.
    if (status === 401) {
      res.status(502).json({
        success: false,
        error: "Bad Gateway",
        detail:
          "The scraper service rejected this service's API key. Check that admin's SCRAPER_SERVICE_API_KEY matches the scraper's SERVICE_API_KEY.",
      });
      return;
    }

    res.status(status === 400 ? 400 : 502).json({
      success: false,
      error: status === 400 ? "Bad Request" : "Bad Gateway",
      detail,
    });
    return;
  }

  const e = err as Error;
  res.status(500).json({
    success: false,
    error: "Internal Server Error",
    detail: e.message,
  });
}

// ─────────────────────────────────────────────────────────────
// POST /api/admin/scrape/urls & /api/admin/crawl
// Submits a batch of URLs and waits synchronously via the scheduler
// until completed before returning the final result.
// ─────────────────────────────────────────────────────────────
router.post(
  ["/api/admin/scrape/urls", "/api/admin/crawl"],
  requireAdminAuth,
  async (req: Request, res: Response) => {
    try {
      const { urls, async: isAsync } = req.body;
      if (!urls || typeof urls !== "string" || !urls.trim()) {
        res.status(400).json({
          success: false,
          error: "Bad Request",
          detail: "Field 'urls' (one URL per line) is required.",
        });
        return;
      }

      const submittedUrls = urls
        .trim()
        .split("\n")
        .map((u) => u.trim())
        .filter(Boolean);

      // Reject non-URLs here rather than letting the scraper fail the job on
      // them — its failure carries no per-URL detail back to the UI.
      const invalidUrls = submittedUrls.filter((u) => !isHttpUrl(u));
      if (invalidUrls.length > 0) {
        res.status(400).json({
          success: false,
          error: "Bad Request",
          detail: `Not a valid http(s) URL: ${invalidUrls.join(", ")}. Include the scheme, e.g. https://en.wikivoyage.org/wiki/Gorakhpur`,
        });
        return;
      }

      // Shared with the destination-driven path in POST /api/admin/crawl/auto
      // so both submit, record and log identically.
      const jobId = await startUrlCrawlJob(submittedUrls);

      // If caller explicitly requested asynchronous fire-and-forget
      if (isAsync === true || req.query.async === "true") {
        res.json({ success: true, job_id: jobId, status: "sent" });
        return;
      }

      // Synchronous behavior: wait internally via scheduler until terminal status
      const outcome = await waitForJobCompletion(jobId, { expectedUrls: submittedUrls });

      if (outcome.status === "success") {
        res.json({
          success: true,
          job_id: jobId,
          status: "success",
          total: outcome.total,
          succeeded: outcome.succeeded,
          failed: outcome.failed,
          results: outcome.results,
        });
      } else {
        res.status(502).json({
          success: false,
          job_id: jobId,
          status: "failed",
          error: outcome.error || "Scraping operation failed",
          total: outcome.total,
          succeeded: outcome.succeeded,
          failed: outcome.failed,
          results: outcome.results,
        });
      }
    } catch (err: unknown) {
      const e = err as Error;
      res.status(500).json({
        success: false,
        error: "Internal Server Error",
        detail: e.message,
      });
    }
  }
);

// ─────────────────────────────────────────────────────────────
// POST /api/admin/scrape/sources
// Trigger tourism sources scrape and wait synchronously for outcome.
// ─────────────────────────────────────────────────────────────
router.post(
  "/api/admin/scrape/sources",
  requireAdminAuth,
  async (req: Request, res: Response) => {
    try {
      const isAsync = req.body?.async === true || req.query.async === "true";

      const scraperRes = await submitSourceScrape();
      const jobId = scraperRes?.job_id || uuidv4();

      await query(
        "INSERT INTO jobs (id, operation, status) VALUES ($1, 'source_scrape', 'sent')",
        [jobId]
      );
      await logEvent(jobId, "created");
      await logEvent(jobId, "sent_to_scraper");

      if (isAsync) {
        res.json({ success: true, job_id: jobId, status: "sent" });
        return;
      }

      // Synchronous wait
      const outcome = await waitForJobCompletion(jobId);

      if (outcome.status === "success") {
        res.json({
          success: true,
          job_id: jobId,
          status: "success",
          total: outcome.total,
          succeeded: outcome.succeeded,
          failed: outcome.failed,
          results: outcome.results,
        });
      } else {
        res.status(502).json({
          success: false,
          job_id: jobId,
          status: "failed",
          error: outcome.error || "Source scraping failed",
          total: outcome.total,
          succeeded: outcome.succeeded,
          failed: outcome.failed,
          results: outcome.results,
        });
      }
    } catch (err: unknown) {
      const e = err as Error;
      res.status(500).json({
        success: false,
        error: "Internal Server Error",
        detail: e.message,
      });
    }
  }
);

// ─────────────────────────────────────────────────────────────
// GET /api/admin/jobs/:job_id/status
// Poll job status — proxies to scraper, processes/stores results if done.
// ─────────────────────────────────────────────────────────────
router.get(
  "/api/admin/jobs/:job_id/status",
  requireAdminAuth,
  async (req: Request, res: Response) => {
    try {
      const { job_id } = req.params;

      const jobResult = await query("SELECT id, status FROM jobs WHERE id = $1", [job_id]);
      if (jobResult.rows.length === 0) {
        res.status(404).json({ success: false, error: "Not Found", detail: `Job '${job_id}' not found.` });
        return;
      }

      const dbJob = jobResult.rows[0];

      // If already finalized in DB, return stored state
      if (dbJob.status === "success" || dbJob.status === "failed") {
        res.json({ success: true, job_id, status: dbJob.status });
        return;
      }

      // Proxy to scraper service
      const scraperStatus = await getJobStatus(job_id);

      if (scraperStatus.status === "success" || scraperStatus.status === "failed") {
        const outcome = await processJobOutcome(job_id, scraperStatus);
        res.json({
          success: outcome.status === "success",
          job_id,
          status: outcome.status,
          results: outcome.results,
          total: outcome.total,
          succeeded: outcome.succeeded,
          failed: outcome.failed,
          error: outcome.error,
        });
        return;
      }

      // Still pending/running
      res.json({ success: true, job_id, status: scraperStatus.status });
    } catch (err: unknown) {
      const e = err as Error;
      res.status(500).json({
        success: false,
        error: "Internal Server Error",
        detail: e.message,
      });
    }
  }
);

// ─────────────────────────────────────────────────────────────
// GET /api/admin/jobs/:job_id/url-results
// Returns per-URL progress for a job — reads from history table
// for resolved URLs, marks unresolved URLs as pending.
// Used by the frontend to show real-time per-URL status cards.
// ─────────────────────────────────────────────────────────────
router.get(
  "/api/admin/jobs/:job_id/url-results",
  requireAdminAuth,
  async (req: Request, res: Response) => {
    try {
      const { job_id } = req.params;

      // Get job status and any submitted URL list stored in job_events
      const jobResult = await query(
        "SELECT id, status, created_at FROM jobs WHERE id = $1",
        [job_id]
      );
      if (jobResult.rows.length === 0) {
        res.status(404).json({ success: false, error: "Not Found", detail: `Job '${job_id}' not found.` });
        return;
      }
      const jobStatus = jobResult.rows[0].status as string;

      // Fetch all history rows for this job (one row per URL that has resolved)
      const historyResult = await query(
        `SELECT url, status, error_message, duration_ms FROM history WHERE job_id = $1`,
        [job_id]
      );

      // Fetch chunk counts per URL from knowledge_base, along with how many of
      // those chunks carry a Qdrant point ID — i.e. actually reached the
      // vector DB rather than only Postgres.
      const kbResult = await query(
        `SELECT source_url,
                COUNT(*) as cnt,
                COUNT(qdrant_point_id) as ingested
         FROM knowledge_base WHERE job_id = $1 GROUP BY source_url`,
        [job_id]
      );
      const chunkMap = new Map<string, number>();
      const ingestedMap = new Map<string, number>();
      for (const row of kbResult.rows) {
        chunkMap.set(row.source_url, parseInt(row.cnt, 10));
        ingestedMap.set(row.source_url, parseInt(row.ingested, 10));
      }

      // Build per-URL results from history
      const urlResults = historyResult.rows.map((h) => {
        const chunks = chunkMap.get(h.url) || 0;
        const ingested = ingestedMap.get(h.url) || 0;
        return {
          url: h.url,
          status: h.status as "success" | "failed" | "pending" | "running",
          chunks,
          vector_chunks: ingested,
          // Only meaningful once the scrape itself has succeeded; until then
          // there is nothing to ingest yet.
          //
          // A URL's history row is written before its chunks are pushed, and
          // the push runs in batches, so "no vectors yet" is the normal state
          // for the first part of a job. Report that as pending rather than
          // failed while the job is still running — the job is not finalized
          // until ingestion has been attempted, so a terminal job with zero
          // vectors is the only case that genuinely failed.
          vector_status:
            h.status !== "success"
              ? null
              : ingested >= chunks
                ? "stored"
                : ingested > 0
                  ? "partial"
                  : jobStatus === "success" || jobStatus === "failed"
                    ? "failed"
                    : "pending",
          error: h.error_message || null,
          duration_ms: h.duration_ms ?? null,
        };
      });

      res.json({
        success: true,
        job_id,
        job_status: jobStatus,
        urls: urlResults,
      });
    } catch (err: unknown) {
      const e = err as Error;
      res.status(500).json({
        success: false,
        error: "Internal Server Error",
        detail: e.message,
      });
    }
  }
);

// ─────────────────────────────────────────────────────────────
// GET /api/admin/jobs — list recent jobs
// ─────────────────────────────────────────────────────────────
router.get("/api/admin/jobs", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const page = Math.max(1, parseInt(req.query.page as string, 10) || 1);
    const limit = Math.min(100, Math.max(1, parseInt(req.query.limit as string, 10) || 20));
    const offset = (page - 1) * limit;

    const countResult = await query("SELECT COUNT(*) as count FROM jobs");
    const total = parseInt(countResult.rows[0].count, 10);

    const result = await query(
      `SELECT id, operation, status, created_at, updated_at
       FROM jobs ORDER BY created_at DESC LIMIT $1 OFFSET $2`,
      [limit, offset]
    );

    res.json({
      success: true,
      jobs: result.rows,
      pagination: { total, page, limit, totalPages: Math.ceil(total / limit) || 1 },
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

// ─────────────────────────────────────────────────────────────
// GET /api/admin/jobs/:job_id — full job detail + event log
// ─────────────────────────────────────────────────────────────
router.get("/api/admin/jobs/:job_id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { job_id } = req.params;
    const jobResult = await query("SELECT * FROM jobs WHERE id = $1", [job_id]);
    if (jobResult.rows.length === 0) {
      res.status(404).json({ success: false, error: "Not Found", detail: `Job '${job_id}' not found.` });
      return;
    }
    const eventsResult = await query(
      "SELECT id, event_type, detail, created_at FROM job_events WHERE job_id = $1 ORDER BY created_at ASC",
      [job_id]
    );
    res.json({ success: true, job: jobResult.rows[0], events: eventsResult.rows });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

// ─────────────────────────────────────────────────────────────
// POST /api/admin/discover
// Destination in, reviewable candidate URLs out. Crawls nothing.
//
// This is the preview half of the automation: it answers "what would an
// automatic crawl of Jabalpur fetch?" so an operator can approve the list
// before any of it is embedded. POST /api/admin/crawl/auto runs the same
// discovery and goes straight to crawling.
// ─────────────────────────────────────────────────────────────
router.post(
  "/api/admin/discover",
  requireAdminAuth,
  async (req: Request, res: Response) => {
    try {
      const { destination, max_urls: maxUrls } = req.body ?? {};

      if (!destination || typeof destination !== "string" || !destination.trim()) {
        res.status(400).json({
          success: false,
          error: "Bad Request",
          detail: "Field 'destination' is required, e.g. { \"destination\": \"Jabalpur\" }.",
        });
        return;
      }

      const discovery = await discoverUrls(destination.trim(), maxUrls);
      const candidates = await annotateWithIndexState(discovery.candidates);

      res.json({
        success: true,
        destination: discovery.destination,
        provider: discovery.provider,
        queries: discovery.queries,
        considered: discovery.considered,
        candidates,
        recommended_count: candidates.filter((c) => c.recommended).length,
        // Partial search failures mean fewer topics are represented than
        // asked for. Passed through rather than swallowed, so a thin result
        // is not mistaken for "this destination has little coverage".
        errors: discovery.errors,
      });
    } catch (err: unknown) {
      handleDiscoveryError(err, res);
    }
  }
);

// ─────────────────────────────────────────────────────────────
// POST /api/admin/crawl/auto
// Destination in, populated knowledge base out — search, filter, crawl,
// chunk and embed, with no URL typed by hand.
//
// Accepts an explicit `urls` array to crawl the operator's edited selection
// from POST /api/admin/discover; without it, crawls everything discovery
// recommends (trusted, and either never indexed or stale).
// ─────────────────────────────────────────────────────────────
router.post(
  "/api/admin/crawl/auto",
  requireAdminAuth,
  async (req: Request, res: Response) => {
    try {
      const {
        destination,
        max_urls: maxUrls,
        urls: approvedUrls,
        async: isAsyncBody,
      } = req.body ?? {};
      const isAsync = isAsyncBody === true || req.query.async === "true";

      if (!destination || typeof destination !== "string" || !destination.trim()) {
        res.status(400).json({
          success: false,
          error: "Bad Request",
          detail: "Field 'destination' is required, e.g. { \"destination\": \"Jabalpur\" }.",
        });
        return;
      }

      const discovery = await discoverUrls(destination.trim(), maxUrls);
      const candidates = await annotateWithIndexState(discovery.candidates);

      // An explicit list is an operator decision that has already been made,
      // so it is honoured as given — including an unrecognised domain they
      // chose to trust. It is still intersected with what discovery returned,
      // so this endpoint can never be used to crawl an arbitrary URL that
      // bypassed the filters; /api/admin/crawl already exists for that.
      let selected: AnnotatedCandidate[];
      if (Array.isArray(approvedUrls) && approvedUrls.length > 0) {
        const approved = new Set<string>(approvedUrls);
        selected = candidates.filter((c) => approved.has(c.url));
      } else {
        selected = candidates.filter((c) => c.recommended);
      }

      if (selected.length === 0) {
        // Not an error: "everything for this destination is already indexed"
        // is the expected steady state, and re-running must be a no-op rather
        // than a duplicate ingest. The candidates come back so the caller can
        // see why nothing was selected and override if they disagree.
        res.json({
          success: true,
          destination: discovery.destination,
          job_id: null,
          status: "skipped",
          detail:
            candidates.length === 0
              ? `No usable sources found for '${discovery.destination}'. Every search result was filtered out as a denied domain or a non-document URL.`
              : `Nothing to crawl for '${discovery.destination}' — all ${candidates.length} candidate(s) are already indexed or need manual review.`,
          candidates,
          errors: discovery.errors,
        });
        return;
      }

      const submittedUrls = selected.map((c) => c.url);
      const jobId = await startUrlCrawlJob(submittedUrls, "auto_scrape");

      // Recorded on the job so the destination that triggered an automated
      // crawl is recoverable afterwards — the jobs table otherwise only knows
      // about URLs, and "why was this page crawled?" has no answer.
      await logEvent(jobId, "auto_discovered", {
        destination: discovery.destination,
        provider: discovery.provider,
        queries: discovery.queries,
        considered: discovery.considered,
        selected: submittedUrls,
        search_errors: discovery.errors,
      });

      if (isAsync) {
        res.json({
          success: true,
          destination: discovery.destination,
          job_id: jobId,
          status: "sent",
          urls: submittedUrls,
          candidates,
          errors: discovery.errors,
        });
        return;
      }

      const outcome = await waitForJobCompletion(jobId, {
        expectedUrls: submittedUrls,
      });

      res.status(outcome.status === "success" ? 200 : 502).json({
        success: outcome.status === "success",
        destination: discovery.destination,
        job_id: jobId,
        status: outcome.status,
        urls: submittedUrls,
        candidates,
        total: outcome.total,
        succeeded: outcome.succeeded,
        failed: outcome.failed,
        results: outcome.results,
        error: outcome.status === "success" ? undefined : outcome.error || "Automated crawl failed",
        errors: discovery.errors,
      });
    } catch (err: unknown) {
      handleDiscoveryError(err, res);
    }
  }
);

export default router;
