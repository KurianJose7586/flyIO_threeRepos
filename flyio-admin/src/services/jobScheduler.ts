import { env } from "../config/env";
import { query } from "../db/pgPool";
import { pushToLlmStore } from "./kbToLlmStore";
import { getJobStatus, type ScraperResult, type ScraperStatusResponse } from "./scraperClient";

export interface JobCompletionResult {
  job_id: string;
  status: "success" | "failed";
  total: number;
  succeeded: number;
  failed: number;
  results: ScraperResult[];
  error?: string;
}

/** Per-URL outcome of the vector-DB ingestion that follows a successful scrape. */
export interface UrlSummary {
  url: string;
  status: "success" | "failed";
  chunks: number;
  error?: string;
  vector_status?: "stored" | "skipped" | "failed";
  vector_stored?: number;
  vector_error?: string;
}

export async function logEvent(
  jobId: string,
  eventType: string,
  detail?: unknown
): Promise<void> {
  await query(
    "INSERT INTO job_events (job_id, event_type, detail) VALUES ($1, $2, $3)",
    [jobId, eventType, detail ? JSON.stringify(detail) : null]
  );
}

export async function updateJobStatus(jobId: string, status: string): Promise<void> {
  await query(
    "UPDATE jobs SET status = $1, updated_at = NOW() WHERE id = $2",
    [status, jobId]
  );
}

export async function storeResults(
  jobId: string,
  results: ScraperResult[]
): Promise<void> {
  // Compute job age in ms for duration tracking
  const jobRow = await query("SELECT created_at FROM jobs WHERE id = $1", [jobId]);
  const jobCreatedAt: Date = jobRow.rows[0]?.created_at ? new Date(jobRow.rows[0].created_at) : new Date();
  const processedHistoryUrls = new Set<string>();
  const cleanedUrls = new Set<string>();

  for (const r of results) {
    const itemUrl = r.source_url || r.url;
    if (!itemUrl) continue;

    const isSuccess = r.status === "success" || (!r.status && !r.error);

    if (isSuccess) {
      // Clear previous chunks for this URL so that re-crawling refreshes instead of duplicating
      if (!cleanedUrls.has(itemUrl)) {
        cleanedUrls.add(itemUrl);
        await query("DELETE FROM knowledge_base WHERE source_url = $1", [itemUrl]);
      }

      // Handle either nested chunks array or direct single chunk object
      const chunks = Array.isArray((r as any).chunks) && (r as any).chunks.length > 0
        ? (r as any).chunks
        : [r];

      for (let idx = 0; idx < chunks.length; idx++) {
        const chunk = chunks[idx];
        const pageTitle = chunk.title || chunk.page_title || r.title || (r as any).page_title || "";
        const sectionPath = chunk.section_path || r.section_path || "";
        const chunkIndex = typeof chunk.chunk_index === "number" ? chunk.chunk_index : (typeof r.chunk_index === "number" ? r.chunk_index : idx);
        const sanitize = (str: string) => (str ? str.replace(/\0/g, "").replace(/\u0000/g, "") : "");
        const contentText = sanitize(chunk.content || chunk.content_text || r.content || (r as any).content_text || "");
        const rawHtml = chunk.content_html || (chunk.content ? `<p>${chunk.content}</p>` : (r as any).content_html || (contentText ? `<p>${contentText}</p>` : ""));
        const contentHtml = sanitize(rawHtml);

        const chunkObj = {
          source_url: itemUrl,
          page_title: sanitize(pageTitle),
          section_path: sanitize(sectionPath),
          chunk_index: chunkIndex,
          content_text: contentText,
          content_html: contentHtml,
        };

        const metadataObj = {
          title: sanitize(pageTitle),
          section_path: sanitize(sectionPath),
          chunk_index: chunkIndex,
        };

        await query(
          `INSERT INTO knowledge_base (source_url, chunk_data, extracted_content, extracted_metadata, job_id)
           VALUES ($1, $2, $3, $4, $5)`,
          [
            itemUrl,
            JSON.stringify(chunkObj),
            contentText,
            JSON.stringify(metadataObj),
            jobId,
          ]
        );
      }

      // Record successful URL attempt in history audit log (once per URL)
      if (!processedHistoryUrls.has(itemUrl)) {
        processedHistoryUrls.add(itemUrl);
        const durationMs = Math.round(Date.now() - jobCreatedAt.getTime());
        await query(
          `INSERT INTO history (url, status, job_id, duration_ms) VALUES ($1, 'success', $2, $3)`,
          [itemUrl, jobId, durationMs]
        );
      }
    } else {
      // Record failed URL attempt in history audit log (once per URL)
      if (!processedHistoryUrls.has(itemUrl)) {
        processedHistoryUrls.add(itemUrl);
        const durationMs = Math.round(Date.now() - jobCreatedAt.getTime());
        // Capture the full error — not just robots.txt but any scraper error
        const errorMsg = r.error || (r as any).error_message || (r as any).reason || "Scraping failed";
        await query(
          `INSERT INTO history (url, status, error_message, job_id, duration_ms) VALUES ($1, 'failed', $2, $3, $4)`,
          [itemUrl, errorMsg, jobId, durationMs]
        );
      }
    }
  }
}

