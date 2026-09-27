import { Router, Request, Response } from "express";
import { query } from "../db/pgPool";
import { requireAdminAuth } from "../middleware/requireAdminAuth";

const router = Router();

// ─────────────────────────────────────────────────────────────
// KNOWLEDGE BASE
// ─────────────────────────────────────────────────────────────

/** GET /api/admin/knowledge-base — paginated list grouped by source_url */
router.get("/api/admin/knowledge-base", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const page  = Math.max(1, parseInt(req.query.page as string, 10) || 1);
    const limit = Math.min(100, Math.max(1, parseInt(req.query.limit as string, 10) || 20));
    const offset = (page - 1) * limit;

    const countResult = await query(
      "SELECT COUNT(DISTINCT source_url) as count FROM knowledge_base"
    );
    const total = parseInt(countResult.rows[0].count, 10);

    const result = await query(
      `SELECT
         source_url,
         extracted_metadata->>'title' AS page_title,
         COUNT(*) AS chunk_count,
         COUNT(qdrant_point_id) AS ingested_count,
         MAX(created_at) AS fetched_at
       FROM knowledge_base
       GROUP BY source_url, extracted_metadata->>'title'
       ORDER BY MAX(created_at) DESC
       LIMIT $1 OFFSET $2`,
      [limit, offset]
    );

    res.json({
      success: true,
      entries: result.rows,
      pagination: { total, page, limit, totalPages: Math.ceil(total / limit) || 1 },
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** GET /api/admin/knowledge-base/chunks?source_url=... — entries for one URL */
router.get("/api/admin/knowledge-base/chunks", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const sourceUrl = req.query.source_url as string;
    if (!sourceUrl) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "source_url query param is required." });
      return;
    }
    const result = await query(
      `SELECT 
         kb.id, 
         kb.source_url, 
         COALESCE(kb.chunk_data->>'content_text', kb.extracted_content) AS content_text,
         COALESCE(kb.chunk_data->>'content_html', '') AS content_html,
         COALESCE(kb.chunk_data->>'page_title', kb.extracted_metadata->>'title', '') AS page_title,
         COALESCE(kb.chunk_data->>'section_path', kb.extracted_metadata->>'section_path', '') AS section_path,
         COALESCE((kb.chunk_data->>'chunk_index')::int, (kb.extracted_metadata->>'chunk_index')::int, 0) AS chunk_index,
         kb.chunk_data,
         kb.job_id,
         kb.qdrant_point_id,
         kb.created_at AS fetched_at,
         j.status AS job_status
       FROM knowledge_base kb
       LEFT JOIN jobs j ON j.id = kb.job_id
       WHERE kb.source_url = $1
       ORDER BY COALESCE((kb.chunk_data->>'chunk_index')::int, (kb.extracted_metadata->>'chunk_index')::int, 0) ASC`,
      [sourceUrl]
    );

    // qdrant_point_id is whatever the LLM Store API returned when this chunk
    // was ingested, and null when it never was. It used to be recomputed here
    // from (source_url, section_path, chunk_index) on every read, which meant
    // a chunk that had never been pushed still displayed a well-formed ID —
    // looking it up in Qdrant just returned an empty result with nothing to
    // indicate the point had never existed.
    //
    // A null is not necessarily a failure, though. Chunks are pushed to the
    // vector DB in batches, so a page part-way through ingestion legitimately
    // has point IDs on its earlier chunks and nulls on the rest — for a large page
    // that window is several minutes. Reporting every null as "not ingested"
    // made a healthy crawl look like a broken one, which is the whole reason
    // the ID was worth reporting honestly in the first place. While the
    // producing job is still running, an un-ingested chunk is pending.
    const chunks = result.rows.map((row) => {
      const jobRunning =
        !!row.job_status && row.job_status !== "success" && row.job_status !== "failed";
      const { job_status, ...chunk } = row;
      return {
        ...chunk,
        qdrant_point_id: row.qdrant_point_id ?? null,
        vector_status: row.qdrant_point_id
          ? "stored"
          : jobRunning
            ? "pending"
            : "not_ingested",
      };
    });

    const ingested = chunks.filter((c) => c.qdrant_point_id).length;
    const pending = chunks.filter((c) => c.vector_status === "pending").length;

    res.json({
      success: true,
      chunks,
      // Per-URL rollup so a caller can see "40 of 58 ingested, still running"
      // without counting nulls across the chunk list itself.
      vector_summary: {
        total: chunks.length,
        ingested,
        pending,
        in_progress: pending > 0,
      },
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/**
 * DELETE /api/admin/knowledge-base?source_url=... (or ?id=...)
 * Deletes scraped content strictly from knowledge_base without affecting history.
 */
router.delete("/api/admin/knowledge-base", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const sourceUrl = req.query.source_url as string;
    const chunkId = req.query.id as string;

    if (!sourceUrl && !chunkId) {
      res.status(400).json({
        success: false,
        error: "Bad Request",
        detail: "Either 'source_url' or 'id' query parameter is required.",
      });
      return;
    }

    let result;
    if (chunkId) {
      result = await query("DELETE FROM knowledge_base WHERE id = $1", [chunkId]);
    } else {
      result = await query("DELETE FROM knowledge_base WHERE source_url = $1", [sourceUrl]);
    }

    if (result.rowCount === 0) {
      res.status(404).json({ success: false, error: "Not Found", detail: "No matching knowledge base entry found." });
      return;
    }

    res.json({
      success: true,
      message: `Deleted ${result.rowCount} entry/entries from knowledge_base. History records remain intact.`,
      deleted_count: result.rowCount,
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

// ─────────────────────────────────────────────────────────────
// CRAWL / SCRAPE HISTORY
// ─────────────────────────────────────────────────────────────

/** GET /api/admin/crawl-history — paginated history, newest first */
router.get("/api/admin/crawl-history", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const page  = Math.max(1, parseInt(req.query.page as string, 10) || 1);
    const limit = Math.min(100, Math.max(1, parseInt(req.query.limit as string, 10) || 50));
    const offset = (page - 1) * limit;

    const countResult = await query("SELECT COUNT(*) as count FROM history");
    const total = parseInt(countResult.rows[0].count, 10);

    const result = await query(
      `SELECT id, url, status, error_message, job_id, created_at
       FROM history
       ORDER BY created_at DESC
       LIMIT $1 OFFSET $2`,
      [limit, offset]
    );

    res.json({
      success: true,
      entries: result.rows,
      pagination: { total, page, limit, totalPages: Math.ceil(total / limit) || 1 },
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** DELETE /api/admin/crawl-history — delete by id, batch ids, or ?all=true */
router.delete("/api/admin/crawl-history", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = req.query.id as string;
    const ids = (req.query.ids as string) || (req.body?.ids);
    const all = req.query.all === "true";

    if (all) {
      await query("DELETE FROM history");
      res.json({ success: true, message: "All crawl history deleted." });
      return;
    }

    if (ids) {
      const idList = Array.isArray(ids)
        ? ids.map((n: any) => parseInt(n, 10)).filter((n: number) => !isNaN(n))
        : String(ids).split(",").map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n));

      if (idList.length > 0) {
        await query("DELETE FROM history WHERE id = ANY($1::int[])", [idList]);
        res.json({ success: true, message: `Deleted ${idList.length} crawl history entries.` });
        return;
      }
    }

    if (id) {
      const numId = parseInt(id, 10);
      if (isNaN(numId)) {
        res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid id parameter." });
        return;
      }
      const result = await query("DELETE FROM history WHERE id = $1", [numId]);
      if (result.rowCount === 0) {
        res.status(404).json({ success: false, error: "Not Found", detail: "Crawl history entry not found." });
        return;
      }
      res.json({ success: true, message: `Crawl history entry #${numId} deleted.` });
      return;
    }

    res.status(400).json({ success: false, error: "Bad Request", detail: "Query parameter 'id', 'ids', or 'all=true' is required." });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** DELETE /api/admin/crawl-history/:id — delete specific entry */
router.delete("/api/admin/crawl-history/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const numId = parseInt(req.params.id, 10);
    if (isNaN(numId)) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid id parameter." });
      return;
    }
    const result = await query("DELETE FROM history WHERE id = $1", [numId]);
    if (result.rowCount === 0) {
      res.status(404).json({ success: false, error: "Not Found", detail: "Crawl history entry not found." });
      return;
    }
    res.json({ success: true, message: `Crawl history entry #${numId} deleted.` });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

export default router;
