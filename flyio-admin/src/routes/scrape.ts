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
} from "../services/scraperClient";
import {
  logEvent,
  processJobOutcome,
  waitForJobCompletion,
} from "../services/jobScheduler";
import {
  annotateWithIndexState,
  crawlUrlFor,
  type AnnotatedCandidate,
} from "../services/discovery";

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
 * Renders an upstream error body as a sentence.
 *
 * A FastAPI `detail` is a string for a raised HTTPException but an *array*
 * of {loc, msg} objects for a schema rejection (422). Passing the array
 * straight through put a raw pydantic dump in the API response, so a
 * two-character destination answered with `[{"type":"string_too_short",
 * "loc":["body","destination"],...}]` instead of a sentence.
 */
function describeUpstreamDetail(data: unknown, fallback: string): string {
  const detail = (data as { detail?: unknown } | undefined)?.detail;

  if (typeof detail === "string" && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const parts = detail
      .map((entry) => {
        const e = entry as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(e.loc)
          ? e.loc.filter((p) => p !== "body").join(".")
          : "";
        if (!e.msg) return "";
        return field ? `${field}: ${e.msg}` : e.msg;
      })
      .filter(Boolean);
    if (parts.length > 0) return parts.join("; ");
  }

  return fallback;
}

/**
 * Translates a failure from the discovery call into a response.
 *
 * The status the caller sees has to say whose problem it is, because that
 * decides who gets paged. The scraper answers a misconfigured search
 * provider with a 400 naming the fix ("SEARCH_API_KEY is empty but
 * SEARCH_PROVIDER is 'tavily'"), a bad destination with a 422, and a dead
 * provider with a 502. Collapsing the client errors into 502 would report a
 * typo in a text box as "Bad Gateway" and send someone to check whether the
 * scraper is up.
 */
function handleDiscoveryError(err: unknown, res: Response): void {
  if (axios.isAxiosError(err) && err.response) {
    const status = err.response.status;
    const detail = describeUpstreamDetail(err.response.data, err.message);

    // 401/403 is *this service's* key for the scraper, not the admin user's
    // session. Forwarding it would read as "your login expired" and send
    // someone to the wrong place entirely.
    if (status === 401 || status === 403) {
      res.status(502).json({
        success: false,
        error: "Bad Gateway",
        detail:
          "The scraper service rejected this service's API key. Check that admin's SCRAPER_SERVICE_API_KEY matches the scraper's SERVICE_API_KEY.",
      });
      return;
    }

    // A 404 means the scraper has no /scrape/discover — a version skew
    // between the two services, not anything the caller did.
    if (status === 404) {
      res.status(502).json({
        success: false,
        error: "Bad Gateway",
        detail:
          "The scraper service has no /scrape/discover endpoint. It is likely running a build from before destination discovery was added.",
      });
      return;
    }

    // Every other 4xx is about what the caller sent, so it keeps its status.
    if (status >= 400 && status < 500) {
      res.status(status).json({
        success: false,
        error: "Bad Request",
        detail,
      });
      return;
    }

    res.status(502).json({ success: false, error: "Bad Gateway", detail });
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
// Without `urls`, crawls everything discovery recommends (trusted, and
// either never indexed or stale). With `urls`, crawls exactly that reviewed
// selection from POST /api/admin/discover — see the note in the handler.
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
      const dest = destination.trim();

      let submittedUrls: string[];
      let candidates: AnnotatedCandidate[] | undefined;
      let searchErrors: string[] = [];
      let provenance: Record<string, unknown>;

      if (approvedUrls != null) {
        // An explicit list is a decision the operator already made from the
        // preview, so it is crawled as given and search is not consulted
        // again. It used to be intersected with a fresh discovery run, but
        // search results drift between the preview and the click (and a
        // failed query drops its hits), so approved pages were silently
        // skipped. That intersection guarded nothing: /api/admin/crawl
        // already accepts arbitrary URLs from the same authenticated admin.
        if (
          !Array.isArray(approvedUrls) ||
          approvedUrls.length === 0 ||
          approvedUrls.some((u) => typeof u !== "string")
        ) {
          res.status(400).json({
            success: false,
            error: "Bad Request",
            detail: "Field 'urls', when given, must be a non-empty array of URL strings. Omit it to crawl what discovery recommends.",
          });
          return;
        }
        submittedUrls = [...new Set((approvedUrls as string[]).map((u) => u.trim()).filter(Boolean))];
        const invalidUrls = submittedUrls.filter((u) => !isHttpUrl(u));
        if (submittedUrls.length === 0 || invalidUrls.length > 0) {
          res.status(400).json({
            success: false,
            error: "Bad Request",
            detail: `Not a valid http(s) URL: ${invalidUrls.join(", ") || "(empty)"}.`,
          });
          return;
        }
        provenance = { destination: dest, source: "operator_selection", selected: submittedUrls };
      } else {
        const discovery = await discoverUrls(dest, maxUrls);
        candidates = await annotateWithIndexState(discovery.candidates);
        searchErrors = discovery.errors;
        const selected = candidates.filter((c) => c.recommended);

        if (selected.length === 0) {
          // Not an error: "everything for this destination is already
          // indexed" is the expected steady state, and re-running must be a
          // no-op rather than a duplicate ingest. The candidates come back
          // so the caller can see why nothing was selected and override.
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
            errors: searchErrors,
          });
          return;
        }

        submittedUrls = selected.map(crawlUrlFor);
        provenance = {
          destination: discovery.destination,
          source: "discovery",
          provider: discovery.provider,
          queries: discovery.queries,
          considered: discovery.considered,
          selected: submittedUrls,
          search_errors: searchErrors,
        };
      }

      const jobId = await startUrlCrawlJob(submittedUrls, "auto_scrape");

      // Recorded on the job so the destination that triggered an automated
      // crawl is recoverable afterwards — the jobs table otherwise only knows
      // about URLs, and "why was this page crawled?" has no answer.
      await logEvent(jobId, "auto_discovered", provenance);

      if (isAsync) {
        res.json({
          success: true,
          destination: dest,
          job_id: jobId,
          status: "sent",
          urls: submittedUrls,
          candidates,
          errors: searchErrors,
        });
        return;
      }

      const outcome = await waitForJobCompletion(jobId, {
        expectedUrls: submittedUrls,
      });

      res.status(outcome.status === "success" ? 200 : 502).json({
        success: outcome.status === "success",
        destination: dest,
        job_id: jobId,
        status: outcome.status,
        urls: submittedUrls,
        candidates,
        total: outcome.total,
        succeeded: outcome.succeeded,
        failed: outcome.failed,
        results: outcome.results,
        error: outcome.status === "success" ? undefined : outcome.error || "Automated crawl failed",
        errors: searchErrors,
      });
    } catch (err: unknown) {
      handleDiscoveryError(err, res);
    }
  }
);

export default router;