/**
 * Pushes the chunks a completed scrape just wrote into knowledge_base on into
 * the vector database, one source URL at a time.
 *
 * Crawling used to stop at Postgres: nothing on this path called the LLM
 * Store API, and the only two callers that did were the scrape-and-retry
 * fallback inside POST /api/admin/llm/generate and the manual
 * POST /api/admin/llm/store, which no part of the UI invokes. A URL crawled
 * from the Knowledge Base page therefore never became searchable, while the
 * chunk view still displayed a qdrant_point_id for it — an ID computed from
 * the chunk's own fields, so it looked real and simply resolved to nothing.
 *
 * Ingestion failures are reported per URL but do not fail the job: the scrape
 * itself succeeded and its chunks are committed, so the URL can be retried
 * with POST /api/admin/llm/store without re-crawling. What they must not do
 * is pass silently, which is how this went unnoticed in the first place.
 */
async function ingestScrapedUrls(
  jobId: string,
  urlSummaryMap: Map<string, UrlSummary>
): Promise<void> {
  for (const summary of urlSummaryMap.values()) {
    if (summary.status !== "success") continue;

    try {
      const push = await pushToLlmStore(summary.url, `job_${jobId}`);

      if (push.success) {
        summary.vector_status = "stored";
        summary.vector_stored = push.stored_count;
        await logEvent(jobId, "vector_ingested", {
          url: summary.url,
          stored_count: push.stored_count,
        });
      } else {
        // pushToLlmStore reports "no chunks found" as an unsuccessful result
        // rather than throwing — surface it as its own state, since nothing
        // was stored but nothing is broken either.
        summary.vector_status = "skipped";
        summary.vector_stored = 0;
        summary.vector_error = push.message;
        await logEvent(jobId, "vector_ingest_skipped", {
          url: summary.url,
          reason: push.message,
        });
      }
    } catch (err: unknown) {
      const e = err as Error;
      const message = e.message || String(err);
      summary.vector_status = "failed";
      summary.vector_stored = 0;
      summary.vector_error = message;
      console.error(`[JobScheduler] Vector ingestion failed for ${summary.url}:`, e);
      await logEvent(jobId, "vector_ingest_failed", {
        url: summary.url,
        error: message,
      });
    }
  }
}

const inFlightJobPromises = new Map<string, Promise<JobCompletionResult>>();

