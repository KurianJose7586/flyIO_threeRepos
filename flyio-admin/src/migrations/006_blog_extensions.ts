import { query } from "../db/pgPool";

/**
 * Migration 006: Blog extensions.
 * - categories table
 * - tags table
 * - blog_post_tags join table (many-to-many)
 * - ALTER blog_posts: add summary, author, banner, category_id
 *
 * Idempotent (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
 */
export async function runMigration006(): Promise<void> {
  console.log("[DB] Running migration 006 — blog extensions...");

  // ── categories table ───────────────────────────────────────────
  await query(`
    CREATE TABLE IF NOT EXISTS categories (
      id         SERIAL PRIMARY KEY,
      name       TEXT NOT NULL UNIQUE,
      slug       TEXT NOT NULL UNIQUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  // ── tags table ─────────────────────────────────────────────────
  await query(`
    CREATE TABLE IF NOT EXISTS tags (
      id         SERIAL PRIMARY KEY,
      name       TEXT NOT NULL UNIQUE,
      slug       TEXT NOT NULL UNIQUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  // ── blog_post_tags join table ──────────────────────────────────
  await query(`
    CREATE TABLE IF NOT EXISTS blog_post_tags (
      blog_post_id INTEGER NOT NULL REFERENCES blog_posts(id) ON DELETE CASCADE,
      tag_id       INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
      PRIMARY KEY (blog_post_id, tag_id)
    )
  `);

  // ── Extend blog_posts with new columns ─────────────────────────
  await query(`ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS summary TEXT`);
  await query(`ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS author TEXT`);
  await query(`ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS banner TEXT`);
  await query(
    `ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL`
  );

  // ── Indexes ────────────────────────────────────────────────────
  await query(`CREATE INDEX IF NOT EXISTS idx_blog_posts_category ON blog_posts(category_id)`);
  await query(`CREATE INDEX IF NOT EXISTS idx_blog_posts_author ON blog_posts(author)`);
  await query(`CREATE INDEX IF NOT EXISTS idx_blog_post_tags_tag ON blog_post_tags(tag_id)`);

  console.log("[DB] Migration 006 complete — blog extensions");
}
