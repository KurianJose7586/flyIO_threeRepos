import { Router, Request, Response } from "express";
import { query } from "../db/pgPool";
import { requireAdminAuth } from "../middleware/requireAdminAuth";
import { env } from "../config/env";

const router = Router();

const isValidSlug = (s: string) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(s);

// ─────────────────────────────────────────────────────────────────────────────
// CATEGORIES CRUD (admin-only)
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/admin/blog/categories — list all categories */
router.get("/api/admin/blog/categories", requireAdminAuth, async (_req: Request, res: Response) => {
  try {
    const result = await query("SELECT id, name, slug, created_at FROM categories ORDER BY name ASC");
    res.json({ success: true, categories: result.rows });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

const slugify = (text: string) =>
  text.toLowerCase().trim().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-").replace(/^-+|-+$/g, "");

/** POST /api/admin/blog/categories — create a category */
router.post("/api/admin/blog/categories", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { name, slug } = req.body;
    if (!name || typeof name !== "string" || !name.trim()) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Field 'name' is required." });
      return;
    }

    const cleanName = name.trim();
    const cleanSlug = (typeof slug === "string" && slug.trim())
      ? slug.trim().toLowerCase().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-")
      : slugify(cleanName);

    if (!cleanSlug || !isValidSlug(cleanSlug)) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Slug must be lowercase alphanumeric with hyphens." });
      return;
    }

    const result = await query(
      "INSERT INTO categories (name, slug) VALUES ($1, $2) RETURNING id",
      [cleanName, cleanSlug]
    );
    res.status(201).json({ success: true, message: `Category '${cleanName}' created.`, id: result.rows[0].id, slug: cleanSlug });
  } catch (err: unknown) {
    const e = err as Error & { code?: string };
    if (e.code === "23505") {
      res.status(409).json({ success: false, error: "Conflict", detail: "A category with that name or slug already exists." });
      return;
    }
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** PUT /api/admin/blog/categories/:id — update a category */
router.put("/api/admin/blog/categories/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) { res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid category ID." }); return; }

    const { name, slug } = req.body;
    let cleanSlug: string | undefined = undefined;
    if (slug !== undefined) {
      cleanSlug = (typeof slug === "string" && slug.trim())
        ? slug.trim().toLowerCase().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-")
        : (name ? slugify(name) : undefined);
      if (cleanSlug && !isValidSlug(cleanSlug)) {
        res.status(400).json({ success: false, error: "Bad Request", detail: "Slug must be lowercase alphanumeric with hyphens." });
        return;
      }
    }

    const existing = await query("SELECT id FROM categories WHERE id = $1", [id]);
    if (existing.rows.length === 0) { res.status(404).json({ success: false, error: "Not Found", detail: `Category #${id} not found.` }); return; }

    const setClauses: string[] = [];
    const args: unknown[] = [];
    let idx = 1;
    if (name !== undefined) { setClauses.push(`name = $${idx++}`); args.push(name.trim()); }
    if (cleanSlug !== undefined) { setClauses.push(`slug = $${idx++}`); args.push(cleanSlug); }

    if (setClauses.length === 0) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "No fields to update." });
      return;
    }

    args.push(id);
    await query(`UPDATE categories SET ${setClauses.join(", ")} WHERE id = $${idx}`, args);
    res.json({ success: true, message: `Category #${id} updated.` });
  } catch (err: unknown) {
    const e = err as Error & { code?: string };
    if (e.code === "23505") {
      res.status(409).json({ success: false, error: "Conflict", detail: "A category with that name or slug already exists." });
      return;
    }
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** DELETE /api/admin/blog/categories/:id — delete a category */
router.delete("/api/admin/blog/categories/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) { res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid category ID." }); return; }
    const result = await query("DELETE FROM categories WHERE id = $1", [id]);
    if (result.rowCount === 0) { res.status(404).json({ success: false, error: "Not Found", detail: `Category #${id} not found.` }); return; }
    res.json({ success: true, message: `Category #${id} deleted.` });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// TAGS CRUD (admin-only)
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/admin/blog/tags — list all tags */
router.get("/api/admin/blog/tags", requireAdminAuth, async (_req: Request, res: Response) => {
  try {
    const result = await query("SELECT id, name, slug, created_at FROM tags ORDER BY name ASC");
    res.json({ success: true, tags: result.rows });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** POST /api/admin/blog/tags — create a tag */
router.post("/api/admin/blog/tags", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { name, slug } = req.body;
    if (!name || typeof name !== "string" || !name.trim()) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Field 'name' is required." });
      return;
    }

    const cleanName = name.trim();
    const cleanSlug = (typeof slug === "string" && slug.trim())
      ? slug.trim().toLowerCase().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-")
      : slugify(cleanName);

    if (!cleanSlug || !isValidSlug(cleanSlug)) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Slug must be lowercase alphanumeric with hyphens." });
      return;
    }

    const result = await query(
      "INSERT INTO tags (name, slug) VALUES ($1, $2) RETURNING id",
      [cleanName, cleanSlug]
    );
    res.status(201).json({ success: true, message: `Tag '${cleanName}' created.`, id: result.rows[0].id, slug: cleanSlug });
  } catch (err: unknown) {
    const e = err as Error & { code?: string };
    if (e.code === "23505") {
      res.status(409).json({ success: false, error: "Conflict", detail: "A tag with that name or slug already exists." });
      return;
    }
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** PUT /api/admin/blog/tags/:id — update a tag */
router.put("/api/admin/blog/tags/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) { res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid tag ID." }); return; }

    const { name, slug } = req.body;
    let cleanSlug: string | undefined = undefined;
    if (slug !== undefined) {
      cleanSlug = (typeof slug === "string" && slug.trim())
        ? slug.trim().toLowerCase().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-")
        : (name ? slugify(name) : undefined);
      if (cleanSlug && !isValidSlug(cleanSlug)) {
        res.status(400).json({ success: false, error: "Bad Request", detail: "Slug must be lowercase alphanumeric with hyphens." });
        return;
      }
    }

    const existing = await query("SELECT id FROM tags WHERE id = $1", [id]);
    if (existing.rows.length === 0) { res.status(404).json({ success: false, error: "Not Found", detail: `Tag #${id} not found.` }); return; }

    const setClauses: string[] = [];
    const args: unknown[] = [];
    let idx = 1;
    if (name !== undefined) { setClauses.push(`name = $${idx++}`); args.push(name.trim()); }
    if (cleanSlug !== undefined) { setClauses.push(`slug = $${idx++}`); args.push(cleanSlug); }

    if (setClauses.length === 0) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "No fields to update." });
      return;
    }

    args.push(id);
    await query(`UPDATE tags SET ${setClauses.join(", ")} WHERE id = $${idx}`, args);
    res.json({ success: true, message: `Tag #${id} updated.` });
  } catch (err: unknown) {
    const e = err as Error & { code?: string };
    if (e.code === "23505") {
      res.status(409).json({ success: false, error: "Conflict", detail: "A tag with that name or slug already exists." });
      return;
    }
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** DELETE /api/admin/blog/tags/:id — delete a tag */
router.delete("/api/admin/blog/tags/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) { res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid tag ID." }); return; }
    const result = await query("DELETE FROM tags WHERE id = $1", [id]);
    if (result.rowCount === 0) { res.status(404).json({ success: false, error: "Not Found", detail: `Tag #${id} not found.` }); return; }
    res.json({ success: true, message: `Tag #${id} deleted.` });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// CKEDITOR CONFIG (admin-only)
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/admin/config/ckeditor — returns CKEditor toolbar config from env */
router.get("/api/admin/config/ckeditor", requireAdminAuth, (_req: Request, res: Response) => {
  res.json({
    success: true,
    toolbar: env.CKEDITOR_TOOLBAR,
  });
});

export default router;
