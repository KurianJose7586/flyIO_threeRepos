import { Router, Request, Response } from "express";
import { query } from "../db/pgPool";
import { requireAdminAuth } from "../middleware/requireAdminAuth";

const router = Router();

// ─────────────────────────────────────────────────────────────────────────────
// PAGES
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/cms/pages — list all pages (public) */
router.get("/api/cms/pages", async (_req: Request, res: Response) => {
  try {
    const result = await query(
      "SELECT id, slug, title, updated_at FROM pages ORDER BY slug ASC"
    );
    res.json({ success: true, pages: result.rows });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** GET /api/cms/pages/:slug — get single page by slug (public) */
router.get("/api/cms/pages/:slug", async (req: Request, res: Response) => {
  try {
    const result = await query(
      "SELECT id, slug, title, body, updated_at FROM pages WHERE slug = $1",
      [req.params.slug]
    );
    if (result.rows.length === 0) {
      res.status(404).json({ success: false, error: "Not Found", detail: `Page '${req.params.slug}' does not exist.` });
      return;
    }
    res.json({ success: true, page: result.rows[0] });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** POST /api/cms/pages — create a page. Requires admin JWT. */
router.post("/api/cms/pages", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { slug, title, body } = req.body;
    if (!slug || !title || !body) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Fields 'slug', 'title', and 'body' are all required." });
      return;
    }
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Slug must be lowercase alphanumeric with hyphens." });
      return;
    }
    await query(
      "INSERT INTO pages (slug, title, body) VALUES ($1, $2, $3)",
      [slug, title, body]
    );
    res.status(201).json({ success: true, message: `Page '${slug}' created.` });
  } catch (err: unknown) {
    const e = err as Error & { code?: string };
    if (e.code === "23505") {
      res.status(409).json({ success: false, error: "Conflict", detail: `A page with slug '${req.body.slug}' already exists.` });
      return;
    }
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** PUT /api/cms/pages/:slug — update an existing page. Requires admin JWT. */
router.put("/api/cms/pages/:slug", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { title, body } = req.body;
    const { slug } = req.params;
    if (!title && !body) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "At least one of 'title' or 'body' must be provided." });
      return;
    }
    const setClauses: string[] = [];
    const args: unknown[] = [];
    let idx = 1;
    if (title !== undefined) { setClauses.push(`title = $${idx++}`); args.push(title); }
    if (body !== undefined) { setClauses.push(`body = $${idx++}`); args.push(body); }
    setClauses.push(`updated_at = NOW()`);
    args.push(slug);
    const result = await query(
      `UPDATE pages SET ${setClauses.join(", ")} WHERE slug = $${idx}`,
      args
    );
    if (result.rowCount === 0) {
      res.status(404).json({ success: false, error: "Not Found", detail: `Page '${slug}' does not exist.` });
      return;
    }
    res.json({ success: true, message: `Page '${slug}' updated.` });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** DELETE /api/cms/pages/:slug — delete a page. Requires admin JWT. */
router.delete("/api/cms/pages/:slug", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const result = await query("DELETE FROM pages WHERE slug = $1", [req.params.slug]);
    if (result.rowCount === 0) {
      res.status(404).json({ success: false, error: "Not Found", detail: `Page '${req.params.slug}' does not exist.` });
      return;
    }
    res.json({ success: true, message: `Page '${req.params.slug}' deleted.` });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// SITE CONTENT
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/cms/content — list all site content (public) */
router.get("/api/cms/content", async (_req: Request, res: Response) => {
  try {
    const result = await query(
      "SELECT id, key, title, updated_at FROM site_content ORDER BY key ASC"
    );
    res.json({ success: true, content: result.rows });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** GET /api/cms/content/:key — get single content block (public) */
router.get("/api/cms/content/:key", async (req: Request, res: Response) => {
  try {
    const result = await query(
      "SELECT id, key, title, body, updated_at FROM site_content WHERE key = $1",
      [req.params.key]
    );
    if (result.rows.length === 0) {
      res.status(404).json({ success: false, error: "Not Found", detail: `Content '${req.params.key}' does not exist.` });
      return;
    }
    res.json({ success: true, content: result.rows[0] });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** PUT /api/cms/content/:key — upsert a content block. Requires admin JWT. */
router.put("/api/cms/content/:key", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { title, body } = req.body;
    const { key } = req.params;
    if (!body) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Field 'body' is required." });
      return;
    }
    if (!/^[a-z0-9]+(?:[-_][a-z0-9]+)*$/.test(key)) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Key must be lowercase alphanumeric with hyphens or underscores." });
      return;
    }
    await query(
      `INSERT INTO site_content (key, title, body)
       VALUES ($1, $2, $3)
       ON CONFLICT (key) DO UPDATE SET
         title = EXCLUDED.title,
         body = EXCLUDED.body,
         updated_at = NOW()`,
      [key, title || null, body]
    );
    res.json({ success: true, message: `Content '${key}' saved.` });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

export default router;
