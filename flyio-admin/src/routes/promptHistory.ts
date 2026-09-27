import { Router, Request, Response } from "express";
import { query } from "../db/pgPool";
import { requireAdminAuth } from "../middleware/requireAdminAuth";

const router = Router();

/**
 * GET /api/admin/prompts
 * Paginated list of prompt history, newest first.
 */
router.get("/api/admin/prompts", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const page = Math.max(1, parseInt(req.query.page as string, 10) || 1);
    const limit = Math.min(100, Math.max(1, parseInt(req.query.limit as string, 10) || 20));
    const offset = (page - 1) * limit;

    const countResult = await query("SELECT COUNT(*) as count FROM prompt_history");
    const total = parseInt(countResult.rows[0].count, 10);

    const result = await query(
      `SELECT id, request_id, prompt_text, status, metadata,
              response_data->>'message' AS summary_message,
              CASE WHEN response_data->'plan' IS NOT NULL THEN true ELSE false END AS has_plan,
              created_at, updated_at
       FROM prompt_history
       ORDER BY created_at DESC
       LIMIT $1 OFFSET $2`,
      [limit, offset]
    );

    res.json({
      success: true,
      prompts: result.rows,
      pagination: {
        total,
        page,
        limit,
        totalPages: Math.ceil(total / limit) || 1,
      },
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/**
 * GET /api/admin/prompts/:request_id
 * Retrieves a single prompt history record by request_id along with its cross-service event trace.
 */
router.get("/api/admin/prompts/:request_id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { request_id } = req.params;

    const promptResult = await query(
      "SELECT * FROM prompt_history WHERE request_id = $1",
      [request_id]
    );

    if (promptResult.rows.length === 0) {
      res.status(404).json({
        success: false,
        error: "Not Found",
        detail: `Prompt record for request_id '${request_id}' not found.`,
      });
      return;
    }

    // Retrieve correlated events across all services for this request_id
    const eventsResult = await query(
      `SELECT id, request_id, service, event_type, status, message, metadata, created_at
       FROM request_events
       WHERE request_id = $1
       ORDER BY created_at ASC`,
      [request_id]
    );

    res.json({
      success: true,
      prompt: promptResult.rows[0],
      events: eventsResult.rows,
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/**
 * DELETE /api/admin/prompts/:request_id
 * Deletes a prompt history record and its associated request events.
 */
router.delete("/api/admin/prompts/:request_id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { request_id } = req.params;

    const result = await query(
      "DELETE FROM prompt_history WHERE request_id = $1",
      [request_id]
    );

    if (result.rowCount === 0) {
      res.status(404).json({
        success: false,
        error: "Not Found",
        detail: `Prompt record for request_id '${request_id}' not found.`,
      });
      return;
    }

    // Clean up corresponding events
    await query("DELETE FROM request_events WHERE request_id = $1", [request_id]);

    res.json({
      success: true,
      message: `Prompt record '${request_id}' and associated event logs deleted.`,
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

export default router;
