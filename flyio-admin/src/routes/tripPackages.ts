import { Router, Request, Response } from "express";
import { query } from "../db/pgPool";
import { requireAdminAuth } from "../middleware/requireAdminAuth";

const router = Router();

const isValidSlug = (s: string) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(s);

// ─────────────────────────────────────────────────────────────
// PUBLIC TRIP ROUTES
// ─────────────────────────────────────────────────────────────

/** GET /api/trips/packages — list published packages (public) */
router.get("/api/trips/packages", async (req: Request, res: Response) => {
  try {
    const page  = Math.max(1, parseInt(req.query.page as string, 10) || 1);
    const limit = Math.min(50, Math.max(1, parseInt(req.query.limit as string, 10) || 12));
    const offset = (page - 1) * limit;
    const countResult = await query(
      "SELECT COUNT(*) as count FROM trip_packages WHERE published_at IS NOT NULL"
    );
    const total = parseInt(countResult.rows[0].count, 10);
    const result = await query(
      `SELECT id, slug, title, description, itinerary_json, images, price_tier, published_at, created_at, updated_at
       FROM trip_packages
       WHERE published_at IS NOT NULL
       ORDER BY published_at DESC
       LIMIT $1 OFFSET $2`,
      [limit, offset]
    );
    res.json({
      success: true,
      packages: result.rows,
      pagination: { total, page, limit, totalPages: Math.ceil(total / limit) || 1 },
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** GET /api/trips/packages/:slug — single published package (public) */
router.get("/api/trips/packages/:slug", async (req: Request, res: Response) => {
  try {
    const result = await query(
      `SELECT id, slug, title, description, itinerary_json, images, price_tier, published_at, created_at, updated_at
       FROM trip_packages WHERE slug = $1 AND published_at IS NOT NULL`,
      [req.params.slug]
    );
    if (result.rows.length === 0) {
      res.status(404).json({ success: false, error: "Not Found", detail: `Trip package '${req.params.slug}' not found.` });
      return;
    }
    res.json({ success: true, package: result.rows[0] });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

// ─────────────────────────────────────────────────────────────
// ADMIN TRIP ROUTES
// ─────────────────────────────────────────────────────────────

/** GET /api/admin/trips/packages — list ALL packages (admin) */
router.get("/api/admin/trips/packages", requireAdminAuth, async (_req: Request, res: Response) => {
  try {
    const result = await query(
      `SELECT id, slug, title, description, itinerary_json, images, price_tier, published_at, created_at, updated_at
       FROM trip_packages ORDER BY updated_at DESC`
    );
    res.json({ success: true, packages: result.rows });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** GET /api/admin/trips/packages/:id — single by ID (admin) */
router.get("/api/admin/trips/packages/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) { res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid package ID." }); return; }
    const result = await query(
      `SELECT id, slug, title, description, itinerary_json, images, price_tier, published_at, created_at, updated_at
       FROM trip_packages WHERE id = $1`,
      [id]
    );
    if (result.rows.length === 0) { res.status(404).json({ success: false, error: "Not Found", detail: `Trip package #${id} not found.` }); return; }
    res.json({ success: true, package: result.rows[0] });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** POST /api/admin/trips/packages — create (admin) */
router.post("/api/admin/trips/packages", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { title, slug, description, itinerary_json, images, price_tier, publish } = req.body;
    if (!title || !slug || !description || !itinerary_json) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Fields 'title', 'slug', 'description', and 'itinerary_json' are required." });
      return;
    }
    if (!isValidSlug(slug)) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Slug must be lowercase alphanumeric with hyphens." });
      return;
    }
    try {
      if (typeof itinerary_json === "string") JSON.parse(itinerary_json);
    } catch {
      res.status(400).json({ success: false, error: "Bad Request", detail: "'itinerary_json' must be valid JSON." });
      return;
    }
    const itineraryStr = typeof itinerary_json === "object" ? JSON.stringify(itinerary_json) : itinerary_json;
    const imagesStr    = typeof images === "object" ? JSON.stringify(images) : (images || "");
    const publishedAt  = publish === true ? new Date().toISOString() : null;
    const result = await query(
      `INSERT INTO trip_packages (title, slug, description, itinerary_json, images, price_tier, published_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       RETURNING id`,
      [title, slug, description, itineraryStr, imagesStr, price_tier || "Standard", publishedAt]
    );
    res.status(201).json({ success: true, message: `Trip package '${title}' created.`, id: result.rows[0].id, slug });
  } catch (err: unknown) {
    const e = err as Error & { code?: string };
    if (e.code === "23505") {
      res.status(409).json({ success: false, error: "Conflict", detail: `A trip package with slug '${req.body.slug}' already exists.` });
      return;
    }
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** PUT /api/admin/trips/packages/:id — update (admin) */
router.put("/api/admin/trips/packages/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) { res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid package ID." }); return; }
    const { title, slug, description, itinerary_json, images, price_tier, publish } = req.body;
    if (slug && !isValidSlug(slug)) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Slug must be lowercase alphanumeric with hyphens." });
      return;
    }
    const existing = await query("SELECT id FROM trip_packages WHERE id = $1", [id]);
    if (existing.rows.length === 0) { res.status(404).json({ success: false, error: "Not Found", detail: `Trip package #${id} not found.` }); return; }

    const setClauses: string[] = [];
    const args: unknown[] = [];
    let idx = 1;
    if (title !== undefined)         { setClauses.push(`title = $${idx++}`);         args.push(title); }
    if (slug !== undefined)          { setClauses.push(`slug = $${idx++}`);          args.push(slug); }
    if (description !== undefined)   { setClauses.push(`description = $${idx++}`);   args.push(description); }
    if (itinerary_json !== undefined) {
      const s = typeof itinerary_json === "object" ? JSON.stringify(itinerary_json) : itinerary_json;
      setClauses.push(`itinerary_json = $${idx++}`); args.push(s);
    }
    if (images !== undefined) {
      const s = typeof images === "object" ? JSON.stringify(images) : images;
      setClauses.push(`images = $${idx++}`); args.push(s);
    }
    if (price_tier !== undefined)    { setClauses.push(`price_tier = $${idx++}`);    args.push(price_tier); }
    if (publish !== undefined)       { setClauses.push(`published_at = $${idx++}`);  args.push(publish ? new Date().toISOString() : null); }
    setClauses.push(`updated_at = NOW()`);
    args.push(id);
    await query(`UPDATE trip_packages SET ${setClauses.join(", ")} WHERE id = $${idx}`, args);
    res.json({ success: true, message: `Trip package #${id} updated.` });
  } catch (err: unknown) {
    const e = err as Error & { code?: string };
    if (e.code === "23505") {
      res.status(409).json({ success: false, error: "Conflict", detail: `A trip package with slug '${req.body.slug}' already exists.` });
      return;
    }
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** DELETE /api/admin/trips/packages/:id — delete (admin) */
router.delete("/api/admin/trips/packages/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) { res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid package ID." }); return; }
    const result = await query("DELETE FROM trip_packages WHERE id = $1", [id]);
    if (result.rowCount === 0) { res.status(404).json({ success: false, error: "Not Found", detail: `Trip package #${id} not found.` }); return; }
    res.json({ success: true, message: `Trip package #${id} deleted.` });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

export default router;