export function processJobOutcome(
  jobId: string,
  scraperStatus: ScraperStatusResponse,
  expectedUrls?: string[]
): Promise<JobCompletionResult> {
  const existingPromise = inFlightJobPromises.get(jobId);
  if (existingPromise) {
    return existingPromise;
  }

  const jobPromise = (async (): Promise<JobCompletionResult> => {
    try {
      // Check if job was already finalized in DB
      const check = await query("SELECT status FROM jobs WHERE id = $1", [jobId]);
      const currentStatus = check.rows[0]?.status;

      if (currentStatus === "success" || currentStatus === "failed") {
        const historyRows = await query(
          "SELECT url, status, error_message FROM history WHERE job_id = $1",
          [jobId]
        );
        const kbChunks = await query(
          `SELECT source_url,
                  COUNT(*) as cnt,
                  COUNT(qdrant_point_id) as ingested
           FROM knowledge_base WHERE job_id = $1 GROUP BY source_url`,
          [jobId]
        );
        const chunkMap = new Map<string, number>();
        const ingestedMap = new Map<string, number>();
        for (const row of kbChunks.rows) {
          chunkMap.set(row.source_url, parseInt(row.cnt, 10));
          ingestedMap.set(row.source_url, parseInt(row.ingested, 10));
        }

        const summaryResults: UrlSummary[] = historyRows.rows.map((h) => {
          const chunks = chunkMap.get(h.url) || 0;
          const ingested = ingestedMap.get(h.url) || 0;
          return {
            url: h.url,
            status: h.status as "success" | "failed",
            chunks,
            error: h.error_message || undefined,
            // Replayed from what is on disk — this branch returns a job that
            // was already finalized, so no ingestion is re-attempted here.
            vector_status: h.status !== "success" ? undefined : ingested > 0 ? "stored" : "failed",
            vector_stored: ingested,
          };
        });

        const total = summaryResults.length;
        const succeeded = summaryResults.filter((s) => s.status === "success").length;
        const failed = total - succeeded;

        return {
          job_id: jobId,
          status: currentStatus as "success" | "failed",
          total,
          succeeded,
          failed,
          results: summaryResults as any,
          error: currentStatus === "failed" ? (summaryResults[0]?.error || "Job failed") : undefined,
        };
      }

      const rawResults = scraperStatus.results || [];

      // Recover the submitted URL list when the caller did not pass one. Only
      // the synchronous /api/admin/crawl path supplies expectedUrls, but the
      // Knowledge Base page submits asynchronously and the background
      // scheduler finalizes those jobs — so the reconciliation below, which
      // exists precisely to catch a URL the scraper returned nothing for,
      // never ran on the path that the UI actually uses. A dropped URL then
      // produced no history row, no knowledge_base rows and no error, while
      // the job reported success.
      let effectiveExpectedUrls = expectedUrls;
      if (!effectiveExpectedUrls || effectiveExpectedUrls.length === 0) {
        const createdEvent = await query(
          `SELECT detail FROM job_events
           WHERE job_id = $1 AND event_type = 'created'
           ORDER BY created_at ASC LIMIT 1`,
          [jobId]
        );
        const recorded = createdEvent.rows[0]?.detail?.urls;
        if (Array.isArray(recorded) && recorded.length > 0) {
          effectiveExpectedUrls = recorded.filter((u: unknown): u is string => typeof u === "string");
        }
      }

      if (scraperStatus.status === "success") {
        try {
          await storeResults(jobId, rawResults);
        } catch (storeErr: any) {
          console.error(`[JobScheduler Error] Failed to store results for job ${jobId}:`, storeErr);
          const storeErrMsg = storeErr.message || String(storeErr);
          await updateJobStatus(jobId, "failed");
          await logEvent(jobId, "failed", { error: storeErrMsg });
          return {
            job_id: jobId,
            status: "failed",
            total: rawResults.length,
            succeeded: 0,
            failed: rawResults.length,
            results: [],
            error: `Storage error: ${storeErrMsg}`,
          };
        }
        // The job is deliberately left un-finalized until vector ingestion
        // below has run. The crawler UI stops polling as soon as the job
        // reaches a terminal status, so marking it 'success' here would let
        // it stop while chunks were still being pushed to Qdrant and report
        // a URL as missing from the vector DB that was moments from landing.

        // Summarize into per-URL result items so frontend receives clean URL cards
        const urlSummaryMap = new Map<string, UrlSummary>();
        for (const r of rawResults) {
          const itemUrl = r.source_url || r.url || "Unknown URL";
          const isSuccess = r.status === "success" || (!r.status && !r.error);
          const existing = urlSummaryMap.get(itemUrl) || {
            url: itemUrl,
            status: isSuccess ? "success" : "failed",
            chunks: 0,
            error: r.error,
          };
          if (isSuccess) {
            existing.chunks += 1;
            existing.status = "success";
          } else {
            existing.error = r.error || existing.error;
          }
          urlSummaryMap.set(itemUrl, existing);
        }

        // Ensure any expected URLs that yielded 0 chunks / were skipped get reported as failed
        if (effectiveExpectedUrls && effectiveExpectedUrls.length > 0) {
          for (const u of effectiveExpectedUrls) {
            const normalized = u.trim();
            if (normalized && !urlSummaryMap.has(normalized)) {
              urlSummaryMap.set(normalized, {
                url: normalized,
                status: "failed",
                chunks: 0,
                error: "No content extracted or URL was blocked/skipped",
              });
              await query(
                `INSERT INTO history (url, status, error_message, job_id) VALUES ($1, 'failed', $2, $3)`,
                [normalized, "No content extracted or URL was blocked/skipped", jobId]
              );
            }
          }
        }

        await ingestScrapedUrls(jobId, urlSummaryMap);

        const summaryResults = Array.from(urlSummaryMap.values());
        const totalUrls = summaryResults.length;
        const succeededUrls = summaryResults.filter((s) => s.status === "success").length;
        const failedUrls = totalUrls - succeededUrls;

        await logEvent(jobId, "stored", { total: totalUrls, succeeded: succeededUrls, failed: failedUrls });

        const isOverallSuccess = totalUrls === 0 || succeededUrls > 0;
        await updateJobStatus(jobId, isOverallSuccess ? "success" : "failed");

        return {
          job_id: jobId,
          status: isOverallSuccess ? "success" : "failed",
          total: totalUrls,
          succeeded: succeededUrls,
          failed: failedUrls,
          results: summaryResults as any,
          error: !isOverallSuccess ? (summaryResults[0]?.error || "Scraping failed for all URLs") : undefined,
        };
      }

      // Failed outcome
      // The scraper reports a failed job as a whole, with no per-URL rows. The
      // crawler UI builds its cards from history, so without these rows every
      // card fell back to a generic "failed or produced no output" and the
      // scraper's actual error was only visible in job_events. Written before
      // the job is finalized so the UI's last poll already sees them.
      const jobError = scraperStatus.error || "Job failed on scraper service";
      const failedResults: UrlSummary[] = [];
      for (const u of effectiveExpectedUrls ?? []) {
        const normalized = u.trim();
        if (!normalized) continue;
        failedResults.push({ url: normalized, status: "failed", chunks: 0, error: jobError });
        await query(
          `INSERT INTO history (url, status, error_message, job_id) VALUES ($1, 'failed', $2, $3)`,
          [normalized, jobError, jobId]
        );
      }
      await updateJobStatus(jobId, "failed");
      await logEvent(jobId, "failed", { error: scraperStatus.error });
      return {
        job_id: jobId,
        status: "failed",
        total: failedResults.length,
        succeeded: 0,
        failed: failedResults.length,
        results: failedResults as any,
        error: jobError,
      };
    } finally {
      inFlightJobPromises.delete(jobId);
    }
  })();

  inFlightJobPromises.set(jobId, jobPromise);
  return jobPromise;
}

