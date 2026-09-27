import { Router, Request, Response } from "express";
import { query } from "../db/pgPool";
import { requireAdminAuth } from "../middleware/requireAdminAuth";
import { env } from "../config/env";
import multer from "multer";
import path from "path";
import fs from "fs";
import { v4 as uuidv4 } from "uuid";

const router = Router();

// Ensure upload directory exists (from env config)
const uploadDir = path.resolve(env.BLOG_UPLOAD_DIR);
if (!fs.existsSync(uploadDir)) {
  fs.mkdirSync(uploadDir, { recursive: true });
}

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, uploadDir),
  filename: (_req, file, cb) => {
    const ext = path.extname(file.originalname);
    cb(null, `${uuidv4()}${ext}`);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: 10 * 1024 * 1024 }, // 10 MB
  fileFilter: (_req, file, cb) => {
    const allowed = /\.(jpg|jpeg|png|gif|webp|svg|avif)$/i;
    if (allowed.test(path.extname(file.originalname))) {
      cb(null, true);
    } else {
      cb(new Error("Only image files (jpg, jpeg, png, gif, webp, svg, avif) are allowed."));
    }
  },
});

const isValidSlug = (s: string) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(s);

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC BLOG ROUTES
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/blog/posts — list published posts (public) */
router.get("/api/blog/posts", async (req: Request, res: Response) => {
  try {
    const page  = Math.max(1, parseInt(req.query.page as string, 10) || 1);
    const limit = Math.min(50, Math.max(1, parseInt(req.query.limit as string, 10) || 10));
    const offset = (page - 1) * limit;

    // Configurable sort — whitelist allowed columns to prevent SQL injection
    const allowedSortFields: Record<string, string> = {
      author: "bp.author",
      created_at: "bp.created_at",
    };
    const sortParam = (req.query.sort as string) || "created_at";
    const sortColumn = allowedSortFields[sortParam] || allowedSortFields.created_at;

    const allowedOrders = ["asc", "desc"];
    const orderParam = ((req.query.order as string) || "desc").toLowerCase();
    const sortOrder = allowedOrders.includes(orderParam) ? orderParam.toUpperCase() : "DESC";

    const countResult = await query(
      "SELECT COUNT(*) as count FROM blog_posts WHERE published_at IS NOT NULL"
    );
    const total = parseInt(countResult.rows[0].count, 10);

    const result = await query(
      `SELECT bp.id, bp.slug, bp.title, bp.summary, bp.author, bp.banner,
              bp.category_id, c.name AS category_name,
              bp.meta_title, bp.meta_description, bp.published_at, bp.created_at, bp.updated_at,
              COALESCE(
                (SELECT json_agg(json_build_object('id', t.id, 'name', t.name, 'slug', t.slug))
                 FROM blog_post_tags bpt
                 INNER JOIN tags t ON t.id = bpt.tag_id
                 WHERE bpt.blog_post_id = bp.id),
                '[]'::json
              ) AS tags
       FROM blog_posts bp
       LEFT JOIN categories c ON bp.category_id = c.id
       WHERE bp.published_at IS NOT NULL
       ORDER BY ${sortColumn} ${sortOrder}
       LIMIT $1 OFFSET $2`,
      [limit, offset]
    );
    res.json({
      success: true,
      posts: result.rows,
      pagination: { total, page, limit, totalPages: Math.ceil(total / limit) || 1 },
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** GET /api/blog/posts/:slug — get single published post (public) */
router.get("/api/blog/posts/:slug", async (req: Request, res: Response) => {
  try {
    const result = await query(
      `SELECT bp.id, bp.slug, bp.title, bp.body, bp.summary, bp.author, bp.banner,
              bp.category_id, c.name AS category_name, c.slug AS category_slug,
              bp.meta_title, bp.meta_description, bp.published_at, bp.created_at, bp.updated_at
       FROM blog_posts bp
       LEFT JOIN categories c ON bp.category_id = c.id
       WHERE bp.slug = $1 AND bp.published_at IS NOT NULL`,
      [req.params.slug]
    );
    if (result.rows.length === 0) {
      res.status(404).json({ success: false, error: "Not Found", detail: `Blog post '${req.params.slug}' not found.` });
      return;
    }

    const post = result.rows[0];

    // Fetch expanded tags for this post
    const tagsResult = await query(
      `SELECT t.id, t.name, t.slug
       FROM tags t
       INNER JOIN blog_post_tags bpt ON bpt.tag_id = t.id
       WHERE bpt.blog_post_id = $1
       ORDER BY t.name ASC`,
      [post.id]
    );
    post.tags = tagsResult.rows;

    res.json({ success: true, post });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// ADMIN BLOG ROUTES
// ─────────────────────────────────────────────────────────────────────────────

/** GET /api/admin/blog/posts — list ALL posts (admin) */
router.get("/api/admin/blog/posts", requireAdminAuth, async (_req: Request, res: Response) => {
  try {
    const result = await query(
      `SELECT bp.id, bp.slug, bp.title, bp.body, bp.summary, bp.author, bp.banner,
              bp.category_id, c.name AS category_name,
              bp.meta_title, bp.meta_description, bp.published_at, bp.created_at, bp.updated_at,
              COALESCE(
                (SELECT json_agg(bpt.tag_id) FROM blog_post_tags bpt WHERE bpt.blog_post_id = bp.id),
                '[]'::json
              ) AS tag_ids
       FROM blog_posts bp
       LEFT JOIN categories c ON bp.category_id = c.id
       ORDER BY bp.updated_at DESC`
    );
    res.json({ success: true, posts: result.rows });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** GET /api/admin/blog/posts/:id — single post by ID (admin) */
router.get("/api/admin/blog/posts/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) { res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid post ID." }); return; }
    const result = await query(
      `SELECT bp.id, bp.slug, bp.title, bp.body, bp.summary, bp.author, bp.banner,
              bp.category_id, c.name AS category_name,
              bp.meta_title, bp.meta_description, bp.published_at, bp.created_at, bp.updated_at,
              COALESCE(
                (SELECT json_agg(bpt.tag_id) FROM blog_post_tags bpt WHERE bpt.blog_post_id = bp.id),
                '[]'::json
              ) AS tag_ids
       FROM blog_posts bp
       LEFT JOIN categories c ON bp.category_id = c.id
       WHERE bp.id = $1`,
      [id]
    );
    if (result.rows.length === 0) { res.status(404).json({ success: false, error: "Not Found", detail: `Blog post #${id} not found.` }); return; }
    res.json({ success: true, post: result.rows[0] });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

const slugify = (text: string) =>
  text.toLowerCase().trim().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-").replace(/^-+|-+$/g, "");

/** POST /api/admin/blog/posts — create a post (admin) */
router.post("/api/admin/blog/posts", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const { title, slug, body, summary, author, banner, category_id, tag_ids, meta_title, meta_description, publish } = req.body;
    if (!title || !body) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Fields 'title' and 'body' are required." });
      return;
    }

    const cleanSlug = (typeof slug === "string" && slug.trim()) ? slug.trim().toLowerCase().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-") : slugify(title);

    if (!cleanSlug || !isValidSlug(cleanSlug)) {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Slug must be lowercase alphanumeric with hyphens." });
      return;
    }

    // Sanitize category_id
    const cleanCategoryId = category_id !== undefined && category_id !== null && category_id !== "" && !isNaN(Number(category_id)) && Number(category_id) > 0
      ? Number(category_id)
      : null;

    if (cleanCategoryId !== null) {
      const catCheck = await query("SELECT id FROM categories WHERE id = $1", [cleanCategoryId]);
      if (catCheck.rows.length === 0) {
        res.status(400).json({ success: false, error: "Bad Request", detail: `Category #${cleanCategoryId} does not exist.` });
        return;
      }
    }

    const publishedAt = publish === true ? new Date().toISOString() : null;
    const result = await query(
      `INSERT INTO blog_posts (title, slug, body, summary, author, banner, category_id, meta_title, meta_description, published_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
       RETURNING id`,
      [
        title, cleanSlug, body,
        summary || null, author || null, banner || null,
        cleanCategoryId,
        meta_title || null, meta_description || null,
        publishedAt,
      ]
    );
    const postId = result.rows[0].id;

    // Filter and insert valid tag associations
    if (Array.isArray(tag_ids) && tag_ids.length > 0) {
      const validTagIds = tag_ids.map((id: unknown) => Number(id)).filter((id: number) => !isNaN(id) && id > 0);
      if (validTagIds.length > 0) {
        const tagCheck = await query("SELECT id FROM tags WHERE id = ANY($1::int[])", [validTagIds]);
        const existingTagIds = new Set(tagCheck.rows.map((r: { id: number }) => r.id));
        const filteredTagIds = validTagIds.filter((id) => existingTagIds.has(id));

        if (filteredTagIds.length > 0) {
          const tagValues = filteredTagIds.map((_: unknown, i: number) => `($1, $${i + 2})`).join(", ");
          await query(
            `INSERT INTO blog_post_tags (blog_post_id, tag_id) VALUES ${tagValues} ON CONFLICT DO NOTHING`,
            [postId, ...filteredTagIds]
          );
        }
      }
    }

    res.status(201).json({ success: true, message: `Blog post '${title}' created.`, id: postId, slug: cleanSlug });
  } catch (err: unknown) {
    const e = err as Error & { code?: string };
    if (e.code === "23505") {
      res.status(409).json({ success: false, error: "Conflict", detail: `A blog post with slug '${req.body.slug}' already exists.` });
      return;
    }
    if (e.code === "23503") {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Referenced category or tag does not exist." });
      return;
    }
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** PUT /api/admin/blog/posts/:id — update a post (admin) */
router.put("/api/admin/blog/posts/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) { res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid post ID." }); return; }

    const { title, slug, body, summary, author, banner, category_id, tag_ids, meta_title, meta_description, publish } = req.body;
    
    let cleanSlug = undefined;
    if (slug !== undefined) {
      cleanSlug = (typeof slug === "string" && slug.trim()) ? slug.trim().toLowerCase().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-") : (title ? slugify(title) : undefined);
      if (cleanSlug && !isValidSlug(cleanSlug)) {
        res.status(400).json({ success: false, error: "Bad Request", detail: "Slug must be lowercase alphanumeric with hyphens." });
        return;
      }
    }

    const existing = await query("SELECT id FROM blog_posts WHERE id = $1", [id]);
    if (existing.rows.length === 0) { res.status(404).json({ success: false, error: "Not Found", detail: `Blog post #${id} not found.` }); return; }

    // Sanitize category_id
    let cleanCategoryId: number | null | undefined = undefined;
    if (category_id !== undefined) {
      cleanCategoryId = category_id !== null && category_id !== "" && !isNaN(Number(category_id)) && Number(category_id) > 0
        ? Number(category_id)
        : null;

      if (cleanCategoryId !== null) {
        const catCheck = await query("SELECT id FROM categories WHERE id = $1", [cleanCategoryId]);
        if (catCheck.rows.length === 0) {
          res.status(400).json({ success: false, error: "Bad Request", detail: `Category #${cleanCategoryId} does not exist.` });
          return;
        }
      }
    }

    const setClauses: string[] = [];
    const args: unknown[] = [];
    let idx = 1;
    if (title !== undefined)            { setClauses.push(`title = $${idx++}`);            args.push(title); }
    if (cleanSlug !== undefined)        { setClauses.push(`slug = $${idx++}`);             args.push(cleanSlug); }
    if (body !== undefined)             { setClauses.push(`body = $${idx++}`);             args.push(body); }
    if (summary !== undefined)          { setClauses.push(`summary = $${idx++}`);          args.push(summary); }
    if (author !== undefined)           { setClauses.push(`author = $${idx++}`);           args.push(author); }
    if (banner !== undefined)           { setClauses.push(`banner = $${idx++}`);           args.push(banner); }
    if (category_id !== undefined)      { setClauses.push(`category_id = $${idx++}`);      args.push(cleanCategoryId); }
    if (meta_title !== undefined)       { setClauses.push(`meta_title = $${idx++}`);       args.push(meta_title); }
    if (meta_description !== undefined) { setClauses.push(`meta_description = $${idx++}`); args.push(meta_description); }
    if (publish !== undefined)          { setClauses.push(`published_at = $${idx++}`);     args.push(publish ? new Date().toISOString() : null); }
    setClauses.push(`updated_at = NOW()`);
    args.push(id);

    await query(`UPDATE blog_posts SET ${setClauses.join(", ")} WHERE id = $${idx}`, args);

    // Update tag associations if provided
    if (Array.isArray(tag_ids)) {
      await query("DELETE FROM blog_post_tags WHERE blog_post_id = $1", [id]);
      const validTagIds = tag_ids.map((tid: unknown) => Number(tid)).filter((tid: number) => !isNaN(tid) && tid > 0);
      if (validTagIds.length > 0) {
        const tagCheck = await query("SELECT id FROM tags WHERE id = ANY($1::int[])", [validTagIds]);
        const existingTagIds = new Set(tagCheck.rows.map((r: { id: number }) => r.id));
        const filteredTagIds = validTagIds.filter((tid) => existingTagIds.has(tid));

        if (filteredTagIds.length > 0) {
          const tagValues = filteredTagIds.map((_: unknown, i: number) => `($1, $${i + 2})`).join(", ");
          await query(
            `INSERT INTO blog_post_tags (blog_post_id, tag_id) VALUES ${tagValues} ON CONFLICT DO NOTHING`,
            [id, ...filteredTagIds]
          );
        }
      }
    }

    res.json({ success: true, message: `Blog post #${id} updated.` });
  } catch (err: unknown) {
    const e = err as Error & { code?: string };
    if (e.code === "23505") {
      res.status(409).json({ success: false, error: "Conflict", detail: `A blog post with slug '${req.body.slug}' already exists.` });
      return;
    }
    if (e.code === "23503") {
      res.status(400).json({ success: false, error: "Bad Request", detail: "Referenced category or tag does not exist." });
      return;
    }
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** DELETE /api/admin/blog/posts/:id — delete a post (admin) */
router.delete("/api/admin/blog/posts/:id", requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) { res.status(400).json({ success: false, error: "Bad Request", detail: "Invalid post ID." }); return; }
    // Delete tag associations first (cascade handles this, but explicit for clarity)
    await query("DELETE FROM blog_post_tags WHERE blog_post_id = $1", [id]);
    const result = await query("DELETE FROM blog_posts WHERE id = $1", [id]);
    if (result.rowCount === 0) { res.status(404).json({ success: false, error: "Not Found", detail: `Blog post #${id} not found.` }); return; }
    res.json({ success: true, message: `Blog post #${id} deleted.` });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({ success: false, error: "Internal Server Error", detail: e.message });
  }
});

/** POST /api/admin/blog/upload-banner — upload a banner image (admin) */
router.post("/api/admin/blog/upload-banner", requireAdminAuth, upload.single("banner"), (req: Request, res: Response) => {
  if (!req.file) {
    res.status(400).json({ success: false, error: "Bad Request", detail: "No file uploaded. Send a 'banner' field with multipart/form-data." });
    return;
  }
  // Build the public URL path based on the configured upload dir name
  const relativePath = path.basename(env.BLOG_UPLOAD_DIR);
  const url = `/uploads/${relativePath}/${req.file.filename}`;
  res.json({ success: true, url });
});

export default router;
