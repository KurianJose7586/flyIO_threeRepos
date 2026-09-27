import { query } from "../db/pgPool";

/**
 * Migration 002: blog_posts table.
 * Idempotent (IF NOT EXISTS).
 */
export async function runMigration002(): Promise<void> {
  console.log("[DB] Running migration 002 — blog_posts...");

  await query(`
    CREATE TABLE IF NOT EXISTS blog_posts (
      id               SERIAL PRIMARY KEY,
      slug             TEXT NOT NULL UNIQUE,
      title            TEXT NOT NULL,
      body             TEXT NOT NULL,
      meta_title       TEXT,
      meta_description TEXT,
      published_at     TIMESTAMPTZ,
      created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_blog_posts_slug
    ON blog_posts(slug)
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_blog_posts_published
    ON blog_posts(published_at)
  `);

  console.log("[DB] Migration 002 complete — blog_posts");
}
