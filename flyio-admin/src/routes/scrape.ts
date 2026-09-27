import { Router, Request, Response } from "express";
import { v4 as uuidv4 } from "uuid";
import { query } from "../db/pgPool";
import { requireAdminAuth } from "../middleware/requireAdminAuth";
import {
  submitUrlScrape,
  submitSourceScrape,
  getJobStatus,
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
      const urlCount = submittedUrls.length;

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

      // Send to asynchronous scraper service
      const scraperRes = await submitUrlScrape(urls);
      const jobId = scraperRes?.job_id || uuidv4();

      // Create job record in PostgreSQL
      await query(
        "INSERT INTO jobs (id, operation, status) VALUES ($1, 'url_scrape', 'sent')",
        [jobId]
      );
      // The submitted list is recorded on the job itself so its outcome can be
      // reconciled against what was actually asked for. An async submission
      // returns immediately and the background scheduler finalizes the job,
      // and that scheduler is not told what was submitted — so a URL the
      // scraper silently dropped left no trace anywhere while the job still
      // reported success. See processJobOutcome.
      await logEvent(jobId, "created", { url_count: urlCount, urls: submittedUrls });
      await logEvent(jobId, "sent_to_scraper");

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

export default router;
