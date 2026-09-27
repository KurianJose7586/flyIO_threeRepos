import { env } from "../config/env";
import { query } from "../db/pgPool";
import { storeDocuments, type LLMDocumentItem, type LLMStoreResponse } from "./llmClient";

/**
 * Logs a structured event to the cross-service request_events table.
 */
export async function logRequestEvent(
  requestId: string,
  eventType: string,
  options?: {
    service?: string;
    status?: "info" | "success" | "warning" | "error" | string;
    message?: string;
    metadata?: Record<string, unknown>;
  }
): Promise<void> {
  try {
    await query(
      `INSERT INTO request_events (request_id, service, event_type, status, message, metadata)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        requestId,
        options?.service || "admin",
        eventType,
        options?.status || "info",
        options?.message || null,
        options?.metadata ? JSON.stringify(options.metadata) : JSON.stringify({}),
      ]
    );
  } catch (err: unknown) {
    // Fail-safe: logging failure should not crash the main pipeline
    console.error(`[EventLog Error] Failed to log event ${eventType} for ${requestId}:`, err);
  }
}

export interface PreparedKbDocuments {
  documents: LLMDocumentItem[];
  /** knowledge_base.id for each entry of `documents`, in the same order. */
  kbIds: number[];
}

/**
 * Queries knowledge_base for all chunks of a given source_url
 * and transforms them into LLMDocumentItem structures for Qdrant ingestion.
 *
 * Returns the originating knowledge_base row IDs alongside the documents so
 * the caller can write the point IDs the Store API returns back onto the
 * right rows — see pushToLlmStore.
 */
export async function prepareDocumentsFromKB(sourceUrl: string): Promise<PreparedKbDocuments> {
  const result = await query(
    `SELECT
       id,
       source_url,
       chunk_data,
       extracted_content,
       extracted_metadata
     FROM knowledge_base
     WHERE source_url = $1
     ORDER BY COALESCE((chunk_data->>'chunk_index')::int, (extracted_metadata->>'chunk_index')::int, 0) ASC`,
    [sourceUrl]
  );

  const documents: LLMDocumentItem[] = [];
  const kbIds: number[] = [];

  for (const row of result.rows) {
    const chunkData = row.chunk_data || {};
    const metadata = row.extracted_metadata || {};

    const text =
      chunkData.content_text ||
      row.extracted_content ||
      chunkData.text ||
      "";

    if (!text || !text.trim()) continue;

    const pageTitle = chunkData.page_title || metadata.title || "";
    const sectionPath = chunkData.section_path || metadata.section_path || "";
    const chunkIndex = typeof chunkData.chunk_index === "number"
      ? chunkData.chunk_index
      : (typeof metadata.chunk_index === "number" ? metadata.chunk_index : 0);
    const contentHtml = chunkData.content_html || "";

    documents.push({
      text: text.trim(),
      // Top-level fields are what flyio-ai-llm's StoreDocumentItem reads
      // directly; `metadata` is kept as-is so the stored payload.metadata
      // stays identical to what previously ingested points carry.
      title: pageTitle || undefined,
      section_path: sectionPath,
      chunk_index: chunkIndex,
      content_html: contentHtml || undefined,
      metadata: {
        source_url: row.source_url,
        title: pageTitle,
        section_path: sectionPath,
        chunk_index: chunkIndex,
      },
      source_url: row.source_url,
    });
    kbIds.push(Number(row.id));
  }

  return { documents, kbIds };
}

/**
 * Writes the point IDs returned by the Store API back onto their
 * knowledge_base rows, so the admin UI can report what is genuinely in
 * Qdrant instead of a recomputed guess.
 *
 * The Store API returns document_ids in the order documents were sent, so a
 * length mismatch means the mapping is not trustworthy (e.g. the service
 * re-split the input) — in that case nothing is written rather than
 * associating chunks with the wrong points.
 */
async function persistQdrantPointIds(kbIds: number[], pointIds: string[]): Promise<void> {
  if (kbIds.length === 0 || kbIds.length !== pointIds.length) {
    if (pointIds.length > 0) {
      console.warn(
        `[LLM Store] Skipping qdrant_point_id write: sent ${kbIds.length} chunk(s) but got ${pointIds.length} point ID(s) back.`
      );
    }
    return;
  }

  await query(
    `UPDATE knowledge_base kb
     SET qdrant_point_id = v.point_id
     FROM (SELECT UNNEST($1::bigint[]) AS id, UNNEST($2::text[]) AS point_id) v
     WHERE kb.id = v.id`,
    [kbIds, pointIds]
  );
}

export interface PushResult {
  source_url: string;
  document_count: number;
  stored_count: number;
  success: boolean;
  message?: string;
}

/**
 * Transforms chunks from knowledge_base for a source URL and pushes them
 * into flyio-ai-llm's Store API (POST /v1/api/store) with mode='pre_chunked'.
 */
export async function pushToLlmStore(
  sourceUrl: string,
  requestId: string
): Promise<PushResult> {
  await logRequestEvent(requestId, "store_workflow_started", {
    service: "admin",
    status: "info",
    message: `Preparing knowledge base chunks for ${sourceUrl} to send to LLM Store`,
    metadata: { source_url: sourceUrl },
  });

  const { documents, kbIds } = await prepareDocumentsFromKB(sourceUrl);

  if (documents.length === 0) {
    await logRequestEvent(requestId, "store_workflow_skipped", {
      service: "admin",
      status: "warning",
      message: `No knowledge base content found for ${sourceUrl}`,
      metadata: { source_url: sourceUrl },
    });
    return {
      source_url: sourceUrl,
      document_count: 0,
      stored_count: 0,
      success: false,
      message: `No chunks found in knowledge_base for URL: ${sourceUrl}`,
    };
  }

  await logRequestEvent(requestId, "json_prepared", {
    service: "admin",
    status: "success",
    message: `Prepared ${documents.length} structured JSON documents for ${sourceUrl}`,
    metadata: { source_url: sourceUrl, count: documents.length },
  });

  // Sent in batches rather than as one call. The LLM service embeds an entire
  // request before responding — roughly 4s per chunk on the development
  // deployment — while the reverse proxy in front of it closes the connection
  // after ~90s. A 27-chunk page sent whole therefore fails from this side
  // *after* the service has already stored the points, so the point IDs come
  // back to nobody and the chunks look un-ingested despite existing in Qdrant.
  //
  // Each batch is persisted as it lands, so a failure partway through keeps
  // whatever already succeeded and a retry only redoes the rest. Point IDs are
  // deterministic, so re-sending a batch updates its points in place.
  const batchSize = env.LLM_STORE_BATCH_SIZE;
  const totalChunks = documents.length;
  let storedCount = 0;
  let lastMessage: string | undefined;

  try {
    for (let offset = 0; offset < documents.length; offset += batchSize) {
      const batch = documents.slice(offset, offset + batchSize).map((doc) => ({
        ...doc,
        // The service infers total_chunks from the siblings present in one
        // request, which would collapse to the batch size here.
        total_chunks: totalChunks,
      }));
      const batchKbIds = kbIds.slice(offset, offset + batchSize);

      const storeResponse: LLMStoreResponse = await storeDocuments(
        requestId,
        batch,
        "pre_chunked"
      );

      storedCount += storeResponse.stored_count ?? batch.length;
      lastMessage = storeResponse.message;

      await persistQdrantPointIds(batchKbIds, storeResponse.document_ids ?? []);
    }

    await logRequestEvent(requestId, "store_workflow_completed", {
      service: "admin",
      status: "success",
      message: `Successfully ingested ${storedCount} documents into vector database for ${sourceUrl}`,
      metadata: {
        source_url: sourceUrl,
        stored_count: storedCount,
        batch_size: batchSize,
      },
    });

    return {
      source_url: sourceUrl,
      document_count: documents.length,
      stored_count: storedCount,
      success: true,
      message: lastMessage || `Successfully stored ${storedCount} chunks in Qdrant`,
    };
  } catch (err: unknown) {
    const e = err as Error;
    await logRequestEvent(requestId, "store_workflow_failed", {
      service: "admin",
      status: "error",
      message: `Failed to push documents to LLM Store for ${sourceUrl}: ${e.message}`,
      metadata: { source_url: sourceUrl, error: e.message },
    });
    throw err;
  }
}

/**
 * Bulk pushes all unique source_urls currently stored in knowledge_base to the LLM Store API.
 */
export async function pushAllToLlmStore(requestId: string): Promise<PushResult[]> {
  const result = await query("SELECT DISTINCT source_url FROM knowledge_base");
  const urls: string[] = result.rows.map((r) => r.source_url);

  const results: PushResult[] = [];
  for (const url of urls) {
    try {
      const res = await pushToLlmStore(url, requestId);
      results.push(res);
    } catch (err: unknown) {
      const e = err as Error;
      results.push({
        source_url: url,
        document_count: 0,
        stored_count: 0,
        success: false,
        message: e.message,
      });
    }
  }

  return results;
}