/**
 * Repeatedly checks scraper job status in the background until the job reaches
 * 'success' or 'failed', allowing synchronous endpoints to wait and return the final result.
 */
export async function waitForJobCompletion(
  jobId: string,
  options?: {
    pollIntervalMs?: number;
    timeoutMs?: number;
    expectedUrls?: string[];
  }
): Promise<JobCompletionResult> {
  const pollInterval = options?.pollIntervalMs ?? env.SCRAPER_POLL_INTERVAL_MS;
  const timeout = options?.timeoutMs ?? env.SCRAPER_JOB_TIMEOUT_MS;
  const expectedUrls = options?.expectedUrls;
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    if (inFlightJobPromises.has(jobId)) {
      return await inFlightJobPromises.get(jobId)!;
    }

    // Check DB in case background scheduler completed it
    const check = await query("SELECT status FROM jobs WHERE id = $1", [jobId]);
    if (check.rows[0]?.status === "success" || check.rows[0]?.status === "failed") {
      return await processJobOutcome(jobId, { status: check.rows[0].status }, expectedUrls);
    }

    try {
      const scraperStatus = await getJobStatus(jobId);

      if (scraperStatus.status === "success" || scraperStatus.status === "failed") {
        return await processJobOutcome(jobId, scraperStatus, expectedUrls);
      }

      await logEvent(jobId, "polled", { status: scraperStatus.status });
    } catch (pollErr: unknown) {
      const err = pollErr as Error;
      await logEvent(jobId, "poll_error", { message: err.message });
    }

    await new Promise((resolve) => setTimeout(resolve, pollInterval));
  }

  // Timeout reached
  const timeoutErr = `Scraper job timed out after ${timeout}ms`;
  await updateJobStatus(jobId, "failed");
  await logEvent(jobId, "timeout", { message: timeoutErr });

  return {
    job_id: jobId,
    status: "failed",
    total: 0,
    succeeded: 0,
    failed: 0,
    results: [],
    error: timeoutErr,
  };
}

let schedulerTimer: NodeJS.Timeout | null = null;

/**
 * Background scheduler that periodically checks any pending/running jobs in PostgreSQL.
 */
export function startBackgroundJobScheduler(): void {
  if (schedulerTimer) return;

  const interval = env.SCRAPER_POLL_INTERVAL_MS || 5000;
  console.log(`[JobScheduler] Background scheduler active (poll interval: ${interval}ms)`);

  schedulerTimer = setInterval(async () => {
    try {
      const pendingJobs = await query(
        `SELECT id FROM jobs 
         WHERE status IN ('created', 'sent', 'pending', 'running') 
           AND created_at > NOW() - INTERVAL '1 hour'
         LIMIT 10`
      );

      for (const row of pendingJobs.rows) {
        const jobId = row.id;
        // If synchronous waiter is already actively processing or awaiting this job, skip background poll
        if (inFlightJobPromises.has(jobId)) {
          continue;
        }
        try {
          const scraperStatus = await getJobStatus(jobId);
          if (scraperStatus.status === "success" || scraperStatus.status === "failed") {
            await processJobOutcome(jobId, scraperStatus);
            console.log(`[JobScheduler] Finalized background job ${jobId} -> ${scraperStatus.status}`);
          } else if (scraperStatus.status && scraperStatus.status !== row.status) {
            await updateJobStatus(jobId, scraperStatus.status);
          }
        } catch {
          // Ignore transient poll errors during background cycle
        }
      }
    } catch {
      // Ignore background cycle DB errors
    }
  }, interval);
}

export function stopBackgroundJobScheduler(): void {
  if (schedulerTimer) {
    clearInterval(schedulerTimer);
    schedulerTimer = null;
    console.log("[JobScheduler] Background scheduler stopped");
  }
}

