import { Router, Request, Response } from "express";
import { v4 as uuidv4 } from "uuid";
import { query } from "../db/pgPool";
import { requireAdminAuth } from "../middleware/requireAdminAuth";
import { env } from "../config/env";
import {
  generatePlan,
  getLLMHealth,
  getQdrantHealth,
  checkServiceKey,
  type LLMGenerateResponse,
} from "../services/llmClient";
import {
  submitUrlScrape,
  submitSourceScrape,
} from "../services/scraperClient";
import {
  waitForJobCompletion,
} from "../services/jobScheduler";
import {
  logRequestEvent,
  pushToLlmStore,
  pushAllToLlmStore,
} from "../services/kbToLlmStore";

const router = Router();

/**
 * Helper to extract URLs from text string using regex.
 */
function extractUrlsFromText(text: string): string[] {
  const urlRegex = /(https?:\/\/[^\s"'<>]+)/g;
  const matches = text.match(urlRegex) || [];
  return Array.from(new Set(matches.map((u) => u.trim())));
}

/**
 * POST /api/admin/llm/generate
 *
 * Full application/orchestration flow:
 * 1. Receives prompt from frontend
 * 2. Generates correlation request_id
 * 3. Saves prompt history in PostgreSQL
 * 4. Calls flyio-ai-llm microservice (POST /v1/api/generate)
 * 5. If data_found -> saves response, returns plan immediately
 * 6. If data_required -> extracts/resolves source URLs -> calls Scraper Service
 *    -> waits for scrape completion -> extracts data into knowledge_base
 *    -> converts to structured JSON -> calls LLM Store API (POST /v1/api/store)
 *    -> retries LLM generation -> saves final response and returns plan
 * 7. Tracks every stage in PostgreSQL request_events table
 */
router.post("/api/admin/llm/generate", requireAdminAuth, async (req: Request, res: Response) => {
  const startTime = Date.now();

  try {
    const { prompt, metadata, urls } = req.body;

    if (!prompt || typeof prompt !== "string" || !prompt.trim()) {
      res.status(400).json({
        success: false,
        error: "Bad Request",
        detail: "Field 'prompt' is required.",
      });
      return;
    }

    // Correlation request_id format (e.g. req_8f7b2c1d4e0a)
    const rawUuid = uuidv4().replace(/-/g, "");
    const requestId = `req_${rawUuid.substring(0, 16)}`;

    // 1. Save prompt to prompt_history
    await query(
      `INSERT INTO prompt_history (request_id, prompt_text, status, metadata)
       VALUES ($1, $2, 'pending', $3)`,
      [requestId, prompt.trim(), JSON.stringify(metadata || {})]
    );

    // 2. Log initial event
    await logRequestEvent(requestId, "prompt_received", {
      service: "admin",
      status: "success",
      message: `Prompt received: "${prompt.trim().substring(0, 80)}..."`,
      metadata: { prompt_length: prompt.length, source: "admin_api" },
    });

    // 3. First call to LLM Generate API
    await logRequestEvent(requestId, "llm_request_started", {
      service: "admin",
      status: "info",
      message: `Calling LLM Generate API for prompt query`,
    });

    let llmResponse: LLMGenerateResponse;
    try {
      llmResponse = await generatePlan(requestId, prompt.trim(), metadata);
    } catch (llmErr: unknown) {
      const e = llmErr as Error;
      await logRequestEvent(requestId, "llm_request_failed", {
        service: "admin",
        status: "error",
        message: `Initial call to LLM service failed: ${e.message}`,
      });

      await query(
        `UPDATE prompt_history SET status = 'failed', response_data = $1, updated_at = NOW() WHERE request_id = $2`,
        [JSON.stringify({ error: e.message }), requestId]
      );

      res.status(502).json({
        success: false,
        request_id: requestId,
        error: "LLM Service Error",
        detail: `Failed to reach LLM service at ${env.LLM_SERVICE_URL}: ${e.message}`,
      });
      return;
    }

    // ── CASE A: Data exists in Qdrant -> Plan generated ──
    if (llmResponse.status === "data_found" || (llmResponse.data_found && llmResponse.plan)) {
      await query(
        `UPDATE prompt_history 
         SET status = 'completed', response_data = $1, updated_at = NOW() 
         WHERE request_id = $2`,
        [JSON.stringify(llmResponse), requestId]
      );

      await logRequestEvent(requestId, "plan_generation_completed", {
        service: "admin",
        status: "success",
        message: "Travel plan generated successfully from existing vector database context",
      });

      res.json({
        success: true,
        request_id: requestId,
        status: "data_found",
        plan: llmResponse.plan,
        results: llmResponse.results || [],
        message: llmResponse.message || "Plan generated successfully",
        execution_time_ms: Date.now() - startTime,
      });
      return;
    }

    // ── CASE B: Data is missing -> Scrape, Store in Vector DB, Retry LLM ──
    if (llmResponse.status === "data_required" || llmResponse.data_required) {
      await query(
        `UPDATE prompt_history SET status = 'data_required', updated_at = NOW() WHERE request_id = $1`,
        [requestId]
      );

      await logRequestEvent(requestId, "data_required", {
        service: "admin",
        status: "warning",
        message: "LLM reported missing data in Qdrant. Initiating source data ingestion pipeline.",
      });

      // Resolve URLs to scrape (Option B: from request body, prompt text, or default sources)
      let targetUrls: string[] = [];
      if (Array.isArray(urls) && urls.length > 0) {
        targetUrls = urls.map(String).filter((u) => u.startsWith("http"));
      } else if (typeof urls === "string" && urls.trim()) {
        targetUrls = urls.split("\n").map((u) => u.trim()).filter((u) => u.startsWith("http"));
      }

      if (targetUrls.length === 0) {
        targetUrls = extractUrlsFromText(prompt);
      }

      if (targetUrls.length === 0 && env.DEFAULT_SOURCE_URLS.length > 0) {
        targetUrls = [...env.DEFAULT_SOURCE_URLS];
      }

      // Step 4.1: Trigger Scraper Service
      const scrapeJobId = uuidv4();
      await query(
        "INSERT INTO jobs (id, operation, status) VALUES ($1, 'llm_source_scrape', 'created')",
        [scrapeJobId]
      );

      if (targetUrls.length > 0) {
        await logRequestEvent(requestId, "scrape_requested", {
          service: "admin",
          status: "info",
          message: `Submitting ${targetUrls.length} source URL(s) to Scraper Service`,
          metadata: { urls: targetUrls, job_id: scrapeJobId },
        });

        await submitUrlScrape(targetUrls.join("\n"), scrapeJobId);
      } else {
        await logRequestEvent(requestId, "scrape_requested", {
          service: "admin",
          status: "info",
          message: "No specific URLs provided. Triggering configured tourism sources scrape",
          metadata: { job_id: scrapeJobId },
        });

        await submitSourceScrape(scrapeJobId);
      }

      // Step 4.2: Wait for Scraper job completion (stores results into knowledge_base)
      const scrapeOutcome = await waitForJobCompletion(scrapeJobId, {
        expectedUrls: targetUrls && targetUrls.length > 0 ? targetUrls : undefined,
      });

      if (scrapeOutcome.status !== "success") {
        await logRequestEvent(requestId, "scrape_failed", {
          service: "admin",
          status: "error",
          message: `Scraper operation failed: ${scrapeOutcome.error}`,
          metadata: { job_id: scrapeJobId },
        });

        await query(
          `UPDATE prompt_history SET status = 'failed', response_data = $1, updated_at = NOW() WHERE request_id = $2`,
          [JSON.stringify({ error: `Scraping failed: ${scrapeOutcome.error}` }), requestId]
        );

        res.status(502).json({
          success: false,
          request_id: requestId,
          status: "scrape_failed",
          error: "Scraper Service failed to fetch required source data.",
          detail: scrapeOutcome.error,
        });
        return;
      }

      await logRequestEvent(requestId, "extraction_completed", {
        service: "admin",
        status: "success",
        message: `Extracted data from ${scrapeOutcome.succeeded} source URL(s) into knowledge base`,
        metadata: { total: scrapeOutcome.total, succeeded: scrapeOutcome.succeeded },
      });

      // Step 4.3: Convert Knowledge Base data to JSON & Push to LLM Store API
      const successfulUrls = (scrapeOutcome.results || [])
        .filter((r): r is typeof r & { url: string } => r.status === "success" && typeof r.url === "string")
        .map((r) => r.url);

      const urlsToStore = successfulUrls.length > 0 ? successfulUrls : targetUrls;

      for (const sourceUrl of urlsToStore) {
        try {
          await pushToLlmStore(sourceUrl, requestId);
        } catch (storeErr: unknown) {
          const err = storeErr as Error;
          console.warn(`[LLM Store Warning] Failed to push ${sourceUrl}: ${err.message}`);
        }
      }

      // Step 4.4: Retry LLM Generate Plan
      await logRequestEvent(requestId, "llm_retry_started", {
        service: "admin",
        status: "info",
        message: "Retrying LLM plan generation with newly ingested vector database knowledge",
      });

      let retryResponse: LLMGenerateResponse;
      try {
        retryResponse = await generatePlan(requestId, prompt.trim(), {
          ...metadata,
          retried_after_scrape: true,
          scraped_url_count: urlsToStore.length,
        });
      } catch (retryErr: unknown) {
        const err = retryErr as Error;
        await logRequestEvent(requestId, "llm_retry_failed", {
          service: "admin",
          status: "error",
          message: `Retry call to LLM service failed: ${err.message}`,
        });

        await query(
          `UPDATE prompt_history SET status = 'failed', response_data = $1, updated_at = NOW() WHERE request_id = $2`,
          [JSON.stringify({ error: err.message }), requestId]
        );

        res.status(502).json({
          success: false,
          request_id: requestId,
          error: "LLM Service Error during retry",
          detail: err.message,
        });
        return;
      }

      const isCompleted = retryResponse.status === "data_found" || Boolean(retryResponse.plan);

      await query(
        `UPDATE prompt_history 
         SET status = $1, response_data = $2, updated_at = NOW() 
         WHERE request_id = $3`,
        [isCompleted ? "completed" : "data_required", JSON.stringify(retryResponse), requestId]
      );

      await logRequestEvent(requestId, "plan_generation_completed", {
        service: "admin",
        status: isCompleted ? "success" : "warning",
        message: isCompleted
          ? "Travel plan generated successfully after scraper and vector database ingestion"
          : retryResponse.message || "Retry completed",
      });

      res.json({
        success: isCompleted,
        request_id: requestId,
        status: retryResponse.status,
        plan: retryResponse.plan || null,
        results: retryResponse.results || [],
        message: retryResponse.message,
        scraped_sources: urlsToStore,
        execution_time_ms: Date.now() - startTime,
      });
      return;
    }

    // ── CASE C: Generation failed ──
    await query(
      `UPDATE prompt_history SET status = 'failed', response_data = $1, updated_at = NOW() WHERE request_id = $2`,
      [JSON.stringify(llmResponse), requestId]
    );

    await logRequestEvent(requestId, "plan_generation_failed", {
      service: "admin",
      status: "error",
      message: llmResponse.message || "LLM failed to generate plan",
      metadata: { error: llmResponse.error },
    });

    res.status(502).json({
      success: false,
      request_id: requestId,
      status: "generation_failed",
      error: llmResponse.error || "LLM plan generation failed",
      detail: llmResponse.message,
    });
  } catch (err: unknown) {
    const e = err as Error;
    console.error("[LLM Generate Route Error]", e);
    res.status(500).json({
      success: false,
      error: "Internal Server Error",
      detail: e.message,
    });
  }
});

/**
 * POST /api/admin/llm/store
 * Manually pushes existing knowledge base chunks to the LLM Store API.
 * Body: { source_url?: string, all?: boolean }
 */
router.post("/api/admin/llm/store", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { source_url, all } = req.body;
    const rawUuid = uuidv4().replace(/-/g, "");
    const requestId = `req_${rawUuid.substring(0, 16)}`;

    if (all === true) {
      // Execute in background
      pushAllToLlmStore(requestId).catch(e => console.error("[LLM Store Background] pushAllToLlmStore failed:", e));
      
      res.json({
        success: true,
        request_id: requestId,
        message: "Background ingestion started for all URLs.",
      });
      return;
    }

    if (!source_url || typeof source_url !== "string") {
      res.status(400).json({
        success: false,
        error: "Bad Request",
        detail: "Either 'source_url' (string) or 'all: true' must be provided.",
      });
      return;
    }

    // Awaited, so the caller learns whether the chunks actually reached
    // Qdrant. This used to fire in the background and answer 200 "ingestion
    // started" no matter what happened next, with the real outcome going only
    // to container stdout — a URL could fail to ingest on every attempt and
    // this endpoint would keep reporting success. A single URL is well inside
    // the LLM client's request timeout, so there is nothing to gain by
    // detaching it.
    //
    // The outcome is reported in the body with a 200 rather than as a 5xx
    // status. The reverse proxy in front of this service replaces the body of
    // any 5xx response with a plain "error code: 502", so a failure returned
    // that way reaches the caller with the reason stripped off — which is
    // exactly the information they need. This matches how the crawl endpoints
    // already report per-URL outcomes.
    try {
      const result = await pushToLlmStore(source_url.trim(), requestId);

      res.json({
        success: result.success,
        request_id: requestId,
        result,
        message: result.message,
      });
    } catch (pushErr: unknown) {
      const e = pushErr as Error;
      console.error(`[LLM Store] pushToLlmStore failed for ${source_url}:`, e);
      res.json({
        success: false,
        request_id: requestId,
        source_url: source_url.trim(),
        error: "Vector ingestion failed",
        detail: e.message,
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
});

/**
 * GET /api/admin/llm/health
 * Checks connectivity to LLM service and Qdrant vector database.
 */
router.get("/api/admin/llm/health", requireAdminAuth, async (_req: Request, res: Response) => {
  try {
    const [llmHealth, qdrantHealth, keyCheck] = await Promise.allSettled([
      getLLMHealth(),
      getQdrantHealth(),
      checkServiceKey(),
    ]);

    const isLlmOk = llmHealth.status === "fulfilled" && llmHealth.value.status === "healthy";
    const isQdrantOk = qdrantHealth.status === "fulfilled" && qdrantHealth.value.connected === true;
    // The key is part of being healthy: reachable-but-unauthorised means
    // every store and generate call fails, which is not a healthy state to
    // report as green.
    const isKeyOk = keyCheck.status === "fulfilled" && keyCheck.value.valid;

    res.json({
      success: isLlmOk && isQdrantOk && isKeyOk,
      service_key: keyCheck.status === "fulfilled"
        ? keyCheck.value
        : { valid: false, detail: "Service key check failed to run." },
      llm_service: {
        url: env.LLM_SERVICE_URL,
        status: llmHealth.status === "fulfilled" ? llmHealth.value : { error: "Unreachable" },
      },
      qdrant: {
        status: qdrantHealth.status === "fulfilled" ? qdrantHealth.value : { error: "Unreachable" },
      },
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Health Check Failed", detail: e.message });
  }
});

export default router;
